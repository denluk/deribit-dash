from __future__ import annotations
import numpy as np
import pandas as pd

def spread_slippage_guardrails(df: pd.DataFrame,
                               max_spread_bps: float = 250.0,
                               min_oi: float = 10.0,
                               min_vol24h: float = 1.0) -> pd.DataFrame:
    out = df.copy()
    out["tradable_flag"] = (
        (out["spread_bps_mid"].fillna(np.inf) <= max_spread_bps) &
        (out["open_interest"].fillna(0) >= min_oi) &
        (out["volume_24h"].fillna(0) >= min_vol24h)
    ).astype(int)
    return out

def max_short_gamma_limits(position_state: pd.DataFrame, gamma_limit: float) -> pd.DataFrame:
    out = position_state.copy()
    out["short_gamma_breach"] = (out["net_gamma"] < -abs(gamma_limit)).astype(int)
    return out

def stress_test_book(df: pd.DataFrame, spot_gap=(-0.20, -0.10, 0.10, 0.20), iv_shock=(-0.20, -0.10, 0.10, 0.20)) -> pd.DataFrame:
    latest = df.sort_values("hour").groupby("instrument").tail(1).copy()
    if latest.empty:
        return pd.DataFrame(columns=["spot_gap", "iv_shock", "stress_pnl"])

    s0 = float(latest["underlying"].median())
    rows = []
    for ds in spot_gap:
        dS = s0 * ds
        for div in iv_shock:
            stress_pnl = (
                latest["delta"].fillna(0).sum() * dS +
                0.5 * latest["gamma"].fillna(0).sum() * (dS ** 2) +
                latest["vega"].fillna(0).sum() * div
            )
            rows.append({"spot_gap": ds, "iv_shock": div, "stress_pnl": stress_pnl})
    return pd.DataFrame(rows)

def liquidity_weighted_sizing(df: pd.DataFrame, base_risk_budget: float = 1.0) -> pd.DataFrame:
    out = df.copy()
    liquidity_score = (
        np.log1p(out["open_interest"].fillna(0)) +
        np.log1p(out["volume_24h"].fillna(0)) -
        np.log1p(out["spread_bps_mid"].clip(lower=0).fillna(1000))
    )
    out["liquidity_score"] = liquidity_score
    score = liquidity_score - liquidity_score.min()
    denom = score.max() if np.isfinite(score.max()) and score.max() > 0 else 1.0
    out["size_multiplier"] = base_risk_budget * (score / denom)
    return out

def aggregate_portfolio_limits(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["hour", "currency", "tte_bucket"], observed=True, as_index=False)
          .agg(
              delta_sum=("delta", "sum"),
              gamma_sum=("gamma", "sum"),
              theta_sum=("theta", "sum"),
              vega_sum=("vega", "sum"),
              oi_notional=("notional_oi_usd", "sum"),
              contracts=("instrument", "count"),
          )
    )
