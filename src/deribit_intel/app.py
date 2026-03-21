from __future__ import annotations
import streamlit as st

st.set_page_config(layout="wide", page_title="Deribit Market-First Options Intelligence")
st.title("Deribit Market-First Options Intelligence")

st.markdown("""
This dashboard uses a **market-surface-first** approach.

Core pages:
- Position State
- Vol Surface
- Edge Engine
- Execution & Risk
- Market-First Signals
- Surface Fit & Quality

The repricing layer is used for normalization and scenario work, not as a claim of true venue pricing.
""")
