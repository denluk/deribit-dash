from __future__ import annotations
import pandas as pd

def aggregate_book(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["hour", "currency", "type", "tte_bucket"], observed=True, as_index=False)
          .agg(
              net_delta=("delta", "sum"),
              net_gamma=("gamma", "sum"),
              net_theta=("theta", "sum"),
              net_vega=("vega", "sum"),
              oi_notional=("notional_oi_usd", "sum"),
          )
    )

def concentration_report(df: pd.DataFrame) -> pd.DataFrame:
    total = df.groupby("hour", as_index=False)["notional_oi_usd"].sum().rename(columns={"notional_oi_usd": "total_notional"})
    by_expiry = df.groupby(["hour", "expiry"], as_index=False)["notional_oi_usd"].sum()
    out = by_expiry.merge(total, on="hour", how="left")
    out["expiry_concentration"] = out["notional_oi_usd"] / out["total_notional"]
    return out
