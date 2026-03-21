from pathlib import Path
import argparse
import json
import pandas as pd

from deribit_intel.s3_ingestion import list_s3_keys, filter_keys_by_partition, load_s3_parquet_dataset
from deribit_intel.loaders import load_deribit_parquet, add_base_fields
from deribit_intel.features import add_feature_layers
from deribit_intel.position_state import add_higher_order_placeholders, build_position_state, build_expiry_sensitivity, build_strike_convexity_map
from deribit_intel.vol_surface import extract_atm_monitor, build_skew_monitor, build_term_structure, realized_vs_implied_tracker, event_premium_decomposition, vol_regime_labeling
from deribit_intel.rv_models import build_hourly_underlying, har_rv_forecast, regime_conditioned_rv_forecast
from deribit_intel.edge_engine import variance_premium_monitor, jump_premium_estimation
from deribit_intel.execution_risk import spread_slippage_guardrails, max_short_gamma_limits, stress_test_book, liquidity_weighted_sizing, aggregate_portfolio_limits
from deribit_intel.portfolio import aggregate_book, concentration_report

def load_input(args) -> pd.DataFrame:
    if args.input_path:
        df = load_deribit_parquet(args.input_path)
    elif args.s3_uri:
        df = load_deribit_parquet(args.s3_uri)
    else:
        if not args.bucket or not args.prefix:
            raise ValueError("Provide --input-path, --s3-uri, or both --bucket and --prefix.")
        keys = list_s3_keys(args.bucket, args.prefix, aws_region=args.aws_region)
        keys = filter_keys_by_partition(keys, start_date=args.start_date, end_date=args.end_date)
        df = load_s3_parquet_dataset(args.bucket, keys, aws_region=args.aws_region)
        if df.empty:
            raise ValueError("No data loaded from S3. Check bucket/prefix/date filters.")
    df = add_base_fields(df)
    df = add_feature_layers(df)
    df = add_higher_order_placeholders(df)
    return df

def main():
    parser = argparse.ArgumentParser(
        description="Batch orchestrator for broad intelligence layer.",
        epilog=(
            "Examples:\n"
            "  python orchestrate_batch.py --input-path data/combined_data.parquet\n"
            "  python orchestrate_batch.py --s3-uri s3://my-bucket/data/options_greeks/BTC/2026-03-15.parquet\n"
            "  python orchestrate_batch.py --bucket my-bucket --prefix data/options_greeks/BTC/ --start-date 2026-03-15 --end-date 2026-03-15"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input-path", default=None, help="Local parquet path or s3:// URI")
    parser.add_argument("--s3-uri", default=None, help="Direct object path, e.g. s3://bucket/path/file.parquet")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--aws-region", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--out-dir", default="artifacts/batch")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = load_input(args)

    # Broad intelligence layer
    position_state = build_position_state(df)
    expiry_sensitivity = build_expiry_sensitivity(df)
    strike_convexity = build_strike_convexity_map(df)

    atm_monitor = extract_atm_monitor(df)
    skew_monitor = build_skew_monitor(df)
    term_structure = build_term_structure(df)
    rv_iv_tracker = realized_vs_implied_tracker(df)
    event_premium = event_premium_decomposition(df)
    vol_regimes = vol_regime_labeling(rv_iv_tracker)

    hourly_underlying = build_hourly_underlying(df)
    har_rv = har_rv_forecast(hourly_underlying)
    regime_rv = regime_conditioned_rv_forecast(hourly_underlying)
    variance_premium = variance_premium_monitor(rv_iv_tracker)
    jump_premium = jump_premium_estimation(
        regime_rv.merge(rv_iv_tracker[["hour", "iv_proxy"]], on="hour", how="left")
                 .rename(columns={"regime_rv_forecast_24h": "rv_forecast_24h"}),
        event_premium,
    )

    execution_flags = spread_slippage_guardrails(df)
    stress_matrix = stress_test_book(df)
    short_gamma_limits = max_short_gamma_limits(position_state, gamma_limit=100.0)
    sizing = liquidity_weighted_sizing(df)
    portfolio_aggregate = aggregate_portfolio_limits(df)
    book_aggregate = aggregate_book(df)
    concentration = concentration_report(df)

    tables = {
        "normalized_chain.parquet": df,
        "position_state.parquet": position_state,
        "expiry_sensitivity.parquet": expiry_sensitivity,
        "strike_convexity.parquet": strike_convexity,
        "atm_monitor.parquet": atm_monitor,
        "skew_monitor.parquet": skew_monitor,
        "term_structure.parquet": term_structure,
        "rv_iv_tracker.parquet": rv_iv_tracker,
        "event_premium.parquet": event_premium,
        "vol_regimes.parquet": vol_regimes,
        "hourly_underlying.parquet": hourly_underlying,
        "har_rv.parquet": har_rv,
        "regime_rv.parquet": regime_rv,
        "variance_premium.parquet": variance_premium,
        "jump_premium.parquet": jump_premium,
        "execution_flags.parquet": execution_flags,
        "stress_matrix.parquet": stress_matrix,
        "short_gamma_limits.parquet": short_gamma_limits,
        "sizing.parquet": sizing,
        "portfolio_aggregate.parquet": portfolio_aggregate,
        "book_aggregate.parquet": book_aggregate,
        "concentration.parquet": concentration,
    }

    summary = {}
    for name, table in tables.items():
        table.to_parquet(out / name, index=False)
        summary[name] = int(len(table))

    context = {
        "latest_hour": str(df["hour"].max()),
        "rows": int(len(df)),
        "instruments": int(df["instrument"].nunique()),
        "time_min": str(df["timestamp"].min()),
        "time_max": str(df["timestamp"].max()),
    }
    (out / "batch_summary.json").write_text(json.dumps(summary, indent=2))
    (out / "batch_context.json").write_text(json.dumps(context, indent=2))
    print(json.dumps({"out_dir": str(out), "tables": len(tables), "rows": int(len(df))}, indent=2))

if __name__ == "__main__":
    main()
