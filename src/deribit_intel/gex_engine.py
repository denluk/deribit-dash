"""
Gamma Exposure (GEX) engine — crypto-adapted dealer-gamma framework.

═══════════════════════════════════════════════════════════════════
WHY EQUITY-STYLE GEX FAILS IN CRYPTO
═══════════════════════════════════════════════════════════════════
Equity convention (Spotgamma / Brent Kochuba):
  Calls → dealers long gamma  (+GEX)
  Puts  → dealers short gamma (-GEX)

This assumes: investors write calls (covered call) → dealers buy them
              investors buy puts (hedge) → dealers sell them

Crypto reality:
  - Participants BUY calls speculatively → dealers SELL calls → dealers SHORT gamma
  - Puts are bought AND sold depending on funding/basis → mixed
  - Net effect: equity framework understates negative GEX in crypto

Crypto-adjusted convention used here:
  - Compute BOTH equity and crypto-adjusted (calls flip negative)
  - Show as a "GEX corridor" — truth lies between the two
  - Key levels from |absolute GEX| (sign-agnostic) are most reliable

═══════════════════════════════════════════════════════════════════
ADDITIONAL CRYPTO-SPECIFIC INDICATORS
═══════════════════════════════════════════════════════════════════
1. Max Pain         — strike where total buyer P&L is most negative
                      Institutional MMs have incentive to pin here near expiry
2. Charm Pressure   — delta decay from time alone (≤7 DTE options)
                      Mechanical delta flow as time passes, crypto weekly expiries
3. Vanna Exposure   — delta change from IV moves
                      Crypto IV swings are huge (±20 vol pts in hours)
                      Positive vanna + falling IV → forced selling by dealers
4. GEX Velocity     — rate of change of net GEX
                      Fastest leading indicator of regime flip
5. Put/Call GEX     — imbalance at each strike reveals directional sentiment
                      Puts below spot = hedging floor, calls above = resistance ceiling
6. Absolute Gamma   — |GEX| regardless of sign = liquidity walls
                      Where price WILL cause mechanical hedging (direction unknown)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _latest_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["hour"] == df["hour"].max()].copy()


def _compute_d1_d2(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Back-calculate d1 from option delta (avoids needing risk-free rate).
    Deribit delta is the Black-Scholes delta with r≈0.
    """
    sigma = (df["mark_iv"] / 100).clip(lower=0.01)
    T = (df["tte_days"] / 365).clip(lower=1e-6)

    abs_delta = df["delta"].abs().clip(lower=0.001, upper=0.999)
    d1 = norm.ppf(abs_delta)           # N(d1)=|delta| for both calls and puts
    d2 = d1 - sigma * np.sqrt(T)
    return d1, d2


def _gex_usd(oi: pd.Series, gamma: pd.Series, spot: float) -> pd.Series:
    """Dollar GEX per 1% spot move: OI × gamma × S²."""
    return oi * gamma * spot ** 2 * 0.01


# ─────────────────────────────────────────────────────────────────
# CORE GEX
# ─────────────────────────────────────────────────────────────────

def compute_gex_by_strike(df: pd.DataFrame, spot_override: float | None = None) -> pd.DataFrame:
    """
    GEX profile by strike — BOTH equity and crypto-adjusted convention.

    Returns columns:
        strike, gex_call_eq, gex_put_eq, gex_net_eq   (equity convention)
        gex_call_cr, gex_put_cr, gex_net_cr            (crypto: calls negative)
        gex_abs                                          (|gex_net_eq| + |gex_net_cr| / 2 band)
        oi_call, oi_put, gamma_call, gamma_put, spot
    """
    snap = _latest_snapshot(df)
    spot = spot_override or snap["underlying"].median()

    grp = snap.groupby(["strike", "type"], observed=True).agg(
        gamma=("gamma", "median"),
        open_interest=("open_interest", "sum"),
        volume_24h=("volume_24h", "sum"),
    ).reset_index()

    calls = grp[grp["type"] == "call"].copy()
    puts  = grp[grp["type"] == "put"].copy()

    calls["gex"] = _gex_usd(calls["open_interest"], calls["gamma"], spot)
    puts["gex"]  = _gex_usd(puts["open_interest"],  puts["gamma"],  spot)

    calls = calls.rename(columns={"gex": "gex_raw_c", "open_interest": "oi_call",
                                   "gamma": "gamma_call", "volume_24h": "vol_call"})
    puts  = puts.rename(columns={"gex": "gex_raw_p", "open_interest": "oi_put",
                                  "gamma": "gamma_put",  "volume_24h": "vol_put"})

    merged = pd.merge(
        calls[["strike", "gex_raw_c", "oi_call", "gamma_call", "vol_call"]],
        puts [["strike", "gex_raw_p", "oi_put",  "gamma_put",  "vol_put"]],
        on="strike", how="outer"
    ).fillna(0).sort_values("strike").reset_index(drop=True)

    # Equity convention
    merged["gex_call_eq"] = +merged["gex_raw_c"]
    merged["gex_put_eq"]  = -merged["gex_raw_p"]
    merged["gex_net_eq"]  = merged["gex_call_eq"] + merged["gex_put_eq"]

    # Crypto convention: calls also negative (dealers short call gamma)
    merged["gex_call_cr"] = -merged["gex_raw_c"]
    merged["gex_put_cr"]  = -merged["gex_raw_p"]
    merged["gex_net_cr"]  = merged["gex_call_cr"] + merged["gex_put_cr"]

    # Absolute gamma wall (sign-agnostic) — average of both conventions' magnitudes
    merged["gex_abs"] = (merged["gex_raw_c"] + merged["gex_raw_p"])

    merged["spot"] = spot
    return merged


def compute_gex_timeseries(df: pd.DataFrame) -> pd.DataFrame:
    """Net GEX (equity & crypto) per hour for regime tracking."""
    spot_by_hour = df.groupby("hour")["underlying"].median().rename("spot")
    df = df.join(spot_by_hour, on="hour")

    df["gex_eq"] = np.where(
        df["type"] == "call",
        +_gex_usd(df["open_interest"], df["gamma"], df["spot"]),
        -_gex_usd(df["open_interest"], df["gamma"], df["spot"]),
    )
    df["gex_cr"] = -_gex_usd(df["open_interest"], df["gamma"], df["spot"])  # all negative in crypto

    ts = (
        df.groupby("hour")[["gex_eq", "gex_cr"]]
        .sum()
        .reset_index()
        .rename(columns={"gex_eq": "net_gex_equity", "gex_cr": "net_gex_crypto"})
    )
    ts = ts.join(spot_by_hour, on="hour")

    # Regime: if BOTH conventions agree on negative → confirmed short-gamma
    ts["regime"] = np.select(
        [
            (ts["net_gex_equity"] > 0) & (ts["net_gex_crypto"] > 0),
            (ts["net_gex_equity"] < 0) & (ts["net_gex_crypto"] < 0),
        ],
        ["Confirmed Long Gamma", "Confirmed Short Gamma"],
        default="Mixed / Uncertain",
    )

    ts["gex_velocity"] = ts["net_gex_equity"].diff()  # rate of change → regime flip signal
    return ts


def compute_gex_by_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """GEX per DTE bucket — front-month weight matters most."""
    snap = _latest_snapshot(df)
    spot = snap["underlying"].median()

    snap = snap.copy()
    snap["gex_eq"] = np.where(
        snap["type"] == "call",
        +_gex_usd(snap["open_interest"], snap["gamma"], spot),
        -_gex_usd(snap["open_interest"], snap["gamma"], spot),
    )

    out = (
        snap.groupby("tte_bucket", observed=True)
        .agg(
            net_gex_eq=("gex_eq", "sum"),
            abs_gex=("gex_eq", lambda x: x.abs().sum()),
            oi_total=("open_interest", "sum"),
        )
        .reset_index()
    )
    return out


# ─────────────────────────────────────────────────────────────────
# CRYPTO-SPECIFIC: MAX PAIN
# ─────────────────────────────────────────────────────────────────

def compute_max_pain(df: pd.DataFrame) -> pd.DataFrame:
    """
    Max pain strike = where total option buyer P&L is most negative at expiry.
    At expiration, buyer losses = premium paid - intrinsic value.
    MMs have incentive to pin price here near expiry.
    """
    snap = _latest_snapshot(df)
    strikes = sorted(snap["strike"].unique())
    spot = snap["underlying"].median()

    results = []
    for test_strike in strikes:
        # P&L of call buyers if price = test_strike
        calls = snap[snap["type"] == "call"].copy()
        calls["intrinsic"] = (test_strike - calls["strike"]).clip(lower=0)
        calls["buyer_pnl"] = (calls["intrinsic"] - calls["mark_price"]) * calls["open_interest"]

        # P&L of put buyers if price = test_strike
        puts = snap[snap["type"] == "put"].copy()
        puts["intrinsic"] = (puts["strike"] - test_strike).clip(lower=0)
        puts["buyer_pnl"] = (puts["intrinsic"] - puts["mark_price"]) * puts["open_interest"]

        total_buyer_pnl = calls["buyer_pnl"].sum() + puts["buyer_pnl"].sum()
        results.append({"strike": test_strike, "total_buyer_pnl": total_buyer_pnl})

    df_mp = pd.DataFrame(results)
    # Max pain = strike where buyers lose the most (min P&L)
    df_mp["max_pain_flag"] = df_mp["total_buyer_pnl"] == df_mp["total_buyer_pnl"].min()
    return df_mp


# ─────────────────────────────────────────────────────────────────
# CRYPTO-SPECIFIC: CHARM PRESSURE (≤7 DTE)
# ─────────────────────────────────────────────────────────────────

def compute_charm_pressure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Charm = rate of delta decay per day (time passing → delta changes).

    In crypto, weekly expiries create concentrated charm pressure.
    Charm exposure = OI × charm × S → how many $ of delta flow per day
    from time decay alone (no price move needed — mechanical hedging).

    Formula (BS, r≈0):
        charm = -N'(d1) × d2 / (2 × T)
    where d1, d2 from BS, T in years.
    """
    snap = _latest_snapshot(df)
    near = snap[snap["tte_days"] <= 7].copy()
    if near.empty:
        return pd.DataFrame(columns=["strike", "charm_pressure_usd", "type"])

    spot = near["underlying"].median()
    T = (near["tte_days"] / 365).clip(lower=1e-6)
    d1, d2 = _compute_d1_d2(near)

    # charm: negative = delta decaying toward 0 for both calls and puts
    near["charm"] = -norm.pdf(d1) * d2 / (2 * T)

    # sign: calls have positive delta decaying → short negative charm (sells delta)
    #        puts have negative delta decaying → positive (buys delta)
    near["charm_sign"] = np.where(near["type"] == "call", 1, -1)

    near["charm_pressure_usd"] = (
        near["open_interest"] * near["charm"] * near["charm_sign"] * spot
    )

    out = (
        near.groupby(["strike", "type"], observed=True)["charm_pressure_usd"]
        .sum()
        .reset_index()
    )
    out["spot"] = spot
    return out


# ─────────────────────────────────────────────────────────────────
# CRYPTO-SPECIFIC: VANNA EXPOSURE (vol-driven delta hedging)
# ─────────────────────────────────────────────────────────────────

def compute_vanna_exposure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vanna = sensitivity of delta to IV change.

    In crypto, IV moves ±20 vol pts intraday. Positive vanna + falling IV
    → dealer delta falls → forced selling. Negative vanna + falling IV → forced buying.

    Formula (BS):
        vanna = -N'(d1) × d2 / sigma

    Vanna exposure per 1 vol pt IV move:
        vanna_exp = OI × vanna × spot × (1 vol pt / 100)
    """
    snap = _latest_snapshot(df)
    spot = snap["underlying"].median()

    sigma = (snap["mark_iv"] / 100).clip(lower=0.01)
    d1, d2 = _compute_d1_d2(snap)

    snap = snap.copy()
    snap["vanna"] = -norm.pdf(d1) * d2 / sigma

    # For calls: positive vanna (delta increases when IV rises)
    # For puts:  negative vanna (delta decreases in magnitude when IV rises)
    snap["vanna_sign"] = np.where(snap["type"] == "call", 1, -1)
    snap["vanna_exp_1vp"] = snap["open_interest"] * snap["vanna"] * snap["vanna_sign"] * spot * 0.01

    out = (
        snap.groupby(["strike", "type"], observed=True)["vanna_exp_1vp"]
        .sum()
        .reset_index()
    )
    out["spot"] = spot
    return out


# ─────────────────────────────────────────────────────────────────
# KEY LEVELS
# ─────────────────────────────────────────────────────────────────

def find_key_levels(gex_by_strike: pd.DataFrame, max_pain_df: pd.DataFrame | None = None) -> dict:
    """
    All key levels for crypto GEX analysis.
    """
    df = gex_by_strike.copy()
    spot = float(df["spot"].iloc[0])

    # Net GEX totals (both conventions)
    net_eq = df["gex_net_eq"].sum()
    net_cr = df["gex_net_cr"].sum()

    if net_eq > 0 and net_cr > 0:
        regime = "Confirmed Long Gamma"
    elif net_eq < 0 and net_cr < 0:
        regime = "Confirmed Short Gamma"
    else:
        regime = "Mixed / Uncertain"

    # Gamma walls = top 3 strikes by absolute GEX
    top_abs = df.nlargest(3, "gex_abs")[["strike", "gex_abs"]].values.tolist()

    # Zero gamma (equity convention cumulative)
    df_s = df.sort_values("strike")
    df_s["cum_gex"] = df_s["gex_net_eq"].cumsum()
    zg = df_s[df_s["cum_gex"].shift(1, fill_value=df_s["cum_gex"].iloc[0]) * df_s["cum_gex"] < 0]
    zero_gamma = float(zg["strike"].iloc[0]) if not zg.empty else None

    # Largest positive / negative GEX strike
    max_pos = float(df.loc[df["gex_net_eq"].idxmax(), "strike"]) if df["gex_net_eq"].max() > 0 else None
    max_neg = float(df.loc[df["gex_net_eq"].idxmin(), "strike"]) if df["gex_net_eq"].min() < 0 else None

    # Put wall (largest put GEX below spot)
    put_below = df[(df["strike"] < spot) & (df["gex_put_eq"] < 0)]
    put_wall = float(put_below.loc[put_below["gex_put_eq"].idxmin(), "strike"]) if not put_below.empty else None

    # Call wall (largest call GEX above spot)
    call_above = df[(df["strike"] > spot) & (df["gex_call_eq"] > 0)]
    call_wall = float(call_above.loc[call_above["gex_call_eq"].idxmax(), "strike"]) if not call_above.empty else None

    # Max pain
    max_pain = None
    if max_pain_df is not None and not max_pain_df.empty:
        mp_row = max_pain_df.loc[max_pain_df["total_buyer_pnl"].idxmin()]
        max_pain = float(mp_row["strike"])

    return {
        "spot": spot,
        "regime": regime,
        "net_gex_equity": net_eq,
        "net_gex_crypto": net_cr,
        "zero_gamma_strike": zero_gamma,
        "gamma_wall_top3": top_abs,
        "max_pos_gamma_strike": max_pos,
        "max_neg_gamma_strike": max_neg,
        "put_wall": put_wall,
        "call_wall": call_wall,
        "max_pain": max_pain,
    }
