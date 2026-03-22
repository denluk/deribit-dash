from __future__ import annotations
import numpy as np
import pandas as pd

def build_market_first_signal_table(df: pd.DataFrame,
                                    rv_forecast: pd.DataFrame,
                                    execution_flags: pd.DataFrame,
                                    repriced: pd.DataFrame,
                                    reliability: pd.DataFrame) -> pd.DataFrame:
    rv = rv_forecast[["hour", "regime_rv_forecast_24h"]].copy()
    ex = execution_flags[["timestamp", "instrument", "tradable_flag"]].copy()
    rp = repriced[["timestamp", "instrument", "surface_price", "surface_iv", "fit_confidence", "surface_minus_mid"]].copy()
    rel = reliability[["timestamp", "instrument", "surface_reliability", "reliability_flag"]].copy()

    out = df.merge(rv, on="hour", how="left")
    out = out.merge(ex, on=["timestamp", "instrument"], how="left")
    out = out.merge(rp, on=["timestamp", "instrument"], how="left")
    out = out.merge(rel, on=["timestamp", "instrument"], how="left")

    grp = out.groupby(["hour", "tte_bucket", "type"], observed=True)["mark_iv"]
    out["local_surface_zscore"] = (out["mark_iv"] - grp.transform("median")) / grp.transform("std")
    # Both in decimal fraction: regime_rv is already decimal (0.35), mark_iv is percentage → /100
    out["iv_edge_vs_rv"] = out["regime_rv_forecast_24h"] - out["mark_iv"] / 100.0
    out["cost_proxy"] = ((out["ask"] - out["bid"]).clip(lower=0) / 2.0).fillna(0) + out["mark_price"].fillna(0) * 0.0005

    out["raw_market_signal"] = (
        1.4 * out["iv_edge_vs_rv"].fillna(0) +
        0.7 * out["surface_minus_mid"].fillna(0) * out["fit_confidence"].fillna(0) -
        0.9 * out["cost_proxy"].fillna(0) -
        0.3 * out["spread_bps_mid"].fillna(250)/250 -
        0.2 * out["local_surface_zscore"].fillna(0).clip(lower=0)
    ) * out["surface_reliability"].fillna(0)

    out["trade_side"] = np.select(
        [out["raw_market_signal"] > 0.35, out["raw_market_signal"] < -0.35],
        ["buy_vol", "sell_vol"],
        default="hold",
    )
    out["gated_signal"] = np.where(
        (out["tradable_flag"].fillna(0) == 1) & (out["surface_reliability"].fillna(0) >= 0.45),
        out["trade_side"],
        "blocked"
    )
    return out

def build_market_top_signals(signal_df: pd.DataFrame, top_n: int = 100) -> pd.DataFrame:
    s = signal_df[signal_df["gated_signal"].isin(["buy_vol", "sell_vol"])].copy()
    s["abs_score"] = s["raw_market_signal"].abs()
    cols = [
        "timestamp", "instrument", "type", "expiry", "strike", "underlying",
        "mark_iv", "surface_iv", "regime_rv_forecast_24h", "surface_minus_mid",
        "iv_edge_vs_rv", "spread_bps_mid", "open_interest", "volume_24h",
        "surface_reliability", "reliability_flag", "raw_market_signal", "gated_signal"
    ]
    return s.sort_values("abs_score", ascending=False)[cols].head(top_n)
