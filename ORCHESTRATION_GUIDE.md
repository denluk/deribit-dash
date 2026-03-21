# Orchestration Guide

This repo now has two explicit orchestrators:

- `orchestrate_batch.py`
- `orchestrate_snapshot.py`

## Why two orchestrators

The system has two different workloads:

### 1. Batch intelligence workload
Runs over full history or fresh S3 partitions.
Goal:
- create broad context
- compute RV/IV regime state
- compute risk and portfolio state
- produce context tables for dashboards and downstream refinement

### 2. Snapshot refinement workload
Runs on the latest chain slice.
Goal:
- build local market surface
- reprice contracts conditionally on that surface
- score reliability
- run final gated market-first signals

These are complementary, not redundant.

## Standard run order

### Step 1 — batch layer
```bash
export PYTHONPATH=src
python orchestrate_batch.py --input-path /mnt/data/combined_data.parquet --out-dir artifacts/batch
```

Or from S3:
```bash
export PYTHONPATH=src
python orchestrate_batch.py \
  --bucket your-bucket \
  --prefix deribit/options/ \
  --start-date 2026-02-01 \
  --end-date 2026-03-07 \
  --out-dir artifacts/batch
```

### Step 2 — snapshot layer
```bash
export PYTHONPATH=src
python orchestrate_snapshot.py \
  --input-path /mnt/data/combined_data.parquet \
  --batch-dir artifacts/batch \
  --out-dir artifacts/snapshot
```

## Output contract between them

The snapshot layer consumes from the batch layer:

- `regime_rv.parquet`
- `vol_regimes.parquet`
- `event_premium.parquet`

So batch provides the **broad context**, while snapshot provides the **local surface refinement**.

## Design principle

### Batch layer is for:
- whole-history computation
- cheap broad scanning
- dashboards
- context and risk state

### Snapshot layer is for:
- contract-level local valuation
- surface confidence
- realistic surface shocks
- final candidate selection

## Practical interpretation

A signal should only survive if:
- broad batch context does not already warn against it
- local surface reliability is acceptable
- execution guardrails are acceptable

That is why the snapshot layer is downstream of the batch layer.
