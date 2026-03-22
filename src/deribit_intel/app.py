from __future__ import annotations
import streamlit as st
from deribit_intel.branding import show_logo

st.set_page_config(layout="wide", page_title="Deribit Market-First Options Intelligence")
show_logo()
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
- **GEX — Gamma Exposure** (dealer-gamma framework, vol regime indicator)

The repricing layer is used for normalization and scenario work, not as a claim of true venue pricing.
""")
