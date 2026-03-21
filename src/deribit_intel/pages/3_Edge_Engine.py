from __future__ import annotations
import streamlit as st
import plotly.express as px
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.rv_models import build_hourly_underlying, regime_conditioned_rv_forecast
from deribit_intel.vol_surface import realized_vs_implied_tracker, event_premium_decomposition
from deribit_intel.edge_engine import variance_premium_monitor, jump_premium_estimation

st.title("Edge Engine")
path = resolve_input_path("edge_engine")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))
pxh = build_hourly_underlying(df)
rvf = regime_conditioned_rv_forecast(pxh)
rviv = realized_vs_implied_tracker(df)
varp = variance_premium_monitor(rviv)
event = event_premium_decomposition(df)
rv_for_jump = (
    rvf.merge(rviv[["hour", "iv_proxy"]], on="hour", how="left")
       .rename(columns={"regime_rv_forecast_24h": "rv_forecast_24h"})
)
jump = jump_premium_estimation(rv_for_jump, event)

st.subheader("HAR / regime-conditioned RV forecast")
st.caption("Realized vol baseline (`rv_24h`) versus model forecasts. `regime_rv_forecast_24h` is the forecast adjusted for current volatility regime.")
fig = px.line(rvf, x="hour", y=["rv_24h", "har_rv_forecast_24h", "regime_rv_forecast_24h"])
st.plotly_chart(fig, use_container_width=True)

st.subheader("Variance premium")
st.caption("Variance risk premium proxies (implied variance minus realized variance). Higher values imply richer implied vol versus realized.")
cols = [c for c in varp.columns if c.startswith("variance_premium_")]
fig2 = px.line(varp, x="hour", y=cols)
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Jump premium proxy")
st.caption("Estimated jump component from event premium plus implied-vs-forecast spread. Tracks discontinuity risk pricing.")
fig3 = px.line(jump, x="hour", y=["iv_proxy", "rv_forecast_24h", "event_premium_proxy", "jump_premium_proxy"])
st.plotly_chart(fig3, use_container_width=True)
