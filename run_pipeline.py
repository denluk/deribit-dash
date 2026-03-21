from pathlib import Path
import json

from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.position_state import (
    add_higher_order_placeholders,
    build_position_state,
    build_expiry_sensitivity,
    build_strike_convexity_map,
    scenario_shock_grid,
)
from deribit_intel.vol_surface import (
    extract_atm_monitor,
    build_skew_monitor,
    build_term_structure,
    realized_vs_implied_tracker,
    event_premium_decomposition,
    vol_regime_labeling,
)
from deribit_intel.surface_interpolation import build_delta_tenor_surface, build_surface_features
from deribit_intel.rv_models import build_hourly_underlying, har_rv_forecast, regime_conditioned_rv_forecast
from deribit_intel.edge_engine import (
    variance_premium_monitor,
    jump_premium_estimation,
    expected_value_proxy,
)
from deribit_intel.execution_risk import (
    spread_slippage_guardrails,
    max_short_gamma_limits,
    stress_test_book,
    liquidity_weighted_sizing,
    aggregate_portfolio_limits,
)
from deribit_intel.portfolio import aggregate_book, concentration_report
from deribit_intel.surface_engine import build_observed_surface_nodes, build_surface_grid, build_surface_quality_report
from deribit_intel.market_repricing import reprice_from_surface, build_market_relative_value
from deribit_intel.surface_shocks import generate_surface_shock_scenarios, build_all_surface_shocks
from deribit_intel.surface_quality import score_contract_surface_reliability, build_surface_uncertainty_report
from deribit_intel.signals_market import build_market_first_signal_table, build_market_top_signals

INPUT_PATH = "/mnt/data/combined_data.parquet"
OUT = Path("artifacts")
OUT.mkdir(exist_ok=True)

df = load_deribit_parquet(INPUT_PATH)
df = add_base_fields(df)
df = add_feature_layers(df)
df = add_higher_order_placeholders(df)

# Module 1
position_state = build_position_state(df)
expiry_sensitivity = build_expiry_sensitivity(df)
strike_convexity = build_strike_convexity_map(df)
scenario_grid = scenario_shock_grid(df)

# Module 2
atm_monitor = extract_atm_monitor(df)
skew_monitor = build_skew_monitor(df)
term_structure = build_term_structure(df)
rv_iv_tracker = realized_vs_implied_tracker(df)
event_premium = event_premium_decomposition(df)
vol_regimes = vol_regime_labeling(rv_iv_tracker)
delta_tenor_surface = build_delta_tenor_surface(df)
surface_features = build_surface_features(delta_tenor_surface)

# Module 3
hourly_underlying = build_hourly_underlying(df)
har_rv = har_rv_forecast(hourly_underlying)
regime_rv = regime_conditioned_rv_forecast(hourly_underlying)
variance_premium = variance_premium_monitor(rv_iv_tracker)
jump_premium = jump_premium_estimation(
    regime_rv.merge(rv_iv_tracker[["hour", "iv_proxy"]], on="hour", how="left")
             .rename(columns={"regime_rv_forecast_24h": "rv_forecast_24h"}),
    event_premium,
)
ev_proxy = expected_value_proxy(df, regime_rv.rename(columns={"regime_rv_forecast_24h": "rv_forecast_24h"}))

# Module 4
execution_flags = spread_slippage_guardrails(df)
short_gamma_limits = max_short_gamma_limits(position_state, gamma_limit=100.0)
stress_matrix = stress_test_book(df)
sizing = liquidity_weighted_sizing(df)
portfolio_aggregate = aggregate_portfolio_limits(df)
book_aggregate = aggregate_book(df)
concentration = concentration_report(df)

# Market-surface-first module
observed_surface_nodes = build_observed_surface_nodes(df)
surface_grid = build_surface_grid(df)
surface_quality_report = build_surface_quality_report(surface_grid)
latest_contracts = df.sort_values("timestamp").groupby("instrument").tail(1).copy()
market_repriced = reprice_from_surface(latest_contracts, surface_grid)
market_relative_value = build_market_relative_value(latest_contracts, market_repriced)
surface_scenarios = generate_surface_shock_scenarios()
all_surface_shocks = build_all_surface_shocks(surface_grid)
surface_reliability = score_contract_surface_reliability(latest_contracts, market_repriced)
surface_uncertainty = build_surface_uncertainty_report(surface_reliability)

# Signals
signal_table = build_market_first_signal_table(latest_contracts, regime_rv, execution_flags, market_repriced, surface_reliability)
top_signals = build_market_top_signals(signal_table)

tables = {
    "position_state.parquet": position_state,
    "expiry_sensitivity.parquet": expiry_sensitivity,
    "strike_convexity.parquet": strike_convexity,
    "scenario_grid.parquet": scenario_grid,
    "atm_monitor.parquet": atm_monitor,
    "skew_monitor.parquet": skew_monitor,
    "term_structure.parquet": term_structure,
    "rv_iv_tracker.parquet": rv_iv_tracker,
    "event_premium.parquet": event_premium,
    "vol_regimes.parquet": vol_regimes,
    "delta_tenor_surface.parquet": delta_tenor_surface,
    "surface_features.parquet": surface_features,
    "hourly_underlying.parquet": hourly_underlying,
    "har_rv.parquet": har_rv,
    "regime_rv.parquet": regime_rv,
    "variance_premium.parquet": variance_premium,
    "jump_premium.parquet": jump_premium,
    "ev_proxy.parquet": ev_proxy,
    "execution_flags.parquet": execution_flags,
    "short_gamma_limits.parquet": short_gamma_limits,
    "stress_matrix.parquet": stress_matrix,
    "sizing.parquet": sizing,
    "portfolio_aggregate.parquet": portfolio_aggregate,
    "book_aggregate.parquet": book_aggregate,
    "concentration.parquet": concentration,
    "observed_surface_nodes.parquet": observed_surface_nodes,
    "surface_grid.parquet": surface_grid,
    "surface_quality_report.parquet": surface_quality_report,
    "market_repriced.parquet": market_repriced,
    "market_relative_value.parquet": market_relative_value,
    "surface_scenarios.parquet": surface_scenarios,
    "all_surface_shocks.parquet": all_surface_shocks,
    "surface_reliability.parquet": surface_reliability,
    "surface_uncertainty.parquet": surface_uncertainty,
    "signal_table.parquet": signal_table,
    "top_signals.parquet": top_signals,
}

summary = {}
for name, table in tables.items():
    table.to_parquet(OUT / name, index=False)
    summary[name] = int(len(table))

(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(summary)
