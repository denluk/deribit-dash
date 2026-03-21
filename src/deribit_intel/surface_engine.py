from __future__ import annotations
import numpy as np
import pandas as pd

def _prepare_surface_coords(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out[out["mark_iv"].notna() & out["underlying"].notna() & out["strike"].notna() & out["tte_days"].notna()].copy()
    out["log_moneyness"] = np.log(out["strike"] / out["underlying"])
    out["abs_delta"] = out["delta"].abs() if "delta" in out.columns else np.nan
    out["tenor_days"] = out["tte_days"].clip(lower=0.001)
    out["liq_score"] = (
        np.log1p(out["open_interest"].fillna(0)) +
        np.log1p(out["volume_24h"].fillna(0)) -
        np.log1p(out["spread_bps_mid"].clip(lower=0).fillna(1000))
    )
    return out

def build_observed_surface_nodes(df: pd.DataFrame) -> pd.DataFrame:
    tmp = _prepare_surface_coords(df)
    return (
        tmp.groupby(["hour", "type", "expiry", "strike"], as_index=False)
           .agg(
               mark_iv=("mark_iv", "median"),
               mid=("mid", "median"),
               bid=("bid", "median"),
               ask=("ask", "median"),
               spread_bps_mid=("spread_bps_mid", "median"),
               underlying=("underlying", "median"),
               log_moneyness=("log_moneyness", "median"),
               tenor_days=("tenor_days", "median"),
               delta=("delta", "median"),
               gamma=("gamma", "median"),
               theta=("theta", "median"),
               vega=("vega", "median"),
               open_interest=("open_interest", "median"),
               volume_24h=("volume_24h", "median"),
               liq_score=("liq_score", "median"),
               contracts=("instrument", "count"),
           )
    )

def build_surface_grid(df: pd.DataFrame,
                       log_m_grid=None,
                       tenor_grid=(2, 7, 14, 30, 60, 90, 180, 365)) -> pd.DataFrame:
    if log_m_grid is None:
        log_m_grid = np.round(np.linspace(-0.35, 0.35, 15), 3)
    nodes = build_observed_surface_nodes(df)
    rows = []
    for (hour, opt_type), g in nodes.groupby(["hour", "type"], observed=True):
        if len(g) < 5:
            continue
        for tenor in tenor_grid:
            local = g.iloc[(g["tenor_days"] - tenor).abs().argsort()[: max(5, min(20, len(g)))]].copy()
            tenor_penalty = 1.0 / (1.0 + (local["tenor_days"] - tenor).abs())
            liq = np.exp(local["liq_score"].fillna(local["liq_score"].median()).clip(-5, 5))
            for lm in log_m_grid:
                strike_penalty = 1.0 / (1.0 + (local["log_moneyness"] - lm).abs() * 25.0)
                w = tenor_penalty * strike_penalty * liq
                if np.nansum(w) <= 0:
                    continue
                iv = np.average(local["mark_iv"], weights=w)
                fit_distance = np.average(np.abs(local["log_moneyness"] - lm) + np.abs(local["tenor_days"] - tenor)/30.0, weights=w)
                support = float(np.nansum(w > np.nanpercentile(w, 50)))
                confidence = float(np.clip(1.0 / (1.0 + fit_distance), 0, 1) * np.clip(support / 10.0, 0, 1))
                rows.append({
                    "hour": hour,
                    "type": opt_type,
                    "tenor_days": float(tenor),
                    "log_moneyness": float(lm),
                    "fitted_iv": float(iv),
                    "fit_distance": float(fit_distance),
                    "support_score": float(support),
                    "fit_confidence": confidence,
                })
    return pd.DataFrame(rows)

def build_surface_quality_report(surface_grid: pd.DataFrame) -> pd.DataFrame:
    if surface_grid.empty:
        return pd.DataFrame(columns=["hour", "type", "avg_fit_confidence", "max_fit_distance", "nodes"])
    return (
        surface_grid.groupby(["hour", "type"], as_index=False)
        .agg(
            avg_fit_confidence=("fit_confidence", "mean"),
            min_fit_confidence=("fit_confidence", "min"),
            max_fit_distance=("fit_distance", "max"),
            nodes=("fitted_iv", "count"),
        )
    )

def lookup_surface_iv(surface_grid: pd.DataFrame, hour, opt_type: str, tenor_days: float, log_moneyness: float) -> dict:
    s = surface_grid[(surface_grid["hour"] == hour) & (surface_grid["type"] == opt_type)].copy()
    if s.empty:
        return {"fitted_iv": np.nan, "fit_confidence": 0.0, "fit_distance": np.inf}
    dist = np.abs(s["tenor_days"] - tenor_days) / 30.0 + np.abs(s["log_moneyness"] - log_moneyness) * 8.0
    idx = dist.idxmin()
    row = s.loc[idx]
    return {
        "fitted_iv": float(row["fitted_iv"]),
        "fit_confidence": float(row["fit_confidence"]),
        "fit_distance": float(row["fit_distance"]),
    }
