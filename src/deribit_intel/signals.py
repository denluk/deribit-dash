from __future__ import annotations
import numpy as np
import pandas as pd

def build_contract_signal_table(df: pd.DataFrame,
                                rv_forecast: pd.DataFrame,
                                execution_flags: pd.DataFrame) -> pd.DataFrame:
    rv = rv_forecast[["hour", "har_rv_forecast_24h", "regime_rv_forecast_24h"]].copy()
    ex = execution_flags[["timestamp", "instrument", "tradable_flag"]].copy()
    tmp = df.merge(rv, on="hour", how="left")
    tmp = tmp.merge(ex, on=["timestamp", "instrument"], how="left", suffixes=("", "_flag"))
    grp = tmp.groupby(["hour", "tte_bucket", "type"], observed=True)["mark_iv"]
    tmp["surface_zscore"] = (tmp["mark_iv"] - grp.transform("median")) / grp.transform("std")
    tmp["iv_edge_vs_rv"] = tmp["regime_rv_forecast_24h"] - tmp["mark_iv"]
    tmp["cost_proxy"] = ((tmp["ask"] - tmp["bid"]).clip(lower=0) / 2.0).fillna(0) + tmp["mark_price"].fillna(0) * 0.0005
    tmp["raw_signal_score"] = (
        1.8 * tmp["iv_edge_vs_rv"].fillna(0) -
        0.8 * tmp["cost_proxy"].fillna(0) -
        0.4 * tmp["spread_bps_mid"].fillna(250)/250 +
        0.35 * np.log1p(tmp["open_interest"].fillna(0)) +
        0.25 * np.log1p(tmp["volume_24h"].fillna(0)) -
        0.25 * tmp["surface_zscore"].fillna(0).clip(lower=0)
    )
    tmp["trade_side"] = np.select(
        [tmp["raw_signal_score"] > 0.5, tmp["raw_signal_score"] < -0.5],
        ["buy_vol", "sell_vol"],
        default="hold",
    )
    tmp["gated_signal"] = np.where(tmp["tradable_flag"].fillna(0) == 1, tmp["trade_side"], "blocked")
    return tmp

def build_top_signals(signal_df: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    s = signal_df[signal_df["gated_signal"].isin(["buy_vol", "sell_vol"])].copy()
    s["abs_score"] = s["raw_signal_score"].abs()
    cols = [
        "timestamp", "instrument", "type", "expiry", "strike", "underlying",
        "mark_iv", "regime_rv_forecast_24h", "iv_edge_vs_rv", "spread_bps_mid",
        "open_interest", "volume_24h", "surface_zscore", "raw_signal_score", "gated_signal"
    ]
    return s.sort_values("abs_score", ascending=False)[cols].head(top_n)
