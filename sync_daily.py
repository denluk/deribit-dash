#!/usr/bin/env python3
"""Download today's options parquet from S3 into artifacts/."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env.s3 if present (no external deps needed)
env_file = Path(__file__).parent / ".env.s3"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import boto3  # noqa: E402

BUCKET = os.environ["S3_BUCKET"]
PREFIX = os.environ.get("S3_PREFIX", "data/options_greeks/BTC/").rstrip("/")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-north-1")
ARTIFACTS = Path(__file__).parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

def download_date(target_date: date) -> Path:
    key = f"{PREFIX}/{target_date.isoformat()}.parquet"
    dest = ARTIFACTS / f"{target_date.isoformat()}.parquet"
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
    except s3.exceptions.ClientError:
        print(f"[sync] NOT FOUND: s3://{BUCKET}/{key}")
        return None
    s3.download_file(BUCKET, key, str(dest))
    print(f"[sync] Downloaded: {key} → {dest}")
    return dest

def main():
    # Default: today, fallback to yesterday if today not yet available
    target = date.today()
    dest = download_date(target)
    if dest is None:
        target = date.today() - timedelta(days=1)
        dest = download_date(target)
    if dest is None:
        print("[sync] ERROR: no data found for today or yesterday")
        sys.exit(1)

    # Symlink/copy as s3_extract.parquet (default path for dashboard)
    latest = ARTIFACTS / "s3_extract.parquet"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(dest.name)
    print(f"[sync] Linked: artifacts/s3_extract.parquet → {dest.name}")

if __name__ == "__main__":
    main()
