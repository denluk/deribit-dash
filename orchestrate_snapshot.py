from pathlib import Path
import argparse
import json
import pandas as pd

from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.execution_risk import spread_slippage_guardrails
from deribit_intel.surface_engine import build_observed_surface_nodes, build_surface_grid, build_surface_quality_report
from deribit_intel.market_repricing import reprice_from_surface, build_market_relative_value
from deribit_intel.surface_shocks import generate_surface_shock_scenarios, build_all_surface_shocks
from deribit_intel.surface_quality import score_contract_surface_reliability, build_surface_uncertainty_report
from deribit_intel.signals_market import build_market_first_signal_table, build_market_top_signals

def main():
    parser = argparse.ArgumentParser(description="Snapshot orchestrator for market-first refinement layer.")
    parser.add_argument("--input-path", default="/mnt/data/combined_data.parquet", help="Local parquet path or s3:// URI")
    parser.add_argument("--batch-dir", default="artifacts/batch", help="Directory with batch outputs")
    parser.add_argument("--out-dir", default="artifacts/snapshot")
    parser.add_argument("--snapshot-mode", default="latest_per_instrument", choices=["latest_per_instrument", "latest_hour"])
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    batch_dir = Path(args.batch_dir)

    df = load_deribit_parquet(args.input_path)
    df = add_base_fields(df)
    df = add_feature_layers(df)

    if args.snapshot_mode == "latest_hour":
        latest_hour = df["hour"].max()
        snapshot = df[df["hour"] == latest_hour].copy()
    else:
        snapshot = df.sort_values("timestamp").groupby("instrument").tail(1).copy()

    execution_flags = spread_slippage_guardrails(snapshot)

    regime_rv = pd.read_parquet(batch_dir / "regime_rv.parquet")
    vol_regimes = pd.read_parquet(batch_dir / "vol_regimes.parquet")
    event_premium = pd.read_parquet(batch_dir / "event_premium.parquet")

    # market-first layer
    observed_surface_nodes = build_observed_surface_nodes(df)
    surface_grid = build_surface_grid(df)
    surface_quality_report = build_surface_quality_report(surface_grid)
    market_repriced = reprice_from_surface(snapshot, surface_grid)
    market_relative_value = build_market_relative_value(snapshot, market_repriced)
    surface_scenarios = generate_surface_shock_scenarios()
    all_surface_shocks = build_all_surface_shocks(surface_grid)
    surface_reliability = score_contract_surface_reliability(snapshot, market_repriced)
    surface_uncertainty = build_surface_uncertainty_report(surface_reliability)

    # contextual joins from batch outputs
    signal_table = build_market_first_signal_table(snapshot, regime_rv, execution_flags, market_repriced, surface_reliability)
    signal_table = signal_table.merge(
        vol_regimes[["hour", "vol_regime"]], on="hour", how="left"
    ).merge(
        event_premium[["hour", "event_premium_proxy"]], on="hour", how="left"
    )
    top_signals = build_market_top_signals(signal_table)

    tables = {
        "snapshot_chain.parquet": snapshot,
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
        table.to_parquet(out / name, index=False)
        summary[name] = int(len(table))

    context = {
        "snapshot_mode": args.snapshot_mode,
        "snapshot_rows": int(len(snapshot)),
        "snapshot_instruments": int(snapshot["instrument"].nunique()),
        "latest_timestamp": str(snapshot["timestamp"].max()),
    }
    (out / "snapshot_summary.json").write_text(json.dumps(summary, indent=2))
    (out / "snapshot_context.json").write_text(json.dumps(context, indent=2))
    print(json.dumps({"out_dir": str(out), "tables": len(tables), "snapshot_rows": int(len(snapshot))}, indent=2))

if __name__ == "__main__":
    main()
