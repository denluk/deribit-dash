from __future__ import annotations
import streamlit as st
import plotly.express as px
from deribit_intel.branding import show_logo
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.surface_engine import build_surface_grid, build_surface_quality_report
from deribit_intel.market_repricing import reprice_from_surface
from deribit_intel.surface_quality import score_contract_surface_reliability, build_surface_uncertainty_report

show_logo()
st.title("Surface Fit & Quality")
path = resolve_input_path("surface_quality")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))
surface = build_surface_grid(df)
q = build_surface_quality_report(surface)
repriced = reprice_from_surface(df.sort_values("timestamp").groupby("instrument").tail(1), surface)
rel = score_contract_surface_reliability(df.sort_values("timestamp").groupby("instrument").tail(1), repriced)
unc = build_surface_uncertainty_report(rel)

st.subheader("Surface quality over time")
st.caption("Average fit confidence by option type over time. Higher values indicate better local surface fit quality.")
fig = px.line(q, x="hour", y="avg_fit_confidence", color="type")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Uncertainty report")
st.caption("Tracks mean reliability and low-reliability share. Rising low-reliability share signals weaker model trust.")
fig2 = px.line(unc, x="hour", y=["avg_surface_reliability", "low_reliability_share"], color="type")
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Latest contract reliability")
st.caption("Top contracts by current surface reliability score. Use as confidence context for repricing and signal consumption.")
st.dataframe(rel.sort_values("surface_reliability", ascending=False).head(100), use_container_width=True)
