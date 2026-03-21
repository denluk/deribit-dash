from pathlib import Path
import argparse
import json

from deribit_intel.s3_ingestion import (
    list_s3_keys,
    filter_keys_by_partition,
    load_s3_parquet_dataset,
    parse_s3_uri,
)
from deribit_intel.loaders import add_base_fields
from deribit_intel.features import add_feature_layers

def main():
    parser = argparse.ArgumentParser(
        epilog=(
            "Examples:\n"
            "  python run_s3_pipeline.py --bucket my-bucket --prefix data/options_greeks/BTC/ --start-date 2026-03-15 --end-date 2026-03-15\n"
            "  python run_s3_pipeline.py --s3-uri s3://my-bucket/data/options_greeks/BTC/2026-03-15.parquet"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--s3-uri", default=None, help="Direct object path, e.g. s3://bucket/path/file.parquet")
    parser.add_argument("--aws-region", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--out", default="artifacts/s3_extract.parquet")
    args = parser.parse_args()

    if args.s3_uri:
        bucket, key = parse_s3_uri(args.s3_uri)
        keys = [key]
    else:
        if not args.bucket or not args.prefix:
            raise ValueError("Provide either --s3-uri or both --bucket and --prefix.")
        bucket = args.bucket
        keys = list_s3_keys(bucket, args.prefix, aws_region=args.aws_region)
        keys = filter_keys_by_partition(keys, start_date=args.start_date, end_date=args.end_date)
    df = load_s3_parquet_dataset(bucket, keys, aws_region=args.aws_region)
    if df.empty:
        print(json.dumps({"rows": 0, "keys": 0}))
        return
    df = add_feature_layers(add_base_fields(df))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(json.dumps({"rows": int(len(df)), "keys": int(len(keys)), "output": str(out)}))

if __name__ == "__main__":
    main()
