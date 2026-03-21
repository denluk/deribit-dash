from __future__ import annotations
import pandas as pd

def build_surface_state(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["hour", "tte_bucket", "type"], as_index=False)
          .agg(
              mark_iv_median=("mark_iv", "median"),
              spread_bps_median=("spread_bps_mid", "median"),
              oi_notional_median=("notional_oi_usd", "median"),
              volume_24h_usd_median=("volume_24h_usd", "median"),
              contracts=("instrument", "count"),
          )
    )

def build_greek_state(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("hour", as_index=False)
          .agg(
              net_delta=("delta", "sum"),
              net_gamma=("gamma", "sum"),
              net_theta=("theta", "sum"),
              net_vega=("vega", "sum"),
              total_oi=("open_interest", "sum"),
              total_notional_oi=("notional_oi_usd", "sum"),
          )
          .sort_values("hour")
    )

def build_strike_pressure(df: pd.DataFrame, strike_bucket_size: int = 5000) -> pd.DataFrame:
    tmp = df.copy()
    tmp["strike_bucket"] = (tmp["strike"] // strike_bucket_size) * strike_bucket_size
    return (
        tmp.groupby(["hour", "strike_bucket"], as_index=False)
           .agg(
               oi_notional=("notional_oi_usd", "sum"),
               volume_24h_usd=("volume_24h_usd", "sum"),
               gamma_sum=("gamma", "sum"),
               delta_sum=("delta", "sum"),
               vega_sum=("vega", "sum"),
           )
    )

def build_regime_flags(surface_state: pd.DataFrame, greek_state: pd.DataFrame) -> pd.DataFrame:
    merged = greek_state.copy()
    merged["abs_net_gamma_z"] = (merged["net_gamma"] - merged["net_gamma"].rolling(48, min_periods=12).mean()) /                                 merged["net_gamma"].rolling(48, min_periods=12).std()
    merged["abs_net_vega_z"] = (merged["net_vega"] - merged["net_vega"].rolling(48, min_periods=12).mean()) /                                merged["net_vega"].rolling(48, min_periods=12).std()
    merged["stress_flag"] = ((merged["abs_net_gamma_z"].abs() > 2.5) | (merged["abs_net_vega_z"].abs() > 2.5)).astype(int)
    return merged
