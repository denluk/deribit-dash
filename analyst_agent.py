"""
Deribit Quant Analyst — data extraction CLI.

Subcommands:
  audit       — check S3 creds, list S3 partitions, check artifact freshness
  extract     — read all parquets + compute GEX, output full state vector JSON
  grade       — grade yesterday's prediction, update signal_stats.json
  write-log   — write a full daily log JSON (receives data via --data)

Usage (from deribit-dash/ with venv active):
  python analyst_agent.py audit
  python analyst_agent.py extract
  python analyst_agent.py grade
  python analyst_agent.py write-log --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── paths ──────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
ARTIFACTS   = ROOT / "artifacts"
BATCH       = ARTIFACTS / "batch"
SNAPSHOT    = ARTIFACTS / "snapshot"
LOGS        = ROOT / "logs"
ACCURACY    = ROOT / "accuracy"
ENV_S3      = ROOT / ".env.s3"
SIGNAL_STATS = ACCURACY / "signal_stats.json"
CALIBRATION  = ACCURACY / "calibration.json"

TODAY     = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

# ── helpers ────────────────────────────────────────────────────────────────

def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _ema(old: float, new: float, alpha: float = 0.1) -> float:
    return alpha * new + (1 - alpha) * old


# ══════════════════════════════════════════════════════════════════════════
# SUBCOMMAND: audit
# ══════════════════════════════════════════════════════════════════════════

def cmd_audit() -> None:
    """Check S3 credentials, list partitions, check artifact freshness."""
    result: dict = {}

    # ── S3 credentials ──────────────────────────────────────────────────
    if ENV_S3.exists():
        for line in ENV_S3.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key  = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    bucket      = os.getenv("S3_BUCKET", os.getenv("AWS_S3_BUCKET", ""))
    prefix      = os.getenv("S3_PREFIX", os.getenv("AWS_S3_PREFIX", ""))
    region      = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", ""))

    result["s3_available"]  = bool(access_key and secret_key and bucket)
    result["s3_bucket"]     = bucket or None
    result["s3_prefix"]     = prefix or None
    result["s3_partitions"] = []
    result["s3_latest_date"] = None

    if result["s3_available"]:
        try:
            import boto3
            from deribit_intel.s3_ingestion import list_s3_keys, filter_keys_by_partition

            kwargs: dict = {}
            if region:
                kwargs["region_name"] = region
            kwargs["aws_access_key_id"]     = access_key
            kwargs["aws_secret_access_key"] = secret_key

            keys = list_s3_keys(bucket, prefix, aws_region=region or None)

            # Extract unique date partitions from keys
            import re
            dates = set()
            for key in keys:
                m = re.search(r"(?:dt|date)=(\d{4}-\d{2}-\d{2})", key)
                if m:
                    dates.add(m.group(1))
                else:
                    m2 = re.search(r"year=(\d{4})/month=(\d{2})/day=(\d{2})", key)
                    if m2:
                        dates.add(f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}")
                    else:
                        m3 = re.search(r"(\d{4}-\d{2}-\d{2})\.parquet$", key)
                        if m3:
                            dates.add(m3.group(1))

            result["s3_partitions"]  = sorted(dates)
            result["s3_latest_date"] = sorted(dates)[-1] if dates else None
            result["s3_key_count"]   = len(keys)
        except Exception as e:
            result["s3_available"]    = False
            result["s3_error"]        = str(e)

    # ── Batch artifacts ─────────────────────────────────────────────────
    batch_ctx = _read_json(BATCH / "batch_context.json")
    snap_ctx  = _read_json(SNAPSHOT / "snapshot_context.json")

    result["artifacts_batch_exists"]    = (BATCH / "batch_context.json").exists()
    result["artifacts_snapshot_exists"] = (SNAPSHOT / "snapshot_context.json").exists()

    latest_hour_str = batch_ctx.get("latest_hour")
    if latest_hour_str:
        try:
            latest_dt = pd.Timestamp(latest_hour_str)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.tz_localize("UTC")
            now_utc = pd.Timestamp.now(tz="UTC")
            freshness_minutes = int((now_utc - latest_dt).total_seconds() / 60)
        except Exception:
            freshness_minutes = 9999
    else:
        freshness_minutes = 9999

    result["batch_latest_hour"]   = latest_hour_str
    result["freshness_minutes"]   = freshness_minutes
    result["instruments"]         = batch_ctx.get("instruments")
    result["rows"]                = batch_ctx.get("rows")

    # ── Snapshot surface reliability ────────────────────────────────────
    surface_reliability = _read_parquet(SNAPSHOT / "surface_reliability.parquet")
    if not surface_reliability.empty and "surface_reliability" in surface_reliability.columns:
        result["surface_reliability_avg"] = round(float(surface_reliability["surface_reliability"].mean()), 3)
        result["surface_reliability_p10"] = round(float(surface_reliability["surface_reliability"].quantile(0.10)), 3)
    else:
        result["surface_reliability_avg"] = None
        result["surface_reliability_p10"] = None

    # ── Batch table completeness ────────────────────────────────────────
    batch_summary  = _read_json(BATCH / "batch_summary.json")
    snap_summary   = _read_json(SNAPSHOT / "snapshot_summary.json")
    result["batch_tables_present"]    = len(batch_summary)
    result["snapshot_tables_present"] = len(snap_summary)

    # ── Pipeline needed? ────────────────────────────────────────────────
    result["pipeline_needed"] = (
        not result["artifacts_batch_exists"]
        or freshness_minutes > 360
    )

    print(json.dumps(result, indent=2, default=str))


# ══════════════════════════════════════════════════════════════════════════
# SUBCOMMAND: extract
# ══════════════════════════════════════════════════════════════════════════

def cmd_extract() -> None:
    """Read all parquets + compute GEX. Output full state vector JSON."""

    # guard
    if not (BATCH / "normalized_chain.parquet").exists():
        print(json.dumps({"error": "normalized_chain.parquet not found — run pipeline first"}))
        sys.exit(1)

    sv: dict = {}

    # ── load normalized chain ────────────────────────────────────────────
    df = _read_parquet(BATCH / "normalized_chain.parquet")

    # ── GEX computation ──────────────────────────────────────────────────
    try:
        from deribit_intel.gex_engine import (
            compute_gex_by_strike,
            compute_gex_timeseries,
            compute_charm_pressure,
            compute_vanna_exposure,
            find_key_levels,
            compute_max_pain,
        )

        gex_strike = compute_gex_by_strike(df)
        gex_ts     = compute_gex_timeseries(df)
        charm      = compute_charm_pressure(df)
        vanna      = compute_vanna_exposure(df)
        max_pain_df = compute_max_pain(df)
        levels     = find_key_levels(gex_strike, max_pain_df)

        spot = float(levels["spot"])
        sv["spot"] = spot

        sv["gex_net_equity_usd_m"] = round(levels["net_gex_equity"] / 1e6, 2)
        sv["gex_net_crypto_usd_m"] = round(gex_ts["net_gex_crypto"].iloc[-1] / 1e6, 2)
        sv["gex_regime"]           = levels["regime"]

        # velocity trend over last 3 periods
        vel = gex_ts["gex_velocity"].dropna()
        if len(vel) >= 3:
            last3 = vel.iloc[-3:].values
            if all(v < 0 for v in last3):
                trend = "accelerating_negative"
            elif all(v > 0 for v in last3):
                trend = "accelerating_positive"
            elif abs(last3[-1]) < abs(last3[-2]):
                trend = "decelerating"
            elif last3[-1] * last3[-2] < 0:
                trend = "reversing"
            else:
                trend = "mixed"
        else:
            trend = "insufficient_data"

        sv["gex_velocity_1h"]      = round(float(vel.iloc[-1]) / 1e6, 2) if len(vel) else None
        sv["gex_velocity_trend"]   = trend

        sv["zero_gamma_strike"]       = levels["zero_gamma_strike"]
        sv["zero_gamma_distance_pct"] = round((levels["zero_gamma_strike"] - spot) / spot * 100, 2) if levels["zero_gamma_strike"] else None
        sv["put_wall_strike"]         = levels["put_wall"]
        sv["put_wall_distance_pct"]   = round((levels["put_wall"] - spot) / spot * 100, 2) if levels["put_wall"] else None
        sv["call_wall_strike"]        = levels["call_wall"]
        sv["call_wall_distance_pct"]  = round((levels["call_wall"] - spot) / spot * 100, 2) if levels["call_wall"] else None
        sv["max_pain_strike"]         = levels["max_pain"]
        sv["max_pain_distance_pct"]   = round((levels["max_pain"] - spot) / spot * 100, 2) if levels["max_pain"] else None

        # max_pain DTE: front expiry tte_days from snapshot
        snap = _read_parquet(SNAPSHOT / "snapshot_chain.parquet")
        if not snap.empty and "tte_days" in snap.columns:
            sv["max_pain_dte"] = int(snap["tte_days"].min())
        else:
            sv["max_pain_dte"] = None

        # top 3 absolute gamma walls
        top3 = sorted(levels["gamma_wall_top3"], key=lambda x: -x[1])
        sv["top3_gamma_walls"] = [
            {"strike": int(s), "gross_usd_m": round(g / 1e6, 2)}
            for s, g in top3
        ]

        # put/call wall strengths
        def _wall_strength(strike):
            if not strike:
                return None
            row = gex_strike[gex_strike["strike"].between(strike * 0.998, strike * 1.002)]
            if row.empty:
                return None
            return round(float(row["gex_abs"].sum()) / 1e6, 2)

        sv["put_wall_strength_usd_m"]  = _wall_strength(levels["put_wall"])
        sv["call_wall_strength_usd_m"] = _wall_strength(levels["call_wall"])

        # charm: gex_engine computes charm in units of USD/year (delta-change-per-year × OI × spot)
        # divide by 365 to get actual daily mechanical delta flow in USD
        charm_usd_yr = float(charm["charm_pressure_usd"].sum()) if not charm.empty else 0.0
        sv["charm_net_usd_m_per_day"] = round(charm_usd_yr / 1e6 / 365, 2)
        sv["charm_direction"] = "buy_pressure" if sv["charm_net_usd_m_per_day"] >= 0 else "sell_pressure"

        # vanna
        vanna_net = float(vanna["vanna_exp_1vp"].sum()) / 1e6 if not vanna.empty else 0.0
        sv["vanna_net_usd_m_per_vol_pt"] = round(vanna_net, 2)
        sv["vanna_flow_if_iv_up_5"]      = round(vanna_net * 5, 2)
        sv["vanna_flow_if_iv_down_5"]    = round(-vanna_net * 5, 2)

    except Exception as e:
        sv["gex_error"] = str(e)

    # ── Vol surface ─────────────────────────────────────────────────────
    # Bug fix: tte_bucket labels are "0-2d","3-7d","8-30d","31-90d" (see features.py)
    atm = _read_parquet(BATCH / "atm_monitor.parquet")
    if not atm.empty and "atm_iv" in atm.columns:
        latest_h = atm["hour"].max()
        atm_l    = atm[atm["hour"] == latest_h]
        buckets  = atm_l["tte_bucket"].astype(str)

        def _atm_for_buckets(bucket_strs: list) -> float | None:
            """Match any of the bucket labels and return median IV."""
            mask = buckets.str.contains("|".join(bucket_strs), na=False)
            row  = atm_l[mask]
            return round(float(row["atm_iv"].median()), 2) if not row.empty else None

        # spot-week = 0-2d + 3-7d buckets combined
        sv["atm_iv_spot_week_pct"]   = _atm_for_buckets(["0-2d", "3-7d"])
        sv["atm_iv_front_month_pct"] = _atm_for_buckets(["8-30d"])
        sv["atm_iv_back_month_pct"]  = _atm_for_buckets(["31-90d"])

        # 30d percentile rank using all spot-week rows in history
        hist_sw = atm[atm["tte_bucket"].astype(str).isin(["0-2d", "3-7d"])]["atm_iv"]
        if not hist_sw.empty and sv["atm_iv_spot_week_pct"]:
            sv["atm_iv_30d_percentile"] = round(float((hist_sw < sv["atm_iv_spot_week_pct"]).mean()) * 100, 1)
        else:
            sv["atm_iv_30d_percentile"] = None

    rv_iv = _read_parquet(BATCH / "rv_iv_tracker.parquet")
    if not rv_iv.empty:
        latest = rv_iv.sort_values("hour").iloc[-1]
        sv["iv_proxy_pct"]     = round(float(latest.get("iv_proxy", np.nan)), 2)
        sv["rv_24h_pct"]       = round(float(latest.get("rv_24h",   np.nan)), 2)
        sv["rv_72h_pct"]       = round(float(latest.get("rv_72h",   np.nan)), 2)
        sv["iv_rv_spread_pct"] = round(sv["iv_proxy_pct"] - sv["rv_24h_pct"], 2)

        # Bug fix: variance_premium from edge_engine is IV²-RV² (%² units) — not vol pts.
        # Use the simple VRP proxy already in rv_iv_tracker instead.
        vrp_col = next((c for c in rv_iv.columns if c.startswith("vrp_proxy_24")), None)
        if vrp_col:
            sv["variance_premium_24h_pct"] = round(float(latest.get(vrp_col, np.nan)), 2)

    # Bug fix: term_structure.parquet has iv_median per tte_bucket, NOT near_iv/far_iv.
    # near_iv / far_iv live in event_premium.parquet.
    event = _read_parquet(BATCH / "event_premium.parquet")
    if not event.empty:
        latest_e = event.sort_values("hour").iloc[-1]
        near = latest_e.get("near_iv", np.nan)
        far  = latest_e.get("far_iv",  np.nan)
        sv["near_iv_pct"]           = round(float(near), 2) if not np.isnan(float(near)) else None
        sv["far_iv_pct"]            = round(float(far),  2) if not np.isnan(float(far))  else None
        sv["event_premium_proxy_pct"] = round(float(latest_e.get("event_premium_proxy", np.nan)), 2)
        if sv["near_iv_pct"] is not None and sv["far_iv_pct"] is not None:
            spread = sv["near_iv_pct"] - sv["far_iv_pct"]
            sv["front_back_spread_pct"] = round(spread, 2)
            sv["term_structure_shape"]  = (
                "backwardated" if spread > 2 else
                "contango"     if spread < -2 else
                "flat"
            )

    # Bug fix: skew_monitor has skew_iv = raw IV of a bucket, NOT put-call spread.
    # Compute actual skew as OTM-put IV minus OTM-call IV for the spot-week bucket.
    skew_df = _read_parquet(BATCH / "skew_monitor.parquet")
    if not skew_df.empty and "skew_iv" in skew_df.columns:
        latest_h_sk = skew_df["hour"].max()
        sk = skew_df[skew_df["hour"] == latest_h_sk]
        # spot-week OTM puts vs OTM calls
        sw_buckets = ["0-2d", "3-7d"]
        put_otm  = sk[(sk["tte_bucket"].astype(str).isin(sw_buckets)) &
                      (sk["type"] == "put") &
                      (sk["mny_bucket"].astype(str) == "otm")]["skew_iv"].median()
        call_otm = sk[(sk["tte_bucket"].astype(str).isin(sw_buckets)) &
                      (sk["type"] == "call") &
                      (sk["mny_bucket"].astype(str) == "otm")]["skew_iv"].median()
        if not (np.isnan(put_otm) or np.isnan(call_otm)):
            skew_val = round(float(put_otm - call_otm), 2)
            sv["skew_25d_pct"]   = skew_val
            sv["skew_direction"] = "put_skew" if skew_val > 2 else ("call_skew" if skew_val < -2 else "balanced")

    jp = _read_parquet(BATCH / "jump_premium.parquet")
    if not jp.empty and "jump_premium_proxy" in jp.columns:
        latest_jp = jp.sort_values("hour").iloc[-1]
        sv["jump_premium_proxy_pct"] = round(float(latest_jp["jump_premium_proxy"]), 2)

    # Bug fix: har_rv and regime_rv are in decimal (no ×100).
    # rv_iv_tracker uses ×100 for %-point parity with mark_iv.
    # Must multiply by 100 to put forecasts on same scale.
    har = _read_parquet(BATCH / "har_rv.parquet")
    if not har.empty and "har_rv_forecast_24h" in har.columns:
        latest_har = har.sort_values("hour").iloc[-1]
        raw = float(latest_har["har_rv_forecast_24h"])
        # Detect scale: if value < 1.0 it's decimal, multiply by 100
        sv["har_rv_forecast_24h_pct"] = round(raw * 100 if raw < 1.0 else raw, 2)

    regime_rv = _read_parquet(BATCH / "regime_rv.parquet")
    if not regime_rv.empty and "regime_rv_forecast_24h" in regime_rv.columns:
        latest_rrv = regime_rv.sort_values("hour").iloc[-1]
        raw = float(latest_rrv["regime_rv_forecast_24h"])
        sv["regime_rv_forecast_24h_pct"] = round(raw * 100 if raw < 1.0 else raw, 2)

    vol_reg = _read_parquet(BATCH / "vol_regimes.parquet")
    if not vol_reg.empty:
        sv["vol_regime_label"] = str(vol_reg.sort_values("hour").iloc[-1].get("vol_regime", "unknown"))

    # ── Surface quality ──────────────────────────────────────────────────
    surf_rel = _read_parquet(SNAPSHOT / "surface_reliability.parquet")
    if not surf_rel.empty and "surface_reliability" in surf_rel.columns:
        sv["surface_reliability_avg"] = round(float(surf_rel["surface_reliability"].mean()), 3)
        sv["surface_reliability_p10"] = round(float(surf_rel["surface_reliability"].quantile(0.10)), 3)
        sv["low_reliability_instrument_count"] = int((surf_rel["surface_reliability"] < 0.6).sum())
    else:
        sv["surface_reliability_avg"] = None

    surf_q = _read_parquet(SNAPSHOT / "surface_quality_report.parquet")
    if not surf_q.empty and "avg_fit_confidence" in surf_q.columns:
        latest_sq = surf_q.sort_values("hour").iloc[-1] if "hour" in surf_q.columns else surf_q.iloc[-1]
        if "type" in surf_q.columns:
            for t in ["call", "put"]:
                row = surf_q[(surf_q["type"] == t)]
                if not row.empty:
                    sv[f"avg_fit_confidence_{t}"] = round(float(row.sort_values("hour").iloc[-1]["avg_fit_confidence"]), 3)

    # ── Book aggregate greeks ─────────────────────────────────────────────
    # position_state sums raw per-instrument greeks (no OI weighting) — useful
    # for sign/direction of the book structure across listed instruments.
    pos = _read_parquet(BATCH / "position_state.parquet")
    if not pos.empty:
        latest_pos = pos.sort_values("hour").iloc[-1]
        for col in ["net_delta", "net_gamma", "net_theta", "net_vega"]:
            if col in pos.columns:
                sv[col] = round(float(latest_pos[col]), 4)

    # OI-weighted greeks — true aggregate market exposure (latest hour snapshot)
    spot_val = sv.get("spot", 0)
    latest_chain = df[df["hour"] == df["hour"].max()] if not df.empty else pd.DataFrame()
    if not latest_chain.empty and "delta" in latest_chain.columns and "open_interest" in latest_chain.columns:
        oi = latest_chain["open_interest"].fillna(0)
        oi_delta = float((latest_chain["delta"].fillna(0) * oi).sum())
        oi_theta = float((latest_chain["theta"].fillna(0) * oi).sum())
        oi_vega  = float((latest_chain["vega"].fillna(0)  * oi).sum())
        sv["oi_wtd_delta_btc"]     = round(oi_delta, 1)
        sv["oi_wtd_theta_btc_day"] = round(oi_theta, 2)
        sv["oi_wtd_vega_btc_pct"]  = round(oi_vega,  2)
        if spot_val:
            sv["oi_wtd_delta_usd_m"]    = round(oi_delta * spot_val / 1e6, 2)
            sv["oi_wtd_theta_usd_day_k"] = round(oi_theta * spot_val / 1000, 1)
            sv["oi_wtd_vega_usd_k"]     = round(oi_vega  * spot_val / 1000, 1)

    # Breakdown by TTE bucket from portfolio_aggregate
    port = _read_parquet(BATCH / "portfolio_aggregate.parquet")
    if not port.empty and "hour" in port.columns:
        latest_port = port[port["hour"] == port["hour"].max()]
        if "gamma_sum" in latest_port.columns and "tte_bucket" in latest_port.columns:
            largest = latest_port.loc[latest_port["gamma_sum"].abs().idxmax()]
            sv["largest_gamma_tte_bucket"] = str(largest["tte_bucket"])
        if "oi_notional" in latest_port.columns:
            sv["total_oi_notional"] = round(float(latest_port["oi_notional"].sum()), 0)
        if "tte_bucket" in latest_port.columns:
            breakdown = []
            for _, row in latest_port.iterrows():
                breakdown.append({
                    "bucket":       str(row.get("tte_bucket", "?")),
                    "delta_sum":    round(float(row.get("delta_sum", 0) or 0), 2),
                    "gamma_sum":    round(float(row.get("gamma_sum", 0) or 0), 6),
                    "theta_sum":    round(float(row.get("theta_sum", 0) or 0), 2),
                    "vega_sum":     round(float(row.get("vega_sum",  0) or 0), 2),
                    "oi_notional_m": round(float(row.get("oi_notional", 0) or 0) / 1e6, 1),
                    "contracts":    int(row.get("contracts", 0) or 0),
                })
            sv["book_by_tte_bucket"] = breakdown

    conc = _read_parquet(BATCH / "concentration.parquet")
    if not conc.empty and "strike" in conc.columns:
        top3c = conc.groupby("strike").sum(numeric_only=True)
        if "open_interest" in top3c.columns:
            sv["top3_concentration_strikes"] = top3c["open_interest"].nlargest(3).index.tolist()

    # ── Signals ──────────────────────────────────────────────────────────
    top_sig = _read_parquet(SNAPSHOT / "top_signals.parquet")
    if not top_sig.empty and "gated_signal" in top_sig.columns:
        sv["signal_count_buy_vol"]  = int((top_sig["gated_signal"] == "buy_vol").sum())
        sv["signal_count_sell_vol"] = int((top_sig["gated_signal"] == "sell_vol").sum())
        sv["signal_count_blocked"]  = int((top_sig["gated_signal"] == "blocked").sum())

        # Bug fix: sort by |raw_market_signal| so sell_vol (negative) surface too
        if "raw_market_signal" in top_sig.columns:
            top_sig = top_sig.copy()
            top_sig["_abs_score"] = top_sig["raw_market_signal"].abs()
            top5 = top_sig.nlargest(5, "_abs_score")
        else:
            top5 = top_sig.head(5)
        cols = ["instrument", "gated_signal", "raw_market_signal", "iv_edge_vs_rv", "surface_reliability"]
        cols = [c for c in cols if c in top5.columns]
        sv["top5_signals"] = top5[cols].round(3).to_dict(orient="records")

    print(json.dumps(sv, indent=2, default=str))


# ══════════════════════════════════════════════════════════════════════════
# SUBCOMMAND: grade
# ══════════════════════════════════════════════════════════════════════════

def cmd_grade() -> None:
    """Grade yesterday's prediction. Update signal_stats.json. Output JSON."""

    log_path = LOGS / f"{YESTERDAY}.json"
    if not log_path.exists():
        print(json.dumps({"error": f"No log found for {YESTERDAY}", "grade_skipped": True}))
        return

    log = json.loads(log_path.read_text())
    grading = log.get("grading", {})

    # Already graded?
    if grading.get("score_0_to_5") is not None:
        print(json.dumps({"already_graded": True, "score": grading["score_0_to_5"]}))
        return

    # We can't call StackIQ from Python — output instructions for Claude to do it
    # and provide the grading framework
    pred = log.get("prediction_24h", {})
    state = log.get("state_vector", {})

    output = {
        "date":             YESTERDAY,
        "grade_needed":     True,
        "spot_at_analysis": state.get("spot"),
        "predicted_range_68_low":  pred.get("range_68pct", [None, None])[0] if isinstance(pred.get("range_68pct"), list) else None,
        "predicted_range_68_high": pred.get("range_68pct", [None, None])[1] if isinstance(pred.get("range_68pct"), list) else None,
        "predicted_range_95_low":  pred.get("range_95pct", [None, None])[0] if isinstance(pred.get("range_95pct"), list) else None,
        "predicted_range_95_high": pred.get("range_95pct", [None, None])[1] if isinstance(pred.get("range_95pct"), list) else None,
        "predicted_direction":     log.get("conviction_score", {}).get("direction"),
        "predicted_central":       pred.get("central_estimate_24h"),
        "primary_scenario":        pred.get("primary_scenario"),
        "primary_scenario_trigger":log.get("scenario_tree", [{}])[0].get("trigger") if log.get("scenario_tree") else None,
        "predicted_vol_direction": pred.get("vol_direction_24h"),
        "tier1_levels":            [l for l in log.get("key_levels", []) if l.get("tier") == 1],
        "grading_criteria": {
            "direction_correct":            "1.0 — predicted direction vs actual Δprice sign",
            "in_68_range":                  "1.0 — actual close within predicted 68% range",
            "in_95_range_fallback":         "0.5 — fallback if missed 68%",
            "primary_scenario_realized":    "1.0 — trigger + target materially observed",
            "key_level_behaved_as_stated":  "1.0 — Tier-1 level held or broke as predicted",
            "vol_direction_correct":        "0.5 — IV expanded/contracted as predicted",
        },
        "instruction": (
            "Fetch actual BTC close for this date via StackIQ get_price. "
            "Score each criterion. Patch logs/<date>.json grading block. "
            "Update accuracy/signal_stats.json for active signals."
        ),
        # ── Signal stats scaffolding ──────────────────────────────────
        "active_signals_yesterday": log.get("signal_matrix", []),
        "signal_stats_path":        str(SIGNAL_STATS),
    }

    # ── Running accuracy from existing logs ──────────────────────────────
    scores_7d  = []
    scores_30d = []
    for i in range(1, 31):
        d = (date.today() - timedelta(days=i)).isoformat()
        p = LOGS / f"{d}.json"
        if p.exists():
            g = json.loads(p.read_text()).get("grading", {})
            sc = g.get("score_0_to_5")
            if sc is not None:
                scores_30d.append(sc)
                if i <= 7:
                    scores_7d.append(sc)

    def _direction_acc(scores_list: list) -> float | None:
        # We store direction_correct in grading block
        correct = []
        for i in range(1, len(scores_list) + 2):
            d = (date.today() - timedelta(days=i)).isoformat()
            p = LOGS / f"{d}.json"
            if p.exists():
                g = json.loads(p.read_text()).get("grading", {})
                if g.get("direction_correct") is not None:
                    correct.append(int(g["direction_correct"]))
        return round(sum(correct) / len(correct), 3) if correct else None

    output["running_stats"] = {
        "7d_direction_accuracy":  _direction_acc(scores_7d),
        "30d_direction_accuracy": _direction_acc(scores_30d),
        "7d_avg_score":           round(sum(scores_7d) / len(scores_7d), 2) if scores_7d else None,
        "30d_avg_score":          round(sum(scores_30d) / len(scores_30d), 2) if scores_30d else None,
        "recalibration_active":   (_direction_acc(scores_7d) or 1.0) < 0.50 and len(scores_7d) >= 5,
    }

    print(json.dumps(output, indent=2, default=str))


# ══════════════════════════════════════════════════════════════════════════
# SUBCOMMAND: write-log
# ══════════════════════════════════════════════════════════════════════════

def cmd_write_log(data_str: str) -> None:
    """Write a full daily log JSON to logs/<today>.json."""
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    # Ensure grading block is present with nulls
    if "grading" not in data:
        data["grading"] = {
            "actual_close_24h":          None,
            "direction_correct":         None,
            "in_68_range":               None,
            "in_95_range":               None,
            "primary_scenario_realized": None,
            "key_level_behaved":         None,
            "vol_direction_correct":     None,
            "score_0_to_5":              None,
            "grading_notes":             None,
        }

    data.setdefault("meta", {})["write_timestamp"] = datetime.now(timezone.utc).isoformat()

    out_path = LOGS / f"{TODAY}.json"
    _write_json(out_path, data)

    # Also record which signals were active (for grading tomorrow)
    if "signal_matrix" in data:
        stats = _read_json(SIGNAL_STATS)
        for sig in data["signal_matrix"]:
            name = sig.get("signal")
            if name and name not in stats:
                stats[name] = {
                    "n": 0, "correct": 0, "wrong": 0,
                    "accuracy_30d": sig.get("historical_accuracy_pct", 50) / 100,
                    "weight": sig.get("weight", 0.60),
                }
        _write_json(SIGNAL_STATS, stats)

    print(json.dumps({"written": str(out_path), "date": TODAY}))


# ══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deribit Quant Analyst — data extraction CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("audit",   help="Check S3 + artifact freshness")
    sub.add_parser("extract", help="Extract full state vector from parquets")
    sub.add_parser("grade",   help="Grade yesterday's prediction")

    wl = sub.add_parser("write-log", help="Write today's log JSON")
    wl.add_argument("--data", required=True, help="Full log JSON string")

    args = parser.parse_args()

    if args.cmd == "audit":
        cmd_audit()
    elif args.cmd == "extract":
        cmd_extract()
    elif args.cmd == "grade":
        cmd_grade()
    elif args.cmd == "write-log":
        cmd_write_log(args.data)


if __name__ == "__main__":
    main()
