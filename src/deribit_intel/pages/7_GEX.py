"""GEX — Gamma Exposure (crypto-adapted dealer-gamma framework)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.gex_engine import (
    compute_gex_by_strike,
    compute_gex_timeseries,
    compute_gex_by_expiry,
    compute_max_pain,
    compute_charm_pressure,
    compute_vanna_exposure,
    find_key_levels,
    compute_gex_by_strike_split,
    compute_gex_at_hour,
)

# ── constants ────────────────────────────────────────────────────────
BG = "#0e1117"
GREEN = "#26a69a"
RED = "#ef5350"
ORANGE = "#ffa726"
BLUE = "#42a5f5"
PURPLE = "#ab47bc"

# ── page config ──────────────────────────────────────────────────────
st.title("Gamma Exposure (GEX)")
st.caption(
    "Crypto-adapted dealer-gamma framework. "
    "**Equity GEX** = calls positive / puts negative (standard). "
    "**Crypto GEX** = both calls and puts negative (dealers net short gamma in spot-driven crypto markets). "
    "Key levels derived from absolute GEX concentration are most reliable."
)

path = resolve_input_path("gex")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))

# ── sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("GEX settings")
    tte_max = st.slider("Max DTE", 1, 365, 90,
                        help="Exclude far-expiry options to focus on near-term gamma.")
    strike_range_pct = st.slider("Strike range ± spot (%)", 5, 80, 25,
                                 help="Narrows the view → fatter, more readable bars.")
    gex_scale = st.radio("Scale", ["USD (million)", "BTC"], index=0)
    show_crypto_gex = st.checkbox("Show crypto-adjusted GEX", value=True)
    show_zero_gamma = st.checkbox("Show zero-gamma line", value=True)

df_f = df[df["tte_days"] <= tte_max].copy()
scale_div = 1e6 if gex_scale == "USD (million)" else 1.0
scale_lbl = "USD M" if gex_scale == "USD (million)" else "USD"

# ── compute ──────────────────────────────────────────────────────────
gex_strike = compute_gex_by_strike(df_f)
gex_ts     = compute_gex_timeseries(df_f)
gex_exp    = compute_gex_by_expiry(df_f)
max_pain   = compute_max_pain(df_f)
charm      = compute_charm_pressure(df_f)
vanna      = compute_vanna_exposure(df_f)
levels     = find_key_levels(gex_strike, max_pain)

spot = levels["spot"]
strike_lo = spot * (1 - strike_range_pct / 100)
strike_hi = spot * (1 + strike_range_pct / 100)

# ── KEY METRICS ──────────────────────────────────────────────────────
st.subheader("Regime & key levels")

regime_icon = {"Confirmed Long Gamma": "🟢", "Confirmed Short Gamma": "🔴"}.get(levels["regime"], "🟡")

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Spot", f"${spot:,.0f}")
c2.metric("Regime", f"{regime_icon} {levels['regime'].replace('Confirmed ','')}")
c3.metric("Net GEX (equity)", f"{levels['net_gex_equity']/scale_div:+.1f} {scale_lbl}")
c4.metric("Zero Gamma", f"${levels['zero_gamma_strike']:,.0f}" if levels["zero_gamma_strike"] else "—",
          help="Cumulative GEX sign flip — crossing this changes the vol regime.")
c5.metric("Max Pain", f"${levels['max_pain']:,.0f}" if levels["max_pain"] else "—",
          help="Strike where option buyers collectively lose the most at expiry.")
c6.metric("Put Wall", f"${levels['put_wall']:,.0f}" if levels["put_wall"] else "—",
          help="Largest put GEX below spot — implied mechanical support.")

if levels["call_wall"]:
    st.info(f"**Call Wall (resistance):** ${levels['call_wall']:,.0f} — "
            f"largest call gamma concentration above spot. "
            f"{'Above zero-gamma → vol suppression.' if levels['zero_gamma_strike'] and levels['call_wall'] > levels['zero_gamma_strike'] else 'Dealers short gamma here → potential gap zone.'}")

if levels["max_pain"] and abs(spot - levels["max_pain"]) / spot < 0.03:
    st.warning(f"**Max Pain pin risk:** Spot is within 3% of max pain ${levels['max_pain']:,.0f}. "
               f"Expect increased pinning pressure near expiry.")

st.divider()

# ══════════════════════════════════════════════════════════════════
# CHART 1 — GEX profile by strike (net + crypto overlay)
# ══════════════════════════════════════════════════════════════════
st.subheader("GEX profile by strike")
st.caption(
    "Green bars = dealers net long gamma (stabilising). "
    "Red bars = dealers net short gamma (vol amplifying). "
    "Orange line = crypto-adjusted net GEX (assumes dealers also short call gamma). "
    "The gap between bars and orange line is the uncertainty band."
)

gp = gex_strike[gex_strike["strike"].between(strike_lo, strike_hi)].copy()
gp["net_eq_s"] = gp["gex_net_eq"] / scale_div
gp["net_cr_s"] = gp["gex_net_cr"] / scale_div

fig1 = go.Figure()

# Equity bars (color by sign)
pos = gp[gp["net_eq_s"] >= 0]
neg = gp[gp["net_eq_s"] < 0]

if not pos.empty:
    fig1.add_trace(go.Bar(
        x=pos["strike"], y=pos["net_eq_s"],
        name="Long gamma (equity)", marker_color=GREEN, opacity=0.85,
    ))
if not neg.empty:
    fig1.add_trace(go.Bar(
        x=neg["strike"], y=neg["net_eq_s"],
        name="Short gamma (equity)", marker_color=RED, opacity=0.85,
    ))

# Crypto-adjusted overlay
if show_crypto_gex:
    fig1.add_trace(go.Scatter(
        x=gp["strike"], y=gp["net_cr_s"],
        mode="lines+markers",
        line=dict(color=ORANGE, width=2, dash="dot"),
        marker=dict(size=5),
        name="Crypto-adjusted GEX",
    ))

# Vertical reference lines
fig1.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
               annotation_text=f"Spot ${spot:,.0f}", annotation_position="top right")

if show_zero_gamma and levels["zero_gamma_strike"]:
    fig1.add_vline(x=levels["zero_gamma_strike"], line_dash="dot", line_color=ORANGE,
                   line_width=1.5,
                   annotation_text=f"Zero γ ${levels['zero_gamma_strike']:,.0f}",
                   annotation_position="bottom right")

if levels["max_pain"]:
    fig1.add_vline(x=levels["max_pain"], line_dash="longdash", line_color=PURPLE,
                   line_width=1.5,
                   annotation_text=f"Max Pain ${levels['max_pain']:,.0f}",
                   annotation_position="top left")

if levels["put_wall"] and strike_lo <= levels["put_wall"] <= strike_hi:
    fig1.add_vline(x=levels["put_wall"], line_dash="dot", line_color=GREEN, line_width=1,
                   annotation_text="Put Wall", annotation_position="bottom left")

if levels["call_wall"] and strike_lo <= levels["call_wall"] <= strike_hi:
    fig1.add_vline(x=levels["call_wall"], line_dash="dot", line_color=BLUE, line_width=1,
                   annotation_text="Call Wall", annotation_position="top left")

fig1.update_layout(
    barmode="relative", bargap=0, bargroupgap=0,
    xaxis_title="Strike", yaxis_title=f"Net GEX ({scale_lbl})",
    legend_title="Convention", height=580,
    plot_bgcolor=BG, paper_bgcolor=BG,
)
st.plotly_chart(fig1, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 1b — Dealer vs Speculator GEX split
# ══════════════════════════════════════════════════════════════════
st.subheader("Dealer vs Speculator GEX — participant proxy")
st.caption(
    "Deribit does not tag participants. Proxy: **vol/OI ratio** per instrument. "
    "Low turnover (vol/OI ≤ median) → structural / dealer-like hedging book. "
    "High turnover (vol/OI > median) → active speculation / retail-like flow. "
    "Divergence between groups at a strike = contested level."
)

gex_split = compute_gex_by_strike_split(df_f)
gex_split_f = gex_split[gex_split["strike"].between(strike_lo, strike_hi)].copy()
gex_split_f["net_s"] = gex_split_f["gex_net_eq"] / scale_div

TEAL   = "#26c6da"
YELLOW = "#ffee58"

fig1b = go.Figure()
for participant, color in [("Structural / Dealer-like", TEAL), ("Speculative / Retail-like", YELLOW)]:
    grp = gex_split_f[gex_split_f["participant"] == participant]
    if grp.empty:
        continue
    fig1b.add_trace(go.Bar(
        x=grp["strike"], y=grp["net_s"],
        name=participant, marker_color=color, opacity=0.75,
    ))

fig1b.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
                annotation_text=f"Spot ${spot:,.0f}", annotation_position="top right")
if show_zero_gamma and levels["zero_gamma_strike"]:
    fig1b.add_vline(x=levels["zero_gamma_strike"], line_dash="dot", line_color=ORANGE,
                    line_width=1.5,
                    annotation_text=f"Zero γ ${levels['zero_gamma_strike']:,.0f}",
                    annotation_position="bottom right")
fig1b.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig1b.update_layout(
    barmode="group", bargap=0.1,
    xaxis_title="Strike", yaxis_title=f"Net GEX ({scale_lbl})",
    height=480, plot_bgcolor=BG, paper_bgcolor=BG,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig1b, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 1c — GEX Evolution (now / -1H / -4H)
# ══════════════════════════════════════════════════════════════════
st.subheader("GEX profile evolution — now vs -1H vs -4H")
st.caption(
    "Overlay of GEX profiles at different points in time. "
    "Shifts in gamma walls reveal where hedging demand is building or collapsing. "
    "Only hours present in the loaded dataset are shown."
)

available_hours = sorted(df_f["hour"].unique())
latest_hour = available_hours[-1] if available_hours else None

evo_snapshots = {}  # label → DataFrame
if latest_hour is not None:
    evo_snapshots[f"Now ({latest_hour.strftime('%H:%M')})"] = compute_gex_at_hour(df_f, latest_hour)

    for label, delta_h in [("-1H", 1), ("-4H", 4)]:
        target = latest_hour - pd.Timedelta(hours=delta_h)
        # find closest available hour ≤ target
        candidates = [h for h in available_hours if h <= target]
        if candidates:
            h = max(candidates)
            evo_snapshots[f"{label} ({h.strftime('%H:%M')})"] = compute_gex_at_hour(df_f, h)

EVO_COLORS = {0: "white", 1: "#42a5f5", 2: "#ab47bc"}
EVO_DASH   = {0: "solid", 1: "dash", 2: "dot"}

fig1c = go.Figure()
for idx, (lbl, evo_df) in enumerate(evo_snapshots.items()):
    if evo_df.empty:
        continue
    evo_f = evo_df[evo_df["strike"].between(strike_lo, strike_hi)].copy()
    evo_f["net_s"] = evo_f["gex_net_eq"] / scale_div
    opacity = 1.0 - idx * 0.25
    fig1c.add_trace(go.Scatter(
        x=evo_f["strike"], y=evo_f["net_s"],
        mode="lines",
        line=dict(color=EVO_COLORS[idx], width=2 - idx * 0.4, dash=EVO_DASH[idx]),
        opacity=max(opacity, 0.45),
        name=lbl,
        fill="tozeroy" if idx == 0 else None,
        fillcolor="rgba(255,255,255,0.05)" if idx == 0 else None,
    ))

if latest_hour is not None:
    fig1c.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
                    annotation_text=f"Spot ${spot:,.0f}", annotation_position="top right")
fig1c.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig1c.update_layout(
    xaxis_title="Strike", yaxis_title=f"Net GEX equity ({scale_lbl})",
    height=400, plot_bgcolor=BG, paper_bgcolor=BG,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig1c, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 2 — Absolute gamma walls (sign-agnostic)
# ══════════════════════════════════════════════════════════════════
st.subheader("Absolute gamma concentration (liquidity walls)")
st.caption(
    "Shows WHERE dealers MUST hedge regardless of direction. "
    "High bars = large mechanical flow when price approaches. "
    "Price stalls or gaps at these strikes — not necessarily mean-reverting."
)

gp_abs = gex_strike[gex_strike["strike"].between(strike_lo, strike_hi)].copy()
gp_abs["gex_abs_s"] = gp_abs["gex_abs"] / scale_div
gp_abs["gex_call_s"] = gp_abs["gex_raw_c"] / scale_div
gp_abs["gex_put_s"]  = gp_abs["gex_raw_p"] / scale_div

fig2 = go.Figure()
fig2.add_trace(go.Bar(
    x=gp_abs["strike"], y=gp_abs["gex_call_s"],
    name="Call gamma", marker_color=BLUE, opacity=0.75,
))
fig2.add_trace(go.Bar(
    x=gp_abs["strike"], y=gp_abs["gex_put_s"],
    name="Put gamma", marker_color=PURPLE, opacity=0.75,
))
fig2.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
               annotation_text=f"Spot ${spot:,.0f}", annotation_position="top right")

top3 = sorted(levels["gamma_wall_top3"], key=lambda x: -x[1])
for s, g in top3:
    if strike_lo <= s <= strike_hi:
        fig2.add_vline(x=s, line_dash="dot", line_color=ORANGE, line_width=1,
                       annotation_text=f"Wall ${s:,.0f}", annotation_position="top left")

fig2.update_layout(
    barmode="stack", bargap=0,
    xaxis_title="Strike", yaxis_title=f"Gross GEX ({scale_lbl})",
    height=420, plot_bgcolor=BG, paper_bgcolor=BG,
)
st.plotly_chart(fig2, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 3 — GEX timeseries + regime + velocity
# ══════════════════════════════════════════════════════════════════
st.subheader("Net GEX over time — regime & velocity")
st.caption(
    "Solid = equity GEX, dashed = crypto GEX. "
    "When both are negative → confirmed short-gamma regime (explosive vol). "
    "**Velocity** (bottom) = rate of GEX change. Velocity turning negative = early regime flip warning."
)

ts = gex_ts.copy()
ts["eq_s"]  = ts["net_gex_equity"] / scale_div
ts["cr_s"]  = ts["net_gex_crypto"]  / scale_div
ts["vel_s"] = ts["gex_velocity"]    / scale_div

col_l, col_r = st.columns([3, 1])

with col_l:
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=ts["hour"], y=ts["eq_s"],
        fill="tozeroy",
        line=dict(color=GREEN, width=2),
        fillcolor=f"rgba(38,166,154,0.2)",
        name="Net GEX (equity)",
    ))
    if show_crypto_gex:
        fig3.add_trace(go.Scatter(
            x=ts["hour"], y=ts["cr_s"],
            line=dict(color=ORANGE, width=1.5, dash="dash"),
            name="Net GEX (crypto)",
        ))
    fig3.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
    fig3.update_layout(
        xaxis_title="Time", yaxis_title=f"Net GEX ({scale_lbl})",
        height=280, plot_bgcolor=BG, paper_bgcolor=BG,
    )
    st.plotly_chart(fig3, width="stretch")

    # Velocity sub-chart
    fig3v = go.Figure()
    vel_colors = [GREEN if v >= 0 else RED for v in ts["vel_s"].fillna(0)]
    fig3v.add_trace(go.Bar(
        x=ts["hour"], y=ts["vel_s"],
        marker_color=vel_colors,
        name="GEX velocity",
    ))
    fig3v.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
    fig3v.update_layout(
        xaxis_title="Time", yaxis_title=f"ΔGEX/period ({scale_lbl})",
        height=180, plot_bgcolor=BG, paper_bgcolor=BG,
        showlegend=False,
    )
    st.plotly_chart(fig3v, width="stretch")

with col_r:
    # Regime history table
    st.markdown("**Regime per period**")
    regime_map = {"Confirmed Long Gamma": "🟢", "Confirmed Short Gamma": "🔴", "Mixed / Uncertain": "🟡"}
    for _, row in ts.tail(8).iloc[::-1].iterrows():
        icon = regime_map.get(row["regime"], "🟡")
        st.markdown(f"`{row['hour'].strftime('%H:%M')}` {icon} {row['regime'].replace('Confirmed ','')}")

# ══════════════════════════════════════════════════════════════════
# CHART 4 — Charm pressure (≤7 DTE — mechanical delta flow)
# ══════════════════════════════════════════════════════════════════
st.subheader("Charm pressure — near-expiry delta decay (≤7 DTE)")
st.caption(
    "Charm = how much dealer delta changes each day from time decay alone. "
    "No price move needed — this is **mechanical, predictable flow**. "
    "Positive = dealers accumulate delta (buy pressure). Negative = dealers shed delta (sell pressure)."
)

if charm.empty:
    st.info("No options ≤7 DTE in current data. Charm pressure is zero.")
else:
    charm_plot = charm.copy()
    charm_plot["cp_s"] = charm_plot["charm_pressure_usd"] / scale_div
    charm_colors = [GREEN if v >= 0 else RED for v in charm_plot["cp_s"]]

    fig4 = go.Figure()
    fig4.add_trace(go.Bar(
        x=charm_plot["strike"].astype(str) + "-" + charm_plot["type"],
        y=charm_plot["cp_s"],
        marker_color=charm_colors,
        name="Charm pressure",
    ))
    fig4.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
    fig4.update_layout(
        xaxis_title="Strike-Type", yaxis_title=f"Charm exposure ({scale_lbl}/day)",
        height=320, plot_bgcolor=BG, paper_bgcolor=BG,
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig4, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 5 — Vanna exposure (vol-driven delta hedging)
# ══════════════════════════════════════════════════════════════════
st.subheader("Vanna exposure — IV-driven delta flow")
st.caption(
    "Vanna = how much dealer delta changes per 1 vol point IV move. "
    "**Crypto IV moves ±10-20 vol pts intraday.** "
    "Positive vanna + falling IV → dealers sell delta (adds selling pressure). "
    "Negative vanna + falling IV → dealers buy delta (adds buying pressure). "
    "Vanna exposure near spot is the most impactful."
)

vanna_plot = vanna[vanna["strike"].between(strike_lo, strike_hi)].copy()
if not vanna_plot.empty:
    vanna_plot["ve_s"] = vanna_plot["vanna_exp_1vp"] / scale_div
    vanna_totals = vanna_plot.groupby("strike")["ve_s"].sum().reset_index()

    v_colors = [GREEN if v >= 0 else RED for v in vanna_totals["ve_s"]]
    fig5 = go.Figure()
    fig5.add_trace(go.Bar(
        x=vanna_totals["strike"], y=vanna_totals["ve_s"],
        marker_color=v_colors, opacity=0.85,
        name="Net vanna exp",
    ))
    fig5.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
                   annotation_text=f"Spot", annotation_position="top right")
    fig5.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
    fig5.update_layout(
        barmode="relative", bargap=0,
        xaxis_title="Strike", yaxis_title=f"Δ delta per 1 vol pt ({scale_lbl})",
        height=360, plot_bgcolor=BG, paper_bgcolor=BG,
    )
    st.plotly_chart(fig5, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 6 — Max pain curve
# ══════════════════════════════════════════════════════════════════
st.subheader("Max pain curve")
st.caption(
    "Total buyer P&L at each expiry price. "
    "Minimum = max pain strike — where MMs are most profitable. "
    "Strong pin force when spot is within 3% of max pain and DTE < 5."
)

mp_plot = max_pain[max_pain["strike"].between(strike_lo, strike_hi)].copy()
mp_plot["pnl_s"] = mp_plot["total_buyer_pnl"] / 1e6

fig6 = go.Figure()
fig6.add_trace(go.Scatter(
    x=mp_plot["strike"], y=mp_plot["pnl_s"],
    mode="lines+markers",
    line=dict(color=BLUE, width=2),
    marker=dict(size=5),
    name="Total buyer P&L",
))
if levels["max_pain"] and mp_plot["strike"].between(strike_lo, strike_hi).any():
    fig6.add_vline(x=levels["max_pain"], line_dash="dot", line_color=PURPLE, line_width=2,
                   annotation_text=f"Max Pain ${levels['max_pain']:,.0f}",
                   annotation_position="top right")
fig6.add_vline(x=spot, line_dash="dash", line_color="white", line_width=2,
               annotation_text=f"Spot ${spot:,.0f}", annotation_position="top left")

fig6.update_layout(
    xaxis_title="Strike (expiry price)", yaxis_title="Total buyer P&L ($M)",
    height=320, plot_bgcolor=BG, paper_bgcolor=BG,
)
st.plotly_chart(fig6, width="stretch")

# ══════════════════════════════════════════════════════════════════
# CHART 7 — GEX by expiry
# ══════════════════════════════════════════════════════════════════
st.subheader("GEX by maturity — where is gamma concentrated?")
st.caption("Front-month negative GEX = immediate vol risk. Back-month = structural overhang.")

exp_plot = gex_exp.copy()
exp_plot["net_s"] = exp_plot["net_gex_eq"] / scale_div
e_colors = [GREEN if v >= 0 else RED for v in exp_plot["net_s"]]

fig7 = go.Figure(go.Bar(
    x=exp_plot["tte_bucket"].astype(str), y=exp_plot["net_s"],
    marker_color=e_colors, opacity=0.85,
))
fig7.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig7.update_layout(
    xaxis_title="DTE bucket", yaxis_title=f"Net GEX ({scale_lbl})",
    height=300, plot_bgcolor=BG, paper_bgcolor=BG,
)
st.plotly_chart(fig7, width="stretch")

# ══════════════════════════════════════════════════════════════════
# METHODOLOGY NOTES
# ══════════════════════════════════════════════════════════════════
with st.expander("Crypto GEX methodology & limitations", expanded=False):
    st.markdown(f"""
**Why two GEX conventions?**

| Convention | Calls | Puts | When accurate |
|---|---|---|---|
| Equity (standard) | +GEX | -GEX | Low crypto call speculation |
| Crypto-adjusted | -GEX | -GEX | High retail call buying |

The truth depends on **who is net long** at each strike. Without taker-flow data (Glassnode proprietary),
we show both and treat the gap as uncertainty.

**Actionable levels — reliability ranking:**
1. **Absolute GEX walls** (chart 2) — most reliable, sign-agnostic mechanical hedging
2. **Max Pain** — institutional pin incentive, strongest ≤5 DTE
3. **Zero Gamma** — regime pivot, most powerful when confirmed by both conventions
4. **Put Wall** — genuine support if from hedged spot longs
5. **Call Wall** — resistance if calls are speculative (dealers short gamma here)

**Vanna in crypto:**
A 10 vol pt IV drop with net positive vanna of {vanna_plot['ve_s'].sum():.1f} {scale_lbl}
→ implies **~{vanna_plot['ve_s'].sum() * 10:.0f} {scale_lbl} of mechanical dealer selling** with no price move.

**Charm cascade:**
Near-expiry options (≤7 DTE) with delta ≠ 0 or 1 create predictable delta drift.
Use charm map to anticipate mechanical flows in the 24-48h before expiry.
    """)
