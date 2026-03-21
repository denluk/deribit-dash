from __future__ import annotations
import numpy as np
import pandas as pd

def build_position_state(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates the chain into a position-state table at hourly resolution.

    Expected inputs:
    - timestamp/hour
    - instrument, expiry_dt, strike, type
    - underlying, mark_price, mark_iv
    - delta, gamma, theta, vega
    - open_interest, volume_24h

    Core outputs:
    - net_delta, net_gamma, net_theta, net_vega
    - oi-weighted greek densities
    - expiry sensitivity by TTE bucket
    - convexity concentration measures
    """
    out = (
        df.groupby("hour", as_index=False)
          .agg(
              net_delta=("delta", "sum"),
              net_gamma=("gamma", "sum"),
              net_theta=("theta", "sum"),
              net_vega=("vega", "sum"),
              gross_gamma=("gamma", lambda s: np.abs(s).sum()),
              gross_vega=("vega", lambda s: np.abs(s).sum()),
              total_oi=("open_interest", "sum"),
              total_notional_oi=("notional_oi_usd", "sum"),
          )
          .sort_values("hour")
    )
    out["gamma_density"] = np.where(out["total_oi"] > 0, out["net_gamma"] / out["total_oi"], np.nan)
    out["vega_density"] = np.where(out["total_oi"] > 0, out["net_vega"] / out["total_oi"], np.nan)
    out["convexity_ratio"] = np.where(out["gross_gamma"] > 0, out["net_gamma"] / out["gross_gamma"], np.nan)
    return out

def build_expiry_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["hour", "tte_bucket"], observed=True, as_index=False)
          .agg(
              delta_sum=("delta", "sum"),
              gamma_sum=("gamma", "sum"),
              theta_sum=("theta", "sum"),
              vega_sum=("vega", "sum"),
              oi_notional=("notional_oi_usd", "sum"),
          )
    )

def build_strike_convexity_map(df: pd.DataFrame, strike_bucket_size: int = 5000) -> pd.DataFrame:
    tmp = df.copy()
    tmp["strike_bucket"] = (tmp["strike"] // strike_bucket_size) * strike_bucket_size
    return (
        tmp.groupby(["hour", "strike_bucket"], as_index=False)
           .agg(
               gamma_sum=("gamma", "sum"),
               abs_gamma_sum=("gamma", lambda s: np.abs(s).sum()),
               vega_sum=("vega", "sum"),
               theta_sum=("theta", "sum"),
               oi_notional=("notional_oi_usd", "sum"),
           )
    )

def scenario_shock_grid(df: pd.DataFrame, spot_shocks=(-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15),
                        iv_shocks=(-0.10, -0.05, 0.0, 0.05, 0.10),
                        dt_days=(0, 1, 3)) -> pd.DataFrame:
    """
    First-order/second-order scenario engine.

    Approximate PnL:
        dP ~= delta*dS + 0.5*gamma*dS^2 + vega*dIV + theta*dT

    Notes:
    - This is a monitoring grid, not a full repricer.
    - For production use, replace with full Black-style or local-vol repricing.
    """
    latest = df.sort_values("hour").groupby("instrument").tail(1).copy()
    if latest.empty:
        return pd.DataFrame(columns=["spot_shock", "iv_shock", "dt_days", "approx_pnl"])

    s0 = float(latest["underlying"].median())
    rows = []
    for ds in spot_shocks:
        dS = s0 * ds
        for div in iv_shocks:
            for dt in dt_days:
                pnl = (
                    latest["delta"].fillna(0).sum() * dS +
                    0.5 * latest["gamma"].fillna(0).sum() * (dS ** 2) +
                    latest["vega"].fillna(0).sum() * div +
                    latest["theta"].fillna(0).sum() * dt
                )
                rows.append({
                    "spot_shock": ds,
                    "iv_shock": div,
                    "dt_days": dt,
                    "approx_pnl": pnl
                })
    return pd.DataFrame(rows)

def add_higher_order_placeholders(df: pd.DataFrame) -> pd.DataFrame:
    """
    Placeholder for charm/vanna awareness when either:
    1) raw charm/vanna are available from venue/API, or
    2) they are derived from your own pricing engine.

    Current behavior:
    - preserves schema hooks only
    """
    out = df.copy()
    if "charm" not in out.columns:
        out["charm"] = np.nan
    if "vanna" not in out.columns:
        out["vanna"] = np.nan
    return out
