from __future__ import annotations
import streamlit as st
import plotly.express as px
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.position_state import build_position_state, build_expiry_sensitivity, build_strike_convexity_map

st.title("Position State Engine")
path = resolve_input_path("position_state")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))
pos = build_position_state(df)
exp = build_expiry_sensitivity(df)
conv = build_strike_convexity_map(df)

st.subheader("Net Greeks")
st.caption("Shows hourly net portfolio risk exposures. Positive/negative levels indicate directional delta, convexity gamma, carry theta, and volatility sensitivity vega.")
fig = px.line(pos, x="hour", y=["net_delta", "net_gamma", "net_theta", "net_vega"])
st.plotly_chart(fig, use_container_width=True)

st.subheader("Expiry sensitivity")
st.caption("Breaks risk by time-to-expiry bucket. Use this to see where exposure is concentrated on the maturity curve.")
metric = st.selectbox("Metric", ["delta_sum", "gamma_sum", "theta_sum", "vega_sum", "oi_notional"])
fig2 = px.line(exp, x="hour", y=metric, color="tte_bucket")
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Strike convexity map")
st.caption("Latest snapshot of gamma concentration by strike bucket. Large bars highlight strike zones with strongest convexity risk.")
latest = conv.sort_values("hour").groupby("strike_bucket").tail(1)
fig3 = px.bar(latest, x="strike_bucket", y="gamma_sum")
st.plotly_chart(fig3, use_container_width=True)
