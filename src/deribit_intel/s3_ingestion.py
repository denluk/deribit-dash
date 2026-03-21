from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional, List, Tuple
import re
import os
from pathlib import Path
import pandas as pd
import boto3

@dataclass
class S3SourceConfig:
    bucket: str
    prefix: str
    aws_region: Optional[str] = None

def load_env_file_tokenless(env_file: str = ".env.s3") -> None:
    path = Path(env_file)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ[key] = value.strip()
    # Enforce long-lived key/secret mode only.
    os.environ.pop("AWS_SESSION_TOKEN", None)

def _aws_key_secret() -> Tuple[Optional[str], Optional[str]]:
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        return access_key, secret_key
    return None, None

def _boto3_client_kwargs(aws_region: str | None = None) -> dict:
    load_env_file_tokenless()
    kwargs: dict = {}
    region = aws_region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        kwargs["region_name"] = region
    access_key, secret_key = _aws_key_secret()
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    return kwargs

def _parquet_storage_options(aws_region: str | None = None) -> dict | None:
    load_env_file_tokenless()
    access_key, secret_key = _aws_key_secret()
    if not access_key or not secret_key:
        return None
    region = aws_region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    out = {"key": access_key, "secret": secret_key}
    if region:
        out["client_kwargs"] = {"region_name": region}
    return out

def parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {s3_uri}")
    bucket_and_key = s3_uri[len("s3://"):]
    if "/" not in bucket_and_key:
        raise ValueError(f"S3 URI must include object key, got: {s3_uri}")
    bucket, key = bucket_and_key.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"S3 URI must include bucket and object key, got: {s3_uri}")
    return bucket, key

def list_s3_keys(bucket: str, prefix: str, suffix: str = ".parquet", aws_region: str | None = None) -> List[str]:
    client = boto3.client("s3", **_boto3_client_kwargs(aws_region=aws_region))
    paginator = client.get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(suffix):
                out.append(key)
    return out

def filter_keys_by_partition(keys: Iterable[str], start_date: str | None = None, end_date: str | None = None) -> list[str]:
    """
    Supports keys containing fragments like:
    - dt=2026-03-07
    - date=2026-03-07
    - year=2026/month=03/day=07
    - 2026-03-07.parquet
    """
    def _extract_date(key: str) -> str | None:
        m1 = re.search(r"(?:dt|date)=(\d{4}-\d{2}-\d{2})", key)
        if m1:
            return m1.group(1)
        m2 = re.search(r"year=(\d{4})/month=(\d{2})/day=(\d{2})", key)
        if m2:
            return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
        m3 = re.search(r"(?:^|/)(\d{4}-\d{2}-\d{2})\.parquet$", key)
        if m3:
            return m3.group(1)
        return None

    out = []
    for key in keys:
        key_date = _extract_date(key)
        if key_date is None:
            out.append(key)
            continue
        if start_date and key_date < start_date:
            continue
        if end_date and key_date > end_date:
            continue
        out.append(key)
    return out

def load_s3_parquet_dataset(bucket: str, keys: list[str], aws_region: str | None = None) -> pd.DataFrame:
    paths = [f"s3://{bucket}/{k}" for k in keys]
    if not paths:
        return pd.DataFrame()
    storage_options = _parquet_storage_options(aws_region=aws_region)
    if len(paths) == 1:
        if storage_options:
            return pd.read_parquet(paths[0], storage_options=storage_options)
        return pd.read_parquet(paths[0])

    if storage_options:
        frames = [pd.read_parquet(path, storage_options=storage_options) for path in paths]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return pd.read_parquet(paths)
