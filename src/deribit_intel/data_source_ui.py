from __future__ import annotations
from datetime import date
import os
import streamlit as st

from deribit_intel.s3_ingestion import load_env_file_tokenless

S3_MIN_DATE = date(2026, 1, 26)


def _build_s3_daily_uri(bucket: str, prefix: str, selected_date: date) -> str:
    normalized_prefix = prefix.strip("/")
    return f"s3://{bucket}/{normalized_prefix}/{selected_date.isoformat()}.parquet"


def resolve_input_path(page_key: str, local_default: str = "artifacts/s3_extract.parquet") -> str:
    load_env_file_tokenless(".env.s3")
    source = st.sidebar.radio(
        "Data source",
        ["Local parquet", "S3 daily parquet"],
        key=f"{page_key}_data_source",
    )
    if source == "Local parquet":
        return st.sidebar.text_input("Input parquet path", local_default, key=f"{page_key}_local_path")

    bucket_default = os.getenv("S3_BUCKET", "crypto-collector-prod-data-720428162886")
    prefix_default = os.getenv("S3_PREFIX", "data/options_greeks/BTC/")
    bucket = st.sidebar.text_input("S3 bucket", bucket_default, key=f"{page_key}_s3_bucket")
    prefix = st.sidebar.text_input("S3 prefix", prefix_default, key=f"{page_key}_s3_prefix")
    selected_date = st.sidebar.date_input(
        "S3 date (from 26.01.2026)",
        value=max(S3_MIN_DATE, date.today()),
        min_value=S3_MIN_DATE,
        max_value=date.today(),
        key=f"{page_key}_s3_date",
    )
    path = _build_s3_daily_uri(bucket=bucket, prefix=prefix, selected_date=selected_date)
    st.sidebar.caption(f"Resolved S3 URI: `{path}`")
    return path
