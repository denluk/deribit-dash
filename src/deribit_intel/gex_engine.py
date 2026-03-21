"""
Gamma Exposure (GEX) engine for Deribit options data.

Methodology (adapted from Glassnode / standard dealer-gamma framework):
  GEX = OI × gamma × S²  per strike

  Sign convention (equity-market heuristic, standard baseline):
    Call options → dealers assumed long gamma  → +GEX
    Put options  → dealers assumed short gamma → -GEX

  Net GEX > 0: dealers long gamma  → hedging dampens moves (mean-reverting)
  Net GEX < 0: dealers short gamma → hedging amplifies moves (trending/explosive)

  Key level: "Zero Gamma" strike — cumulative GEX (sorted from OTM inward) changes sign.
  Below zero-gamma → negative GEX regime, above → positive GEX regime.

  Caveat: Crypto participants buy calls speculatively, so this heuristic
  understates negative GEX from net long calls. For flow-based GEX
  (Glassnode proprietary) you need taker-flow data. This module implements
  the standard structural GEX which works well for identifying gamma walls.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _latest_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Return most recent hour snapshot."""
    return df[df["hour"] == df["hour"].max()].copy()


def compute_gex_by_strike(df: pd.DataFrame, spot_override: float | None = None) -> pd.DataFrame:
    """
    GEX profile across strikes for the latest hour snapshot.

    Returns DataFrame with columns:
        strike, gex_call, gex_put, gex_net, oi_call, oi_put, gamma_mid
    """
    snap = _latest_snapshot(df)
    spot = spot_override or snap["underlying"].median()

    grp = snap.groupby(["strike", "type"], observed=True).agg(
        gamma=("gamma", "median"),
        open_interest=("open_interest", "sum"),
    ).reset_index()

    calls = grp[grp["type"] == "call"].copy()
    puts  = grp[grp["type"] == "put"].copy()

    # Dollar gamma per 1% spot move: OI × gamma × S²
    # gamma on Deribit = Δdelta per $1 underlying move
    # × S² converts to delta-dollars per 1% spot move
    calls["gex"] = calls["open_interest"] * calls["gamma"] * spot**2 * 0.01
    puts["gex"]  = puts["open_interest"]  * puts["gamma"]  * spot**2 * 0.01 * -1  # dealers short put gamma

    calls = calls[["strike", "gex", "open_interest", "gamma"]].rename(
        columns={"gex": "gex_call", "open_interest": "oi_call", "gamma": "gamma_call"}
    )
    puts = puts[["strike", "gex", "open_interest", "gamma"]].rename(
        columns={"gex": "gex_put", "open_interest": "oi_put", "gamma": "gamma_put"}
    )

    merged = pd.merge(calls, puts, on="strike", how="outer").fillna(0)
    merged["gex_net"] = merged["gex_call"] + merged["gex_put"]
    merged = merged.sort_values("strike").reset_index(drop=True)
    merged["spot"] = spot
    return merged


def compute_gex_timeseries(df: pd.DataFrame) -> pd.DataFrame:
    """
    Net GEX aggregated per hour. Tracks regime over time.
    """
    df = df.copy()
    spot_by_hour = df.groupby("hour")["underlying"].median().rename("spot")
    df = df.join(spot_by_hour, on="hour")

    df["gex_contract"] = np.where(
        df["type"] == "call",
        df["open_interest"] * df["gamma"] * df["spot"]**2 * 0.01,
        -df["open_interest"] * df["gamma"] * df["spot"]**2 * 0.01,
    )

    ts = (
        df.groupby("hour")["gex_contract"]
        .sum()
        .reset_index()
        .rename(columns={"gex_contract": "net_gex"})
    )
    ts = ts.join(spot_by_hour, on="hour")
    ts["gex_regime"] = np.where(ts["net_gex"] >= 0, "long_gamma", "short_gamma")
    return ts


def compute_gex_by_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """
    GEX bucketed by time-to-expiry. Shows which maturities dominate gamma risk.
    """
    snap = _latest_snapshot(df)
    spot = snap["underlying"].median()

    snap = snap.copy()
    snap["gex_contract"] = np.where(
        snap["type"] == "call",
        snap["open_interest"] * snap["gamma"] * spot**2 * 0.01,
        -snap["open_interest"] * snap["gamma"] * spot**2 * 0.01,
    )

    out = (
        snap.groupby("tte_bucket", observed=True)
        .agg(
            net_gex=("gex_contract", "sum"),
            abs_gex=("gex_contract", lambda x: x.abs().sum()),
            oi_total=("open_interest", "sum"),
        )
        .reset_index()
    )
    return out


def find_key_levels(gex_by_strike: pd.DataFrame) -> dict:
    """
    Derive key GEX levels:
      - net_gex_total: sum of all GEX
      - zero_gamma_strike: strike where cumulative GEX (OTM→spot) crosses zero
      - max_pos_gamma_strike: strike with highest positive GEX (gamma wall)
      - max_neg_gamma_strike: strike with most negative GEX
      - spot: current underlying price
    """
    df = gex_by_strike.copy()
    spot = df["spot"].iloc[0]
    net_total = df["gex_net"].sum()

    max_pos = df.loc[df["gex_net"].idxmax(), "strike"] if df["gex_net"].max() > 0 else None
    max_neg = df.loc[df["gex_net"].idxmin(), "strike"] if df["gex_net"].min() < 0 else None

    # Zero gamma: find strike where cumulative GEX from lowest strike crosses zero
    df_sorted = df.sort_values("strike")
    df_sorted["cum_gex"] = df_sorted["gex_net"].cumsum()
    sign_changes = df_sorted[df_sorted["cum_gex"].shift(1) * df_sorted["cum_gex"] < 0]
    zero_gamma = float(sign_changes["strike"].iloc[0]) if not sign_changes.empty else None

    return {
        "spot": spot,
        "net_gex_total": net_total,
        "gex_regime": "Long Gamma" if net_total >= 0 else "Short Gamma",
        "zero_gamma_strike": zero_gamma,
        "max_pos_gamma_strike": float(max_pos) if max_pos is not None else None,
        "max_neg_gamma_strike": float(max_neg) if max_neg is not None else None,
    }
