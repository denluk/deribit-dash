from dataclasses import dataclass
from pathlib import Path

@dataclass
class PipelineConfig:
    input_path: str
    output_dir: str = "artifacts"
    resample_freq: str = "1H"
    max_tte_days: int = 365
    strike_bucket_size: int = 5000
    atm_candidates_per_group: int = 3
    min_valid_mid: float = 1e-12
