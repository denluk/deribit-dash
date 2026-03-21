from __future__ import annotations
import numpy as np
import pandas as pd

TTE_BINS = [-1, 2, 7, 30, 90, 180, 10000]
TTE_LABELS = ["0-2d", "3-7d", "8-30d", "31-90d", "91-180d", "180d+"]

def add_feature_layers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["tte_bucket"] = pd.cut(out["tte_days"], bins=TTE_BINS, labels=TTE_LABELS)
    out["is_call"] = (out["type"] == "call").astype(int)
    out["is_put"] = (out["type"] == "put").astype(int)
    out["otm_flag"] = np.where(
        ((out["type"] == "call") & (out["strike"] > out["underlying"])) |
        ((out["type"] == "put") & (out["strike"] < out["underlying"])),
        1, 0
    )
    return out

def extract_atm_slice(df: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    tmp = df.copy()
    tmp["atm_rank"] = tmp.groupby(["hour", "tte_bucket", "type"])["abs_log_moneyness"].rank(method="first")
    return tmp[tmp["atm_rank"] <= top_n].copy()
