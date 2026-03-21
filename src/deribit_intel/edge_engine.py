from __future__ import annotations
import numpy as np
import pandas as pd

def estimate_costs(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["half_spread_cost"] = (out["ask"] - out["bid"]).clip(lower=0) / 2.0
    out["fee_proxy"] = out["mark_price"].fillna(0) * 0.0005
    out["total_cost_proxy"] = out["half_spread_cost"].fillna(0) + out["fee_proxy"].fillna(0)
    return out

def variance_premium_monitor(rv_iv: pd.DataFrame) -> pd.DataFrame:
    out = rv_iv.copy()
    for c in [x for x in out.columns if x.startswith("rv_")]:
        suffix = c.replace("rv_", "")
        out[f"variance_premium_{suffix}"] = (out["iv_proxy"] ** 2) - (out[c] ** 2)
    return out

def conditional_rv_forecast(rv_iv: pd.DataFrame) -> pd.DataFrame:
    out = rv_iv.copy()
    out["rv_forecast_24h"] = (
        0.50 * out["rv_24h"].fillna(method="ffill") +
        0.30 * out["rv_72h"].fillna(method="ffill") +
        0.20 * out["log_ret"].abs().rolling(12).mean() * np.sqrt(24 * 365)
    )
    return out

def jump_premium_estimation(rv_iv: pd.DataFrame, event_premium: pd.DataFrame) -> pd.DataFrame:
    out = rv_iv.merge(event_premium[["hour", "event_premium_proxy"]], on="hour", how="left")
    out["jump_premium_proxy"] = out["event_premium_proxy"].fillna(0) + (out["iv_proxy"] - out["rv_forecast_24h"].fillna(out["rv_24h"]))
    return out

def surface_relative_scoring(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    grp = tmp.groupby(["hour", "tte_bucket", "type"], observed=True)["mark_iv"]
    tmp["surface_zscore"] = (tmp["mark_iv"] - grp.transform("median")) / grp.transform("std")
    tmp["cheap_rich_flag"] = np.select(
        [tmp["surface_zscore"] < -1.0, tmp["surface_zscore"] > 1.0],
        ["cheap", "rich"],
        default="fair",
    )
    return tmp

def expected_value_proxy(df: pd.DataFrame, rv_iv: pd.DataFrame) -> pd.DataFrame:
    costs = estimate_costs(df)
    surf = surface_relative_scoring(costs)
    iv_hour = rv_iv[["hour", "iv_proxy", "rv_forecast_24h"]].copy()
    out = surf.merge(iv_hour, on="hour", how="left")
    out["edge_vol_diff"] = out["rv_forecast_24h"] - out["mark_iv"]
    out["ev_proxy"] = out["edge_vol_diff"].fillna(0) - out["total_cost_proxy"].fillna(0)
    return out
