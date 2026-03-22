from __future__ import annotations
import streamlit as st
import plotly.express as px
from deribit_intel.branding import show_logo
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.position_state import build_position_state
from deribit_intel.execution_risk import spread_slippage_guardrails, max_short_gamma_limits, stress_test_book, liquidity_weighted_sizing, aggregate_portfolio_limits

show_logo()
st.title("Execution & Risk")
path = resolve_input_path("execution_risk")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))

flags = spread_slippage_guardrails(df)
pos = build_position_state(df)
gamma = max_short_gamma_limits(pos, gamma_limit=100.0)
stress = stress_test_book(df)
sizing = liquidity_weighted_sizing(df)
port = aggregate_portfolio_limits(df)

st.subheader("Tradability breakdown")
st.caption("Share of contracts currently passing tradability checks. More `1` means broader executable universe.")
fig = px.histogram(flags, x="tradable_flag")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Short gamma breaches")
st.caption("Net gamma versus breach flag over time. Breach indicates short-gamma exposure beyond configured limit.")
fig2 = px.line(gamma, x="hour", y=["net_gamma", "short_gamma_breach"])
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Stress matrix")
st.caption("PnL sensitivity grid under spot and IV shocks. Use it to identify tail-risk directions and magnitudes.")
fig3 = px.density_heatmap(stress, x="spot_gap", y="iv_shock", z="stress_pnl", text_auto=True)
st.plotly_chart(fig3, use_container_width=True)

st.subheader("Liquidity-weighted sizing")
st.caption("Position size multiplier versus spread. Wider spreads usually reduce suggested size.")
latest = sizing.sort_values("timestamp").groupby("instrument").tail(1)
fig4 = px.scatter(latest, x="spread_bps_mid", y="size_multiplier", size="open_interest", hover_name="instrument")
st.plotly_chart(fig4, use_container_width=True)

st.subheader("Portfolio aggregates")
st.caption("Portfolio totals by expiry bucket for the selected metric. Helps locate where aggregate risk is concentrated.")
metric = st.selectbox("Portfolio metric", ["delta_sum", "gamma_sum", "theta_sum", "vega_sum", "oi_notional"])
fig5 = px.line(port, x="hour", y=metric, color="tte_bucket")
st.plotly_chart(fig5, use_container_width=True)
