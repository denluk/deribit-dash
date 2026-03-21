"""GEX — Gamma Exposure dashboard page."""
from __future__ import annotations

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
    find_key_levels,
)

st.title("Gamma Exposure (GEX)")
st.caption(
    "Structural GEX — dealer-gamma framework. "
    "**Positive GEX** near spot → dealers long gamma → vol suppression / mean-reverting. "
    "**Negative GEX** near spot → dealers short gamma → vol amplification / trending."
)

path = resolve_input_path("gex")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))

# ── sidebar controls ────────────────────────────────────────────────
with st.sidebar:
    st.subheader("GEX settings")
    tte_max = st.slider(
        "Max DTE (days)", min_value=1, max_value=365, value=90,
        help="Exclude options expiring beyond this many days (reduces noise from LEAPS)."
    )
    gex_scale = st.radio("GEX scale", ["USD (million)", "BTC"], index=0)
    show_zero_gamma = st.checkbox("Show zero-gamma line", value=True)

# ── filter by DTE ───────────────────────────────────────────────────
df_filtered = df[df["tte_days"] <= tte_max].copy()

# ── compute ──────────────────────────────────────────────────────────
gex_strike  = compute_gex_by_strike(df_filtered)
gex_ts      = compute_gex_timeseries(df_filtered)
gex_expiry  = compute_gex_by_expiry(df_filtered)
levels      = find_key_levels(gex_strike)

scale_div  = 1e6 if gex_scale == "USD (million)" else levels["spot"]
scale_label = "USD M" if gex_scale == "USD (million)" else "BTC"

# ── key metrics row ──────────────────────────────────────────────────
st.subheader("Key levels")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Spot", f"${levels['spot']:,.0f}")
regime_color = "🟢" if levels["gex_regime"] == "Long Gamma" else "🔴"
c2.metric("GEX Regime", f"{regime_color} {levels['gex_regime']}")
c3.metric(
    "Net GEX",
    f"{levels['net_gex_total']/scale_div:+.2f} {scale_label}",
)
c4.metric(
    "Zero Gamma",
    f"${levels['zero_gamma_strike']:,.0f}" if levels["zero_gamma_strike"] else "N/A",
    help="Strike where cumulative GEX changes sign. Key pivot level for the underlying."
)
c5.metric(
    "Gamma Wall",
    f"${levels['max_pos_gamma_strike']:,.0f}" if levels["max_pos_gamma_strike"] else "N/A",
    help="Strike with highest positive GEX — acts as magnet/resistance when approached from below."
)

st.divider()

# ── 1. GEX by strike profile ─────────────────────────────────────────
st.subheader("GEX profile by strike")
st.caption(
    "Each bar = net dealer gamma at that strike (call GEX − put GEX). "
    "Green bars = dealers long gamma (stabilising). Red bars = dealers short gamma (destabilising). "
    "Dashed lines: spot (white), zero-gamma level (orange), gamma wall (blue)."
)

gex_plot = gex_strike.copy()
gex_plot["gex_net_scaled"] = gex_plot["gex_net"] / scale_div
gex_plot["color"] = gex_plot["gex_net_scaled"].apply(lambda x: "positive" if x >= 0 else "negative")

fig1 = go.Figure()

# bars
for color, grp in gex_plot.groupby("color"):
    fig1.add_trace(go.Bar(
        x=grp["strike"],
        y=grp["gex_net_scaled"],
        name="Long dealer gamma" if color == "positive" else "Short dealer gamma",
        marker_color="#26a69a" if color == "positive" else "#ef5350",
        opacity=0.85,
    ))

# spot line
fig1.add_vline(
    x=levels["spot"], line_dash="dash", line_color="white", line_width=2,
    annotation_text=f"Spot ${levels['spot']:,.0f}", annotation_position="top right",
)

# zero gamma line
if show_zero_gamma and levels["zero_gamma_strike"]:
    fig1.add_vline(
        x=levels["zero_gamma_strike"], line_dash="dot", line_color="orange", line_width=1.5,
        annotation_text=f"Zero Gamma ${levels['zero_gamma_strike']:,.0f}",
        annotation_position="bottom right",
    )

# gamma wall
if levels["max_pos_gamma_strike"]:
    fig1.add_vline(
        x=levels["max_pos_gamma_strike"], line_dash="longdash", line_color="#42a5f5", line_width=1.5,
        annotation_text=f"Gamma Wall ${levels['max_pos_gamma_strike']:,.0f}",
        annotation_position="top left",
    )

fig1.update_layout(
    barmode="relative",
    xaxis_title="Strike",
    yaxis_title=f"Net GEX ({scale_label})",
    legend_title="Dealer position",
    height=480,
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
)
st.plotly_chart(fig1, width="stretch")

# ── 2. GEX timeseries ────────────────────────────────────────────────
st.subheader("Net GEX over time")
st.caption(
    "Sustained negative net GEX = short-gamma regime: dealers forced to buy as spot falls and sell as spot rises — amplifying moves. "
    "Transition from positive to negative GEX is a key vol regime signal."
)

ts_plot = gex_ts.copy()
ts_plot["net_gex_scaled"] = ts_plot["net_gex"] / scale_div

fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=ts_plot["hour"],
    y=ts_plot["net_gex_scaled"],
    mode="lines",
    fill="tozeroy",
    line=dict(width=1.5, color="white"),
    fillcolor="rgba(38,166,154,0.3)",
    name="Net GEX",
))
fig2.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig2.update_layout(
    xaxis_title="Time",
    yaxis_title=f"Net GEX ({scale_label})",
    height=320,
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
)
st.plotly_chart(fig2, width="stretch")

# ── 3. GEX by expiry ─────────────────────────────────────────────────
st.subheader("GEX distribution by maturity")
st.caption(
    "Shows which expiries carry the most gamma risk. "
    "Front-month negative GEX is more impactful on spot than back-month negative GEX."
)

exp_plot = gex_expiry.copy()
exp_plot["net_gex_scaled"] = exp_plot["net_gex"] / scale_div
exp_plot["color"] = exp_plot["net_gex_scaled"].apply(lambda x: "#26a69a" if x >= 0 else "#ef5350")

fig3 = px.bar(
    exp_plot,
    x="tte_bucket", y="net_gex_scaled",
    color="net_gex_scaled",
    color_continuous_scale=["#ef5350", "#26a69a"],
    color_continuous_midpoint=0,
    labels={"tte_bucket": "DTE bucket", "net_gex_scaled": f"Net GEX ({scale_label})"},
    height=320,
)
fig3.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig3.update_layout(
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
    coloraxis_showscale=False,
)
st.plotly_chart(fig3, width="stretch")

# ── 4. call vs put breakdown ─────────────────────────────────────────
st.subheader("Call GEX vs Put GEX by strike")
st.caption(
    "Stacked view: teal = call (dealers long), red = put (dealers short). "
    "Large red put GEX below spot = significant support/pin zone for dealers."
)

gex_stack = gex_strike.copy()
gex_stack["gex_call_scaled"] = gex_stack["gex_call"] / scale_div
gex_stack["gex_put_scaled"]  = gex_stack["gex_put"]  / scale_div

fig4 = go.Figure()
fig4.add_trace(go.Bar(
    x=gex_stack["strike"], y=gex_stack["gex_call_scaled"],
    name="Call GEX (dealers long)", marker_color="#26a69a", opacity=0.8,
))
fig4.add_trace(go.Bar(
    x=gex_stack["strike"], y=gex_stack["gex_put_scaled"],
    name="Put GEX (dealers short)", marker_color="#ef5350", opacity=0.8,
))
fig4.add_vline(
    x=levels["spot"], line_dash="dash", line_color="white", line_width=2,
    annotation_text=f"Spot ${levels['spot']:,.0f}", annotation_position="top right",
)
fig4.update_layout(
    barmode="relative",
    xaxis_title="Strike",
    yaxis_title=f"GEX ({scale_label})",
    height=380,
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
)
st.plotly_chart(fig4, width="stretch")

# ── 5. interpretation box ────────────────────────────────────────────
with st.expander("How to read GEX", expanded=False):
    st.markdown("""
**Dealer gamma hedging mechanics:**

Dealers (market makers) continuously delta-hedge their options book.
When dealers are **long gamma** at a strike, their hedge requires them to:
- Sell the underlying as price *rises*
- Buy the underlying as price *falls*
→ This creates a self-correcting force — spot gets "pinned" near high-GEX strikes.

When dealers are **short gamma** at a strike:
- Buy as price rises, sell as price falls
→ This amplifies moves — gap risk increases, vol tends to expand.

**Key levels explained:**
| Level | Meaning |
|---|---|
| **Zero Gamma** | Strike where cumulative GEX transitions from negative to positive. Acts as a pivot — crossing it changes the vol regime. |
| **Gamma Wall** | Highest positive GEX strike. Strong gravitational pull on price, especially in low-vol environments. |
| **Put Wall** | Largest negative GEX from puts. Dealers must buy aggressively here → implied support. |

**Crypto-specific caveat:**
In crypto, participants buy calls speculatively (not just for protection), which can shift dealer gamma to short on the call side too.
Treat this as a *structural baseline* — for flow-adjusted GEX you need taker-flow data (Glassnode proprietary).
    """)
