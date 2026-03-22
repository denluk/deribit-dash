from __future__ import annotations
import streamlit as st
from deribit_intel.branding import show_logo
from deribit_intel.data_source_ui import resolve_input_path
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.execution_risk import spread_slippage_guardrails
from deribit_intel.rv_models import build_hourly_underlying, regime_conditioned_rv_forecast
from deribit_intel.surface_engine import build_surface_grid
from deribit_intel.market_repricing import reprice_from_surface
from deribit_intel.surface_quality import score_contract_surface_reliability
from deribit_intel.signals_market import build_market_first_signal_table, build_market_top_signals

show_logo()
st.title("Market-First Signal Layer")
path = resolve_input_path("signals")
df = add_feature_layers(add_base_fields(load_deribit_parquet(path)))
flags = spread_slippage_guardrails(df)
pxh = build_hourly_underlying(df)
rvf = regime_conditioned_rv_forecast(pxh)
latest = df.sort_values("timestamp").groupby("instrument").tail(1).copy()
surface = build_surface_grid(df)
repriced = reprice_from_surface(latest, surface)
reliability = score_contract_surface_reliability(latest, repriced)
signals = build_market_first_signal_table(latest, rvf, flags, repriced, reliability)
top = build_market_top_signals(signals, top_n=100)

st.subheader("Top gated market-first signals")
st.caption("Ranked contracts with strongest executable signal after reliability and tradability gating.")
st.info(
    "Call to action: `buy_vol` means prioritize buying optionality (long volatility), "
    "`sell_vol` means prioritize selling optionality (short volatility), "
    "`hold` means no strong edge, and `blocked` means do not trade due to gating constraints."
)
st.caption(
    "Key columns: `raw_market_signal` is edge strength, `gated_signal` is final action, "
    "`iv_edge_vs_rv` compares forecast RV to market IV, and `surface_reliability` is confidence weight."
)
st.dataframe(top, use_container_width=True)
