from __future__ import annotations
import numpy as np
import pandas as pd

def _approx_delta_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "delta" in out.columns and out["delta"].notna().any():
        abs_delta = out["delta"].abs()
        out["delta_bucket"] = pd.cut(
            abs_delta,
            bins=[-0.001, 0.10, 0.25, 0.40, 0.60, 0.80, 1.01],
            labels=["05d", "15d", "30d", "50d", "70d", "90d"]
        )
    else:
        # fallback via moneyness proxy
        m = np.abs(np.log(out["strike"] / out["underlying"]))
        out["delta_bucket"] = pd.cut(
            m,
            bins=[-1e-12, 0.02, 0.05, 0.10, 0.20, 0.35, 10],
            labels=["50d", "30d", "15d", "10d", "05d", "tail"]
        )
    return out

def build_delta_tenor_surface(df: pd.DataFrame) -> pd.DataFrame:
    tmp = _approx_delta_bucket(df)
    tmp = tmp[tmp["tte_days"].between(0, 365)].copy()
    tmp["tenor_days_bucket"] = pd.cut(
        tmp["tte_days"],
        bins=[-1, 2, 7, 14, 30, 60, 90, 180, 365],
        labels=["2d", "7d", "14d", "30d", "60d", "90d", "180d", "365d"]
    )
    surf = (
        tmp.groupby(["hour", "type", "delta_bucket", "tenor_days_bucket"], observed=True, as_index=False)
           .agg(
               mark_iv=("mark_iv", "median"),
               spread_bps=("spread_bps_mid", "median"),
               oi_notional=("notional_oi_usd", "sum"),
               contracts=("instrument", "count"),
           )
    )
    return surf

def build_surface_features(surface: pd.DataFrame) -> pd.DataFrame:
    out = surface.copy()
    out["surface_key"] = (
        out["type"].astype(str) + "_" +
        out["delta_bucket"].astype(str) + "_" +
        out["tenor_days_bucket"].astype(str)
    )
    return out

def build_surface_pivots(surface: pd.DataFrame) -> dict[str, pd.DataFrame]:
    pivots = {}
    for opt_type in sorted(surface["type"].dropna().unique()):
        s = surface[surface["type"] == opt_type]
        pivots[opt_type] = s.pivot_table(
            index=["hour", "delta_bucket"],
            columns="tenor_days_bucket",
            values="mark_iv",
            aggfunc="median",
        )
    return pivots
