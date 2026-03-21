from __future__ import annotations
import numpy as np
import pandas as pd

def score_contract_surface_reliability(df: pd.DataFrame, repriced: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(
        repriced[["timestamp", "instrument", "fit_confidence", "fit_distance"]],
        on=["timestamp", "instrument"],
        how="left",
    )
    out["liquidity_reliability"] = (
        np.log1p(out["open_interest"].fillna(0)) +
        np.log1p(out["volume_24h"].fillna(0)) -
        np.log1p(out["spread_bps_mid"].clip(lower=0).fillna(1000))
    )
    lr = out["liquidity_reliability"]
    lr = (lr - lr.min()) / ((lr.max() - lr.min()) if (lr.max() - lr.min()) > 0 else 1.0)
    out["liquidity_reliability"] = lr
    out["surface_reliability"] = 0.65 * out["fit_confidence"].fillna(0) + 0.35 * out["liquidity_reliability"].fillna(0)
    out["reliability_flag"] = np.select(
        [out["surface_reliability"] >= 0.75, out["surface_reliability"] >= 0.45],
        ["high", "medium"],
        default="low"
    )
    return out

def build_surface_uncertainty_report(reliability_df: pd.DataFrame) -> pd.DataFrame:
    return (
        reliability_df.groupby(["hour", "type"], as_index=False)
        .agg(
            avg_surface_reliability=("surface_reliability", "mean"),
            low_reliability_share=("surface_reliability", lambda s: float((s < 0.45).mean())),
            contracts=("instrument", "count"),
        )
    )
