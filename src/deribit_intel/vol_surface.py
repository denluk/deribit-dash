from __future__ import annotations
import numpy as np
import pandas as pd

def extract_atm_monitor(df: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    tmp = df.copy()
    tmp["atm_rank"] = tmp.groupby(["hour", "tte_bucket", "type"], observed=True)["abs_log_moneyness"].rank(method="first")
    atm = tmp[tmp["atm_rank"] <= top_n].copy()
    return (
        atm.groupby(["hour", "tte_bucket", "type"], observed=True, as_index=False)
           .agg(
               atm_iv=("mark_iv", "median"),
               atm_spread_bps=("spread_bps_mid", "median"),
               atm_oi_notional=("notional_oi_usd", "median"),
               atm_volume_24h_usd=("volume_24h_usd", "median"),
           )
    )

def build_skew_monitor(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df[df["tte_days"].between(0, 180)].copy()
    tmp["mny_bucket"] = pd.cut(tmp["moneyness"], bins=[0, 0.9, 0.97, 1.03, 1.1, 10], labels=["deep_otm", "otm", "atm", "itm", "deep_itm"])
    return (
        tmp.groupby(["hour", "tte_bucket", "type", "mny_bucket"], observed=True, as_index=False)
           .agg(skew_iv=("mark_iv", "median"), contracts=("instrument", "count"))
    )

def build_term_structure(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    return (
        tmp.groupby(["hour", "tte_bucket"], observed=True, as_index=False)
           .agg(
               iv_median=("mark_iv", "median"),
               iv_mean=("mark_iv", "mean"),
               oi_notional=("notional_oi_usd", "sum"),
               contracts=("instrument", "count"),
           )
    )

def realized_vs_implied_tracker(df: pd.DataFrame, windows=(6, 24, 72)) -> pd.DataFrame:
    px = (
        df.groupby("hour", as_index=False)["underlying"]
          .median()
          .sort_values("hour")
          .copy()
    )
    px["log_ret"] = np.log(px["underlying"]).diff()
    # mark_iv is stored in percentage points (e.g. 55.0), so RV is scaled to the same unit.
    ann = np.sqrt(24 * 365) * 100.0
    for w in windows:
        # Keep short slices visible while avoiding unstable long-window estimates.
        min_periods = 2 if w <= 24 else 12
        rv = px["log_ret"].rolling(w, min_periods=min_periods).std() * ann
        px[f"rv_{w}h"] = rv

    # Robust fallbacks for partial-day datasets.
    if "rv_24h" in px.columns:
        px["rv_24h"] = px["rv_24h"].fillna(px["log_ret"].rolling(3, min_periods=2).std() * ann)
        px["rv_24h"] = px["rv_24h"].ffill().bfill()
    if "rv_72h" in px.columns:
        # 72h should be smoother and not collapse on sparse intraday windows.
        px["rv_72h"] = px["rv_72h"].fillna(px.get("rv_24h"))
        px["rv_72h"] = px["rv_72h"].rolling(3, min_periods=1).mean()

    for w in windows:
        c = f"rv_{w}h"
        if c in px.columns:
            px[c] = px[c].clip(lower=0)
    atm = (
        df.groupby("hour", as_index=False)["mark_iv"]
          .median()
          .rename(columns={"mark_iv": "iv_proxy"})
    )
    out = px.merge(atm, on="hour", how="left")
    for w in windows:
        out[f"vrp_proxy_{w}h"] = out["iv_proxy"] - out[f"rv_{w}h"]
    return out

def event_premium_decomposition(df: pd.DataFrame, near_days: int = 7, far_days: int = 30) -> pd.DataFrame:
    tmp = df.copy()
    near = tmp[tmp["tte_days"].between(0, near_days)].groupby("hour", as_index=False)["mark_iv"].median().rename(columns={"mark_iv": "near_iv"})
    far = tmp[tmp["tte_days"].between(near_days + 1, far_days)].groupby("hour", as_index=False)["mark_iv"].median().rename(columns={"mark_iv": "far_iv"})
    out = near.merge(far, on="hour", how="outer").sort_values("hour")
    out["event_premium_proxy"] = out["near_iv"] - out["far_iv"]
    return out

def vol_regime_labeling(rv_iv: pd.DataFrame) -> pd.DataFrame:
    out = rv_iv.copy()
    iv_z = (out["iv_proxy"] - out["iv_proxy"].rolling(72, min_periods=24).mean()) / out["iv_proxy"].rolling(72, min_periods=24).std()
    rv_z = (out["rv_24h"] - out["rv_24h"].rolling(72, min_periods=24).mean()) / out["rv_24h"].rolling(72, min_periods=24).std()
    out["iv_z"] = iv_z
    out["rv_z"] = rv_z
    conditions = [
        (iv_z > 1.0) & (rv_z <= 0.5),
        (iv_z < -1.0) & (rv_z < -0.5),
        (rv_z > 1.0) & (iv_z <= 0.5),
        (iv_z > 1.0) & (rv_z > 1.0),
    ]
    labels = ["rich_calm", "cheap_calm", "realized_stress", "joint_stress"]
    out["vol_regime"] = np.select(conditions, labels, default="neutral")
    return out
