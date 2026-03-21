from __future__ import annotations
import numpy as np
import pandas as pd

def generate_surface_shock_scenarios() -> pd.DataFrame:
    scenarios = [
        {"scenario": "sticky_strike_spot_dn_10", "spot_shock": -0.10, "iv_parallel": 0.00, "front_skew": 0.00, "front_shift": 0.00},
        {"scenario": "sticky_strike_spot_up_10", "spot_shock":  0.10, "iv_parallel": 0.00, "front_skew": 0.00, "front_shift": 0.00},
        {"scenario": "parallel_iv_up_5pts",    "spot_shock":  0.00, "iv_parallel": 0.05, "front_skew": 0.00, "front_shift": 0.00},
        {"scenario": "parallel_iv_dn_5pts",    "spot_shock":  0.00, "iv_parallel":-0.05, "front_skew": 0.00, "front_shift": 0.00},
        {"scenario": "crash_put_skew",         "spot_shock": -0.08, "iv_parallel": 0.03, "front_skew": 0.05, "front_shift": 0.03},
        {"scenario": "front_event_premium_up", "spot_shock":  0.00, "iv_parallel": 0.00, "front_skew": 0.00, "front_shift": 0.06},
        {"scenario": "front_event_crush",      "spot_shock":  0.00, "iv_parallel":-0.02, "front_skew":-0.01, "front_shift":-0.08},
    ]
    return pd.DataFrame(scenarios)

def apply_surface_shock_to_grid(surface_grid: pd.DataFrame, scenario_row: pd.Series) -> pd.DataFrame:
    s = surface_grid.copy()
    s["shocked_iv"] = s["fitted_iv"] + scenario_row["iv_parallel"]
    front_mask = s["tenor_days"] <= 14
    s.loc[front_mask, "shocked_iv"] = s.loc[front_mask, "shocked_iv"] + scenario_row["front_shift"]
    put_wing_mask = (s["type"] == "put") & (s["log_moneyness"] < 0)
    s.loc[put_wing_mask, "shocked_iv"] = s.loc[put_wing_mask, "shocked_iv"] + scenario_row["front_skew"] * np.clip(np.abs(s.loc[put_wing_mask, "log_moneyness"]) / 0.25, 0, 2)
    s["shocked_iv"] = s["shocked_iv"].clip(lower=0.01)
    s["scenario"] = scenario_row["scenario"]
    s["spot_shock"] = scenario_row["spot_shock"]
    return s

def build_all_surface_shocks(surface_grid: pd.DataFrame) -> pd.DataFrame:
    scen = generate_surface_shock_scenarios()
    parts = [apply_surface_shock_to_grid(surface_grid, row) for _, row in scen.iterrows()]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
