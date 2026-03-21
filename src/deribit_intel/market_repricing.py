from __future__ import annotations
import math
import numpy as np
import pandas as pd
from deribit_intel.surface_engine import lookup_surface_iv

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def black_scholes_local(spot: float, strike: float, t: float, vol: float, opt_type: str, r: float = 0.0) -> dict:
    if spot <= 0 or strike <= 0 or t <= 0 or vol <= 0:
        intrinsic = max(spot - strike, 0.0) if opt_type == "call" else max(strike - spot, 0.0)
        return {"price": intrinsic, "delta": np.nan, "gamma": np.nan, "vega": np.nan, "theta": np.nan}
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    nd1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    if opt_type == "call":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
    gamma = nd1 / (spot * vol * math.sqrt(t))
    vega = spot * nd1 * math.sqrt(t)
    theta = -(spot * nd1 * vol) / (2.0 * math.sqrt(t))
    return {"price": price, "delta": delta, "gamma": gamma, "vega": vega, "theta": theta}

def reprice_from_surface(df: pd.DataFrame, surface_grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        hour = r["hour"]
        opt_type = r["type"]
        tenor_days = max(float(r["tte_days"]), 1e-6)
        lm = float(np.log(r["strike"] / r["underlying"]))
        lookup = lookup_surface_iv(surface_grid, hour, opt_type, tenor_days, lm)
        iv = lookup["fitted_iv"]
        greeks = black_scholes_local(
            spot=float(r["underlying"]),
            strike=float(r["strike"]),
            t=tenor_days / 365.0,
            vol=float(iv) if pd.notna(iv) else 0.0,
            opt_type=opt_type,
            r=0.0,
        )
        rows.append({
            "timestamp": r["timestamp"],
            "instrument": r["instrument"],
            "hour": hour,
            "surface_price": greeks["price"],
            "local_delta": greeks["delta"],
            "local_gamma": greeks["gamma"],
            "local_vega": greeks["vega"],
            "surface_conditional_theta": greeks["theta"],
            "surface_iv": iv,
            "fit_confidence": lookup["fit_confidence"],
            "fit_distance": lookup["fit_distance"],
            "market_mid": r.get("mid", np.nan),
            "market_bid": r.get("bid", np.nan),
            "market_ask": r.get("ask", np.nan),
            "surface_minus_mid": greeks["price"] - r.get("mid", np.nan),
        })
    return pd.DataFrame(rows)

def build_market_relative_value(df: pd.DataFrame, repriced: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(
        repriced[["timestamp", "instrument", "surface_price", "surface_iv", "fit_confidence", "surface_minus_mid"]],
        on=["timestamp", "instrument"],
        how="left",
    )
    grp = out.groupby(["hour", "tte_bucket", "type"], observed=True)["mark_iv"]
    out["local_surface_zscore"] = (out["mark_iv"] - grp.transform("median")) / grp.transform("std")
    out["market_relative_score"] = (
        -0.4 * out["local_surface_zscore"].fillna(0) +
        0.8 * out["surface_minus_mid"].fillna(0) *
        out["fit_confidence"].fillna(0)
    )
    return out
