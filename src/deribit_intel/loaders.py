from __future__ import annotations
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from deribit_intel.s3_ingestion import _parquet_storage_options

def load_deribit_parquet(path: str) -> pd.DataFrame:
    if path.startswith("s3://"):
        storage_options = _parquet_storage_options()
        if storage_options:
            df = pd.read_parquet(path, storage_options=storage_options)
        else:
            df = pd.read_parquet(path)
    else:
        df = pq.read_table(path).to_pandas()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    if "expiry" in df.columns:
        df["expiry_dt"] = pd.to_datetime(df["expiry"], format="%d%b%y", errors="coerce")
    elif "expiry_dt" in df.columns:
        df["expiry_dt"] = pd.to_datetime(df["expiry_dt"], errors="coerce")
    return df

def add_base_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    if "expiry_dt" not in out.columns:
        if "expiry" in out.columns:
            out["expiry_dt"] = pd.to_datetime(out["expiry"], format="%d%b%y", errors="coerce")
    elif "expiry_dt" in out.columns:
        out["expiry_dt"] = pd.to_datetime(out["expiry_dt"], errors="coerce")
    if "expiry_dt" not in out.columns:
        raise KeyError("Missing required expiry field: expected `expiry_dt` or `expiry`.")

    out["tte_days"] = (out["expiry_dt"] - out["timestamp"]).dt.total_seconds() / 86400.0
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["spread"] = out["ask"] - out["bid"]
    out["spread_bps_mid"] = np.where(out["mid"] > 0, out["spread"] / out["mid"] * 1e4, np.nan)
    out["moneyness"] = out["strike"] / out["underlying"]
    out["abs_log_moneyness"] = np.abs(np.log(out["moneyness"]))
    out["notional_oi_usd"] = out["open_interest"] * out["underlying"]
    out["volume_24h_usd"] = out["volume_24h"] * out["underlying"]
    out["hour"] = out["timestamp"].dt.floor("H")
    return out
