from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

def build_hourly_underlying(df: pd.DataFrame) -> pd.DataFrame:
    px = df.groupby("hour", as_index=False)["underlying"].median().sort_values("hour").copy()
    px["log_ret"] = np.log(px["underlying"]).diff()
    return px

def add_realized_vol_features(px: pd.DataFrame) -> pd.DataFrame:
    out = px.copy()
    out["rv_6h"] = out["log_ret"].rolling(6).std() * np.sqrt(24 * 365)
    out["rv_24h"] = out["log_ret"].rolling(24).std() * np.sqrt(24 * 365)
    out["rv_72h"] = out["log_ret"].rolling(72).std() * np.sqrt(24 * 365)
    out["absret_6h"] = out["log_ret"].abs().rolling(6).mean() * np.sqrt(24 * 365)
    out["absret_24h"] = out["log_ret"].abs().rolling(24).mean() * np.sqrt(24 * 365)
    out["future_rv_24h"] = out["log_ret"].rolling(24).std().shift(-24) * np.sqrt(24 * 365)
    return out

def har_rv_forecast(px: pd.DataFrame) -> pd.DataFrame:
    out = add_realized_vol_features(px)
    # Short-history fallback: keep forecast columns usable for partial-day slices.
    if out["rv_24h"].notna().sum() == 0:
        out["rv_24h"] = out["log_ret"].abs().rolling(3, min_periods=2).mean() * np.sqrt(24 * 365)
    if out["rv_72h"].notna().sum() == 0:
        out["rv_72h"] = out["rv_24h"]
    if out["absret_6h"].notna().sum() == 0:
        out["absret_6h"] = out["rv_24h"]

    model_df = out.dropna(subset=["rv_6h", "rv_24h", "rv_72h", "future_rv_24h"]).copy()
    out["har_rv_forecast_24h"] = np.nan
    if len(model_df) < 50:
        out["har_rv_forecast_24h"] = (
            0.55 * out["rv_24h"].ffill().bfill() +
            0.30 * out["rv_72h"].ffill().bfill() +
            0.15 * out["absret_6h"].ffill().bfill()
        )
        return out
    X = model_df[["rv_6h", "rv_24h", "rv_72h"]].values
    y = model_df["future_rv_24h"].values
    lr = LinearRegression()
    lr.fit(X, y)
    mask = out[["rv_6h", "rv_24h", "rv_72h"]].notna().all(axis=1)
    out.loc[mask, "har_rv_forecast_24h"] = lr.predict(out.loc[mask, ["rv_6h", "rv_24h", "rv_72h"]].values)
    return out

def regime_conditioned_rv_forecast(px: pd.DataFrame) -> pd.DataFrame:
    out = har_rv_forecast(px)
    iv_proxy = out["rv_24h"].rolling(12, min_periods=6).mean()
    vol_regime = np.select(
        [iv_proxy > iv_proxy.rolling(72, min_periods=24).mean() + iv_proxy.rolling(72, min_periods=24).std(),
         iv_proxy < iv_proxy.rolling(72, min_periods=24).mean() - iv_proxy.rolling(72, min_periods=24).std()],
        ["high_vol", "low_vol"],
        default="mid_vol",
    )
    out["rv_regime"] = vol_regime
    adj = {"high_vol": 1.10, "mid_vol": 1.00, "low_vol": 0.92}
    out["regime_rv_forecast_24h"] = out["har_rv_forecast_24h"] * pd.Series(out["rv_regime"]).map(adj).values
    return out
