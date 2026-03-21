# Unified Repo Manifest

This is the **single unified repository** for the Deribit options intelligence stack.

It contains all previously built components in one place:

## 1. Ingestion and normalization
- `run_s3_pipeline.py`
- `orchestrate_batch.py`
- `orchestrate_snapshot.py`
- `src/deribit_intel/s3_ingestion.py`
- `src/deribit_intel/loaders.py`
- `src/deribit_intel/features.py`

## 2. Broad intelligence layer
- `src/deribit_intel/position_state.py`
- `src/deribit_intel/vol_surface.py`
- `src/deribit_intel/rv_models.py`
- `src/deribit_intel/edge_engine.py`
- `src/deribit_intel/execution_risk.py`
- `src/deribit_intel/portfolio.py`

## 3. Surface / repricing layer
- `src/deribit_intel/surface_engine.py`
- `src/deribit_intel/market_repricing.py`
- `src/deribit_intel/surface_shocks.py`
- `src/deribit_intel/surface_quality.py`
- `src/deribit_intel/surface_interpolation.py`

## 4. Signal layer
- `src/deribit_intel/signals.py`
- `src/deribit_intel/signals_market.py`

## 5. Dashboard layer
- `src/deribit_intel/app.py`
- `src/deribit_intel/pages/`

## 6. Main docs
- `README.md`
- `MODULE_ARCHITECTURE.md`
- `MARKET_FIRST_DESIGN.md`
- `COMBINED_TANDEM_ARCHITECTURE.md`
- `ORCHESTRATION_GUIDE.md`
- `PRODUCTION_NEXT_STEPS.md`

## Recommended run order

### Batch context build
```bash
pip install -r requirements.txt
export PYTHONPATH=src
python orchestrate_batch.py --input-path /mnt/data/combined_data.parquet --out-dir artifacts/batch
```

### Snapshot refinement
```bash
export PYTHONPATH=src
python orchestrate_snapshot.py --input-path /mnt/data/combined_data.parquet --batch-dir artifacts/batch --out-dir artifacts/snapshot
```

### Dashboard
```bash
export PYTHONPATH=src
streamlit run src/deribit_intel/app.py
```

## Philosophy
This unified repo is:
- market-first
- surface-aware
- RV/IV-context-aware
- execution/risk-gated
- split into batch context + snapshot refinement

It does **not** assume theoretical BS pricing is exchange truth.
