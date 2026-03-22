"""Deribit Quant Analyst — on-demand full options intelligence run."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from deribit_intel.branding import show_logo

# ── constants (match GEX page palette) ────────────────────────────────────
BG         = "#0e1117"
GREEN      = "#26a69a"
RED        = "#ef5350"
ORANGE     = "#ffa726"
BLUE       = "#42a5f5"
PURPLE     = "#ab47bc"
YELLOW     = "#ffee58"
FONT_COLOR = "#90caf9"
GRID_COLOR = "#1e2530"
CARD_BG    = "#161b22"

ROOT    = Path(__file__).parent.parent.parent.parent  # deribit-dash/
VENV_PY = ROOT / "venv" / "bin" / "python"
AGENT   = ROOT / "analyst_agent.py"
LOGS    = ROOT / "logs"

PYTHON = str(VENV_PY) if VENV_PY.exists() else sys.executable


# ── helpers ────────────────────────────────────────────────────────────────

def _style(fig: go.Figure) -> go.Figure:
    ax = dict(
        title_font=dict(color=FONT_COLOR, size=12),
        tickfont=dict(color=FONT_COLOR, size=11),
        tickcolor=FONT_COLOR,
        gridcolor=GRID_COLOR,
        linecolor="#2a3040",
        zerolinecolor="#2a3040",
    )
    fig.update_xaxes(**ax)
    fig.update_yaxes(**ax)
    fig.update_layout(
        font=dict(color=FONT_COLOR, size=12),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        legend=dict(
            font=dict(color=FONT_COLOR),
            bgcolor="rgba(14,17,23,0.6)",
            bordercolor="#2a3040",
            borderwidth=1,
        ),
    )
    return fig


def _run(subcmd: list[str]) -> dict:
    """Run analyst_agent.py subcommand, return parsed JSON output."""
    result = subprocess.run(
        [PYTHON, str(AGENT)] + subcmd,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip() or "Unknown error"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"Bad output: {result.stdout[:300]}"}


def _f(val, fmt: str = ".1f", suffix: str = "", prefix: str = "", fallback: str = "—") -> str:
    """None-safe formatter for state vector values."""
    if val is None:
        return fallback
    try:
        return f"{prefix}{val:{fmt}}{suffix}"
    except (ValueError, TypeError):
        return str(val) or fallback


def _color_direction(direction: str) -> str:
    d = (direction or "").lower()
    if "bear" in d or "sell" in d or "negative" in d:
        return RED
    if "bull" in d or "buy" in d or "positive" in d:
        return GREEN
    return ORANGE


def _metric_row(cols_data: list[tuple]) -> None:
    """cols_data = list of (label, value, delta=None)."""
    cols = st.columns(len(cols_data))
    for col, (label, value, *rest) in zip(cols, cols_data):
        delta = rest[0] if rest else None
        col.metric(label, value, delta)


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#000;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:600">{text}</span>'
    )


def _clean_for_display(text: str) -> str:
    """Prepare Claude output for Streamlit markdown display.

    Strips:
    - Phase 10 LOG OUTPUT block (kept only for JSON extraction)
    - Markdown tables (Signal Scoring Matrix in Phase 3 — internal only)
    - Raw JSON log blocks

    Fixes:
    - Escapes $<digit> so markdown does not parse dollar amounts as LaTeX
    """
    import re
    # Remove Phase 10 section entirely
    cleaned = re.sub(r'(?s)\n?##\s*PHASE\s*10[^\n]*\n.*', '', text)
    # Remove raw JSON blocks with log payload
    cleaned = re.sub(r'(?s)```json\s*\{.*?"log_version".*?```', '', cleaned)
    # Remove markdown table rows (Signal Scoring Matrix — internal use only)
    cleaned = re.sub(r'(?m)^\|.*\|[ \t]*$\n?', '', cleaned)
    # Remove conviction arithmetic block (Σ calculations — internal only)
    cleaned = re.sub(r'(?s)Σ\(dir.*?conviction_final\s*=\s*\S+[^\n]*\n?', '', cleaned)
    # Remove Penalty checks block if it appears standalone
    cleaned = re.sub(r'(?s)Penalty checks:.*?(?=\n##|\n\*\*|\Z)', '', cleaned)
    # Escape $<digit> so Streamlit doesn't treat price strings as LaTeX math delimiters
    cleaned = re.sub(r'\$(\d)', r'\\$\1', cleaned)
    return cleaned.rstrip()


def _parse_range(raw) -> list | None:
    """Parse prediction range from various formats: list, '[x, y]' string, '$x – $y' string."""
    import re
    if isinstance(raw, list) and len(raw) == 2:
        try:
            return [float(raw[0]), float(raw[1])]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        nums = re.findall(r'\d[\d,]*(?:\.\d+)?', raw)
        cleaned = [float(n.replace(',', '')) for n in nums if n]
        if len(cleaned) >= 2:
            return [cleaned[0], cleaned[1]]
    return None


# ══════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════

show_logo()
st.title("Quant Analyst")
st.caption(
    "On-demand options intelligence: GEX regime, vol surface, mechanical flows, "
    "scenario tree and trade recommendation — all from in-house pipeline data."
)

# ── sidebar controls ───────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Analyst controls")
    run_pipeline = st.checkbox(
        "Refresh pipeline before analysis",
        value=False,
        help="Force re-run of orchestrate_batch + orchestrate_snapshot before extracting.",
    )
    show_raw = st.checkbox("Show raw state vector JSON", value=False)
    st.divider()
    run_btn = st.button("▶  Run Full Analysis", use_container_width=True, type="primary")
    grade_btn = st.button("⚖  Grade Yesterday", use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════
# GRADE YESTERDAY
# ══════════════════════════════════════════════════════════════════════════
if grade_btn:
    with st.spinner("Grading yesterday's prediction…"):
        grade_data = _run(["grade"])
    if "error" in grade_data:
        st.error(grade_data["error"])
    elif grade_data.get("grade_needed") is False:
        st.success(f"Already graded — score: {grade_data.get('score')}/5")
    elif grade_data.get("grade_skipped"):
        st.warning(grade_data.get("error", "No log found for yesterday."))
    else:
        st.subheader("Grade instructions")
        st.caption(
            "Fetch the actual 24h BTC close for "
            f"**{grade_data.get('date')}** via StackIQ, "
            "then score the criteria below and update the log."
        )
        st.json(grade_data)

# ══════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
# Session state: keep page alive after button press; track if new analysis needed
if run_btn:
    st.session_state["page_active"] = True
    st.session_state["needs_analysis"] = True
    st.session_state.pop("analysis_text", None)   # clear cache → re-run
    st.session_state.pop("analysis_log", None)

if not st.session_state.get("page_active"):
    st.info("Press **▶ Run Full Analysis** in the sidebar to start.")
    st.stop()

# ── Phase 0: data audit ───────────────────────────────────────────────────
st.divider()
st.subheader("Phase 1 — Data Audit")
with st.spinner("Auditing data sources…"):
    audit = _run(["audit"])

if "error" in audit:
    st.error(f"Audit failed: {audit['error']}")
    st.stop()

# Audit metrics
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("S3 available",    "✓" if audit.get("s3_available") else "✗")
col2.metric("Latest hour",     str(audit.get("batch_latest_hour", "—"))[:16])
col3.metric("Freshness",       f"{audit.get('freshness_minutes', '?')} min")
col4.metric("Instruments",     audit.get("instruments", "—"))
col5.metric("Surface rel.",    f"{audit.get('surface_reliability_avg') or '—'}")

# S3 partitions
if audit.get("s3_partitions"):
    st.caption(f"S3 partitions available: `{'`, `'.join(audit['s3_partitions'][-5:])}`")

rel_avg = audit.get("surface_reliability_avg") or 0
if rel_avg and rel_avg < 0.65:
    st.warning(
        f"⚠️ LOW SURFACE CONFIDENCE ({rel_avg:.2f}) — signals degraded. "
        "Position sizing reduced to 0.5×. 68% CI widened by 25%.",
        icon="⚠️",
    )

# Pipeline run if needed or requested
pipeline_needed = audit.get("pipeline_needed") or run_pipeline
s3_latest = ROOT / "artifacts" / "s3_latest.parquet"

if pipeline_needed:
    st.info("Pipeline artifacts stale or missing — starting data ingestion…")

    # Step 1 — pull from S3 if available and local file missing/stale
    if audit.get("s3_available") and audit.get("s3_bucket"):
        bucket      = audit["s3_bucket"]
        prefix      = audit.get("s3_prefix") or ""
        latest_date = audit.get("s3_latest_date") or ""
        start_date  = audit.get("s3_partitions", [latest_date])[
            max(0, len(audit.get("s3_partitions", [latest_date])) - 3)
        ] if audit.get("s3_partitions") else latest_date

        with st.spinner(f"Pulling S3 data ({start_date} → {latest_date})…"):
            s3_cmd = [
                PYTHON, str(ROOT / "run_s3_pipeline.py"),
                "--bucket", bucket,
                "--out", str(s3_latest),
            ]
            if prefix:
                s3_cmd += ["--prefix", prefix]
            if start_date:
                s3_cmd += ["--start-date", start_date]
            if latest_date:
                s3_cmd += ["--end-date", latest_date]
            ps3 = subprocess.run(s3_cmd, capture_output=True, text=True, cwd=str(ROOT))

        if ps3.returncode != 0:
            st.error(f"S3 pull failed:\n{ps3.stderr[:500]}")
            st.stop()
        try:
            s3_result = json.loads(ps3.stdout)
            st.success(f"S3 pull complete — {s3_result.get('rows', '?')} rows, {s3_result.get('keys', '?')} files.")
        except Exception:
            st.success("S3 pull complete.")

    # Abort early if still no input file
    if not s3_latest.exists():
        st.error(
            "No input data found. Either connect S3 or place a parquet file at "
            f"`{s3_latest}`."
        )
        st.stop()

    # Step 2 — batch pipeline
    with st.spinner("Running batch pipeline (GEX, vol, RV, signals)…"):
        p1 = subprocess.run(
            [PYTHON, str(ROOT / "orchestrate_batch.py"),
             "--input-path", str(s3_latest),
             "--out-dir", str(ROOT / "artifacts" / "batch")],
            capture_output=True, text=True, cwd=str(ROOT),
        )
    if p1.returncode != 0:
        st.error(f"Batch pipeline failed:\n{p1.stderr[:600]}")
        st.stop()

    # Step 3 — snapshot pipeline
    with st.spinner("Running snapshot pipeline (surface fit, signals, repricing)…"):
        p2 = subprocess.run(
            [PYTHON, str(ROOT / "orchestrate_snapshot.py"),
             "--input-path", str(s3_latest),
             "--batch-dir", str(ROOT / "artifacts" / "batch"),
             "--out-dir", str(ROOT / "artifacts" / "snapshot")],
            capture_output=True, text=True, cwd=str(ROOT),
        )
    if p2.returncode != 0:
        st.error(f"Snapshot pipeline failed:\n{p2.stderr[:600]}")
        st.stop()

    st.success("Pipeline complete — artifacts ready.")

# ── Phase 1: extract state vector ─────────────────────────────────────────
st.divider()
st.subheader("Phase 2 — Quantitative State Vector")
with st.spinner("Extracting state vector from parquets…"):
    sv = _run(["extract"])

if "error" in sv:
    st.error(f"Extraction failed: {sv['error']}")
    st.stop()

if show_raw:
    with st.expander("Raw state vector JSON"):
        st.json(sv)

spot = sv.get("spot", 0)

# ── Top-line regime badges ─────────────────────────────────────────────────
gex_regime  = sv.get("gex_regime", "Unknown")
vol_regime  = sv.get("vol_regime_label", "Unknown")
skew_dir    = sv.get("skew_direction", "balanced")
term_shape  = sv.get("term_structure_shape", "unknown")

reg_color = RED if "Short" in gex_regime else (GREEN if "Long" in gex_regime else ORANGE)
sk_color  = RED if "put" in skew_dir else (ORANGE if "call" in skew_dir else GREEN)
ts_color  = RED if "backwardated" in term_shape else (GREEN if "contango" in term_shape else ORANGE)

st.markdown(
    f"**Regime:** &nbsp;"
    f"{_badge(gex_regime, reg_color)} &nbsp;"
    f"{_badge(vol_regime, BLUE)} &nbsp;"
    f"{_badge(skew_dir, sk_color)} &nbsp;"
    f"{_badge(term_shape, ts_color)}",
    unsafe_allow_html=True,
)
st.markdown("<br>", unsafe_allow_html=True)

# ── GEX metrics ────────────────────────────────────────────────────────────
st.markdown("#### GEX")
_metric_row([
    ("Spot",             f"${spot:,.0f}"),
    ("Net GEX (equity)", _f(sv.get("gex_net_equity_usd_m"), fmt="+.1f", suffix="M")),
    ("Net GEX (crypto)", _f(sv.get("gex_net_crypto_usd_m"), fmt="+.1f", suffix="M")),
    ("GEX velocity 1H",  _f(sv.get("gex_velocity_1h"),      fmt="+.1f", suffix="M")),
    ("Velocity trend",   sv.get("gex_velocity_trend") or "—"),
])
_metric_row([
    ("Zero Gamma",       _f(sv.get("zero_gamma_strike"),       fmt=",.0f", prefix="$")),
    ("ZG distance",      _f(sv.get("zero_gamma_distance_pct"), fmt="+.2f", suffix="%")),
    ("Put Wall",         _f(sv.get("put_wall_strike"),         fmt=",.0f", prefix="$")),
    ("Put Wall str.",    _f(sv.get("put_wall_strength_usd_m"), fmt=".1f",  suffix="M")),
    ("Call Wall",        _f(sv.get("call_wall_strike"),        fmt=",.0f", prefix="$")),
])
_metric_row([
    ("Max Pain",         _f(sv.get("max_pain_strike"),             fmt=",.0f", prefix="$")),
    ("Max Pain DTE",     _f(sv.get("max_pain_dte"),               fmt=".0f",  suffix=" days")),
    ("Charm/day",        _f(sv.get("charm_net_usd_m_per_day"),    fmt="+.1f", suffix=f"M ({sv.get('charm_direction','—')})")),
    ("Vanna / vol pt",   _f(sv.get("vanna_net_usd_m_per_vol_pt"), fmt="+.1f", suffix="M")),
    ("Vanna IV +5vp",    _f(sv.get("vanna_flow_if_iv_up_5"),      fmt="+.1f", suffix="M")),
])

# ── Vol surface metrics ────────────────────────────────────────────────────
st.markdown("#### Volatility Surface")
_metric_row([
    ("ATM IV spot-week",    _f(sv.get("atm_iv_spot_week_pct"),   suffix="%")),
    ("ATM IV front-month",  _f(sv.get("atm_iv_front_month_pct"), suffix="%")),
    ("ATM IV back-month",   _f(sv.get("atm_iv_back_month_pct"),  suffix="%")),
    ("30d percentile",      _f(sv.get("atm_iv_30d_percentile"),  fmt=".0f", suffix="th")),
    ("IV/RV spread",        _f(sv.get("iv_rv_spread_pct"),       fmt="+.1f", suffix="vp")),
])
_metric_row([
    ("RV 24h",              _f(sv.get("rv_24h_pct"),                  suffix="%")),
    ("RV 72h",              _f(sv.get("rv_72h_pct"),                  suffix="%")),
    ("HAR RV forecast",     _f(sv.get("har_rv_forecast_24h_pct"),     suffix="%")),
    ("Regime RV forecast",  _f(sv.get("regime_rv_forecast_24h_pct"),  suffix="%")),
    ("Variance premium",    _f(sv.get("variance_premium_24h_pct"),    fmt="+.1f", suffix="vp")),
])
_metric_row([
    ("25d Skew",            _f(sv.get("skew_25d_pct"),              fmt="+.1f", suffix="vp")),
    ("Front/back spread",   _f(sv.get("front_back_spread_pct"),     fmt="+.1f", suffix="vp")),
    ("Jump premium",        _f(sv.get("jump_premium_proxy_pct"),    fmt="+.1f", suffix="vp")),
    ("Surface rel. avg",    _f(sv.get("surface_reliability_avg"),   fmt=".2f")),
    ("Low-rel. contracts",  str(sv.get("low_reliability_instrument_count") or "—")),
])

# ── Screened contracts count (no directional language) ────────────────────
_screened = (sv.get("signal_count_buy_vol") or 0) + (sv.get("signal_count_sell_vol") or 0) + (sv.get("signal_count_blocked") or 0)
_rel_avg  = sv.get("surface_reliability_avg")
st.caption(
    f"{_screened} contracts screened from in-house surface. "
    f"Surface reliability avg: **{_rel_avg:.2f}**. "
    "Trade opportunities — if any — are presented after full analysis below."
    if _rel_avg else f"{_screened} contracts screened from in-house surface."
)

# ── Charts ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Visualizations")

col_l, col_r = st.columns(2)

# Chart 1 — GEX level map
with col_l:
    st.markdown("**GEX Level Map**")
    st.caption("Key structural levels relative to spot.")

    walls = sv.get("top3_gamma_walls", [])
    levels_plot = []
    level_colors = []
    level_labels = []
    level_vals   = []

    named = [
        ("Put Wall",   sv.get("put_wall_strike"),   sv.get("put_wall_strength_usd_m"),   RED),
        ("Zero Gamma", sv.get("zero_gamma_strike"),  None,                                ORANGE),
        ("Max Pain",   sv.get("max_pain_strike"),    None,                                PURPLE),
        ("Call Wall",  sv.get("call_wall_strike"),   sv.get("call_wall_strength_usd_m"),  BLUE),
        ("Spot",       spot,                         None,                                "white"),
    ]
    for wall in walls:
        named.append((f"γ Wall ${wall['strike']:,.0f}", wall["strike"], wall["gross_usd_m"], GREEN))

    named = [(lbl, s, v, c) for lbl, s, v, c in named if s]
    named.sort(key=lambda x: x[1])

    fig_lev = go.Figure()
    # Invisible anchor trace — required for shapes + annotations to render correctly
    all_strikes = [s for _, s, _, _ in named if s]
    if all_strikes:
        fig_lev.add_trace(go.Scatter(
            x=[0.5] * len(all_strikes),
            y=all_strikes,
            mode="markers",
            marker=dict(opacity=0, size=1, color="rgba(0,0,0,0)"),
            showlegend=False,
            hoverinfo="skip",
        ))
    for lbl, strike, strength, color in named:
        fig_lev.add_shape(
            type="line",
            x0=0, x1=1, xref="paper",
            y0=strike, y1=strike,
            line=dict(color=color, width=2 if lbl != "Spot" else 3,
                      dash="dot" if lbl != "Spot" else "solid"),
        )
        ann_text = f"{lbl}: ${strike:,.0f}" + (f" ({strength:.1f}M)" if strength else "")
        fig_lev.add_annotation(
            x=1.01, xref="paper", y=strike,
            text=ann_text, showarrow=False,
            font=dict(color=color, size=11),
            xanchor="left",
        )

    fig_lev.update_layout(
        height=380, showlegend=False,
        yaxis_title="Strike ($)",
        xaxis=dict(visible=False),
        margin=dict(r=180),
    )
    st.plotly_chart(_style(fig_lev), use_container_width=True)

# Chart 2 — Term structure
with col_r:
    st.markdown("**Vol Term Structure**")
    st.caption("ATM IV across tenors vs RV benchmarks.")

    buckets = ["Spot week", "Front month", "Back month"]
    iv_vals = [
        sv.get("atm_iv_spot_week_pct")   or 0,
        sv.get("atm_iv_front_month_pct") or 0,
        sv.get("atm_iv_back_month_pct")  or 0,
    ]
    rv_24 = sv.get("rv_24h_pct") or 0
    rv_72 = sv.get("rv_72h_pct") or 0
    har   = sv.get("har_rv_forecast_24h_pct") or 0

    fig_ts = go.Figure()
    fig_ts.add_trace(go.Scatter(
        x=buckets, y=iv_vals, mode="lines+markers",
        name="ATM IV", line=dict(color=BLUE, width=2),
        marker=dict(size=8),
    ))
    for val, label, color in [(rv_24, "RV 24h", GREEN), (rv_72, "RV 72h", ORANGE), (har, "HAR RV forecast", YELLOW)]:
        if val:
            fig_ts.add_hline(y=val, line_dash="dot", line_color=color,
                             annotation_text=f"{label}: {val:.1f}%",
                             annotation_font_color=color, annotation_font_size=10,
                             annotation_position="top left")
    fig_ts.update_layout(height=380, yaxis_title="Implied Vol (%)", xaxis_title="Tenor")
    st.plotly_chart(_style(fig_ts), use_container_width=True)

# Chart 3 — Mechanical flow bar
st.markdown("**Mechanical Flow Summary**")
st.caption(
    "Net directional pressure from each mechanical layer over 24h. "
    "Charm is deterministic. Vanna shown for IV ±5 vol pt scenarios."
)
charm_val = sv.get("charm_net_usd_m_per_day", 0)
vanna_up  = sv.get("vanna_flow_if_iv_up_5", 0)
vanna_dn  = sv.get("vanna_flow_if_iv_down_5", 0)

flow_labels = ["Charm (24h)", "Vanna (IV +5vp)", "Vanna (IV −5vp)"]
flow_vals   = [charm_val, vanna_up, vanna_dn]
flow_colors = [GREEN if v >= 0 else RED for v in flow_vals]

fig_flow = go.Figure(go.Bar(
    x=flow_labels, y=flow_vals,
    marker_color=flow_colors, opacity=0.85,
    text=[f"{v:+.1f}M" for v in flow_vals],
    textposition="outside",
    textfont=dict(color=FONT_COLOR),
))
fig_flow.add_hline(y=0, line_color="grey", line_dash="dash", line_width=1)
fig_flow.update_layout(height=280, yaxis_title="USD M delta", showlegend=False)
st.plotly_chart(_style(fig_flow), use_container_width=True)

# Chart 4 — Book aggregate greeks
with st.expander("Book Aggregate Greeks (all listed instruments)"):
    st.caption(
        "**Raw sums** of per-instrument greeks across all listed instruments "
        "(sign/direction indicator only — not OI-weighted). "
        "OI-weighted values below show true market delta exposure."
    )
    net_d = sv.get("net_delta")
    net_g = sv.get("net_gamma")
    net_t = sv.get("net_theta")
    net_v = sv.get("net_vega")
    if any(x is not None for x in [net_d, net_g, net_t, net_v]):
        _metric_row([
            ("Σ Delta (raw)",  f"{net_d:+.1f}" if net_d is not None else "—"),
            ("Σ Gamma (raw)",  f"{net_g:+.4f}" if net_g is not None else "—"),
            ("Σ Theta (raw)",  f"{net_t:+.0f}" if net_t is not None else "—"),
            ("Σ Vega (raw)",   f"{net_v:+.0f}" if net_v is not None else "—"),
        ])
    else:
        st.info("Position state not available in artifacts.")

    # OI-weighted greeks — true aggregate exposure
    oi_d = sv.get("oi_wtd_delta_usd_m")
    oi_t = sv.get("oi_wtd_theta_usd_day_k")
    oi_v = sv.get("oi_wtd_vega_usd_k")
    if any(x is not None for x in [oi_d, oi_t, oi_v]):
        st.markdown("**OI-weighted (true market exposure):**")
        _metric_row([
            ("Net Delta (OI×δ)", _f(sv.get("oi_wtd_delta_btc"), fmt="+,.0f", suffix=" BTC")),
            ("Net Delta USD",    _f(oi_d, fmt="+.1f", suffix="M")),
            ("Net Theta/day",    _f(oi_t, fmt="+.0f", suffix="K USD")),
            ("Net Vega/1%IV",   _f(oi_v, fmt="+.0f", suffix="K USD")),
        ])

    # Breakdown by TTE bucket
    breakdown = sv.get("book_by_tte_bucket", [])
    if breakdown:
        st.markdown("**Breakdown by expiry bucket:**")
        import pandas as _pd
        df_bk = _pd.DataFrame(breakdown)
        df_bk = df_bk.rename(columns={
            "bucket": "Expiry bucket",
            "delta_sum": "Σ Delta",
            "gamma_sum": "Σ Gamma",
            "theta_sum": "Σ Theta",
            "vega_sum": "Σ Vega",
            "oi_notional_m": "OI Notional $M",
            "contracts": "Instruments",
        })
        st.dataframe(df_bk, use_container_width=True, hide_index=True)

# ── Full Claude Analysis (Phases 3–10) ────────────────────────────────────
st.divider()
st.subheader("Full Analysis — Phases 3–10")

import sys as _sys
_sys.path.insert(0, str(ROOT))
import analyst_runner

_grade_ctx = st.session_state.get("grade_ctx")

# Run analysis via claude --print streaming
if st.session_state.get("needs_analysis"):
    st.session_state["needs_analysis"] = False  # clear flag

    # Collect grade context if not already done
    if _grade_ctx is None:
        with st.spinner("Loading grading context…"):
            _grade_ctx = _run(["grade"])
            st.session_state["grade_ctx"] = _grade_ctx

    st.info(
        "Running 10-phase quantitative analysis via Claude... "
        "This takes 30–90 seconds. The output streams live below."
    )
    try:
        placeholder = st.empty()
        accumulated = ""

        for chunk in analyst_runner.stream_analysis(sv, _grade_ctx):
            accumulated += chunk
            # Strip Phase 10 log block from display; keep full text for JSON extraction
            placeholder.markdown(_clean_for_display(accumulated))

        full_text = accumulated
        st.session_state["analysis_text"] = full_text

        # Extract log JSON and save
        log_data = analyst_runner.extract_log_json(full_text)
        if log_data:
            saved_path = analyst_runner.save_log(log_data)
            st.session_state["analysis_log"] = log_data
            if saved_path:
                st.success(f"Log saved → `{saved_path}`")
        else:
            st.warning(
                "Analysis complete but log JSON not found in output. "
                "Save the text above manually or re-run."
            )
    except Exception as e:
        st.error(f"Analysis failed: {e}")

elif st.session_state.get("analysis_text"):
    # Show cached analysis from this session (Phase 10 stripped)
    st.markdown(_clean_for_display(st.session_state["analysis_text"]))
    log_data = st.session_state.get("analysis_log")

else:
    # Check if today's log exists from a previous session
    from datetime import date as _date
    _today_log = LOGS / f"{_date.today().isoformat()}.json"
    if _today_log.exists():
        import json as _json
        with open(_today_log) as _f:
            log_data = _json.load(_f)
        st.success(f"Loaded today's log: `{_today_log.name}` — re-run to refresh.")
    else:
        st.info("Analysis not yet run for today. Press **▶ Run Full Analysis** to execute all 10 phases.")
        log_data = None

# ── Structured results from log ────────────────────────────────────────────
log_data = (
    st.session_state.get("analysis_log")
    or locals().get("log_data")
)

if log_data:
    st.divider()
    st.subheader("Structured Results")

    # Conviction
    cv = log_data.get("conviction_score", {})
    if cv:
        direction = cv.get("direction", "—")
        score     = float(cv.get("conviction_final", cv.get("conviction_raw", 0)) or 0)
        color     = _color_direction(direction)
        st.markdown(
            f"**Conviction:** {_badge(f'{direction.upper()}  {score:.1f}/10', color)}",
            unsafe_allow_html=True,
        )
        st.progress(min(score / 10, 1.0))

    # Prediction block
    pred = log_data.get("prediction_24h", {})
    if pred:
        st.markdown("#### 24h Prediction")
        p1, p2, p3, p4 = st.columns(4)
        central = pred.get("central_estimate_24h")
        rng68   = _parse_range(pred.get("range_68pct"))
        p1.metric("Central estimate",  f"${central:,.0f}" if central else "—")
        p2.metric("68% range",
            f"${rng68[0]:,.0f} – ${rng68[1]:,.0f}"
            if rng68 else "—")
        p3.metric("Vol direction",     pred.get("vol_direction_24h", "—"))
        p4.metric("Primary scenario",  pred.get("primary_scenario", "—"))

        # Range chart
        rng95 = _parse_range(pred.get("range_95pct"))
        if rng68 and rng68[0] and rng68[1]:
            fig_pred = go.Figure()
            if rng95 and rng95[0]:
                fig_pred.add_vrect(x0=rng95[0], x1=rng95[1], fillcolor=BLUE,
                                   opacity=0.10, line_width=0)
            fig_pred.add_vrect(x0=rng68[0], x1=rng68[1], fillcolor=BLUE,
                               opacity=0.25, line_width=0,
                               annotation_text="68% CI", annotation_position="top left",
                               annotation_font_color=BLUE)
            if central:
                fig_pred.add_vline(x=central, line_color=ORANGE, line_width=2,
                                   annotation_text=f"Central ${central:,.0f}",
                                   annotation_font_color=ORANGE)
            if spot:
                fig_pred.add_vline(x=spot, line_color="white", line_dash="dash", line_width=1,
                                   annotation_text=f"Spot ${spot:,.0f}",
                                   annotation_font_color=FONT_COLOR)
            fig_pred.update_layout(height=160, showlegend=False,
                                   xaxis_title="BTC Price ($)",
                                   yaxis=dict(visible=False))
            st.plotly_chart(_style(fig_pred), use_container_width=True)

        brief = pred.get("trading_brief")
        if brief:
            st.info(f"**Trading brief:** {brief}")

    # Key levels
    kl = log_data.get("key_levels", [])
    if kl:
        st.markdown("#### Key Levels")
        import pandas as _pd
        df_kl = _pd.DataFrame(kl)
        tier_sym = {1: "🟡", 2: "🟠", 3: "⚪"}
        if "tier" in df_kl.columns:
            df_kl["tier"] = df_kl["tier"].apply(lambda t: f"{tier_sym.get(int(t) if str(t).isdigit() else 0, '')} T{t}")
        show = [c for c in ["strike", "type", "tier", "distance_pct", "confluence", "invalidation"] if c in df_kl.columns]
        st.dataframe(df_kl[show] if show else df_kl, use_container_width=True, hide_index=True)

    # Scenario tree
    sc = log_data.get("scenario_tree", [])
    if sc:
        st.markdown("#### Scenario Tree")
        max_prob = max((s.get("probability", 0) for s in sc), default=0)
        for scenario in sc:
            prob  = scenario.get("probability", 0)
            label = scenario.get("label", "—")
            with st.expander(
                f"**{scenario.get('id', scenario.get('label', '?')[:2])}** — {label}  `P={prob:.0%}`",
                expanded=(prob == max_prob),
            ):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Trigger:** {scenario.get('trigger','—')}")
                    st.markdown(f"**Target:** {scenario.get('target', scenario.get('price_target','—'))}")
                    st.markdown(f"**Invalidation:** {scenario.get('invalidation','—')}")
                with c2:
                    st.markdown(f"**IV path:** {scenario.get('iv_path','—')}")
                    st.markdown(f"**Options edge:** {scenario.get('options_edge','—')}")
                    st.markdown(f"**GEX dynamic:** {scenario.get('gex_dynamic', scenario.get('GEX DYNAMIC','—'))}")

    # Trade recommendation
    trade = log_data.get("trade_recommendation", {})
    if trade and trade.get("status") not in ("monitoring_only", None, ""):
        st.markdown("#### Trade Recommendation")
        st.error(
            "⚠️ **Defined-risk structures only.** Max loss shown is a hard cap. "
            "Never implement naked short options. Hedge leg is mandatory when selling vol."
        )
        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("Structure", trade.get("structure", "—"))
        tc2.metric("Max loss",  trade.get("max_loss", "—"))
        tc3.metric("Entry",     trade.get("entry_trigger", "—"))
        tc4.metric("Stop",      trade.get("stop", "—"))
        st.caption(f"**Legs:** {trade.get('legs','—')}  |  **Sizing:** {trade.get('sizing','—')}")
        if trade.get("hedge"):
            st.caption(f"**Hedge:** {trade['hedge']}")
        if trade.get("contraindicated"):
            st.warning(f"**Do NOT:** {trade['contraindicated']}")
    elif trade:
        st.info(f"**Trade gate:** {trade.get('status', 'monitoring only')}")

    # Signal matrix — backend only, not shown in UI
