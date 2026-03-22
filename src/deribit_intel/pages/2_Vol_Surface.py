from __future__ import annotations
import streamlit as st
import plotly.express as px
from deribit_intel.branding import show_logo
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.vol_surface import extract_atm_monitor, build_skew_monitor, build_term_structure, realized_vs_implied_tracker, event_premium_decomposition
from deribit_intel.surface_interpolation import build_delta_tenor_surface

show_logo()
st.title("Volatility Surface Engine")
path = resolve_input_path("vol_surface")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))

atm = extract_atm_monitor(df)
skew = build_skew_monitor(df)
term = build_term_structure(df)
rviv = realized_vs_implied_tracker(df)
event = event_premium_decomposition(df)
surf = build_delta_tenor_surface(df)

st.subheader("ATM IV monitor")
st.caption("Median at-the-money implied volatility by hour, split by tenor bucket and option type.")
fig = px.line(atm, x="hour", y="atm_iv", color="tte_bucket", line_dash="type")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Realized vs Implied")
st.caption("Compares implied volatility proxy (`iv_proxy`) to realized volatility estimates (`rv_24h`, `rv_72h`) in the same percent-vol units.")
fig2 = px.line(rviv, x="hour", y=["iv_proxy", "rv_24h", "rv_72h"])
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Event premium proxy")
st.caption("Near-term IV minus farther-term IV. Positive values suggest extra short-dated event premium.")
fig3 = px.line(event, x="hour", y=["near_iv", "far_iv", "event_premium_proxy"])
st.plotly_chart(fig3, use_container_width=True)

st.subheader("Latest delta-tenor surface")
st.caption("Heatmap of current implied vol by delta bucket and tenor bucket. Useful for spotting local surface dislocations.")
latest_hour = surf["hour"].max()
s = surf[surf["hour"] == latest_hour].copy()
s["delta_bucket"] = s["delta_bucket"].astype(str)
s["tenor_days_bucket"] = s["tenor_days_bucket"].astype(str)
fig4 = px.density_heatmap(s, x="tenor_days_bucket", y="delta_bucket", z="mark_iv", facet_col="type", text_auto=True)
st.plotly_chart(fig4, use_container_width=True)
