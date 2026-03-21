# Deribit Unified Market-First Options Intelligence Repo

This is the unified repository containing the full stack:

- S3-aware ingestion
- normalized options-chain processing
- broad intelligence layer
- RV / IV forecasting and regime context
- execution and portfolio risk layer
- market-first local surface fitting
- local market-relative repricing
- surface quality and reliability scoring
- broad and market-first signal layers
- Streamlit dashboard pages
- explicit batch and snapshot orchestrators

## Main entrypoints

### Batch orchestrator
Builds the broad context layer from local parquet or S3:
```bash
python orchestrate_batch.py --input-path /mnt/data/combined_data.parquet --out-dir artifacts/batch
```

### Snapshot orchestrator
Builds the market-first local refinement layer using batch outputs:
```bash
python orchestrate_snapshot.py --input-path /mnt/data/combined_data.parquet --batch-dir artifacts/batch --out-dir artifacts/snapshot
```

### Dashboard
```bash
streamlit run src/deribit_intel/app.py
```

## Repo structure

```text
deribit_intel_unified_repo/
  README.md
  UNIFIED_REPO_MANIFEST.md
  MODULE_ARCHITECTURE.md
  MARKET_FIRST_DESIGN.md
  COMBINED_TANDEM_ARCHITECTURE.md
  ORCHESTRATION_GUIDE.md
  PRODUCTION_NEXT_STEPS.md
  orchestrate_batch.py
  orchestrate_snapshot.py
  run_pipeline.py
  run_s3_pipeline.py
  requirements.txt
  src/deribit_intel/
    app.py
    s3_ingestion.py
    loaders.py
    features.py
    position_state.py
    vol_surface.py
    rv_models.py
    edge_engine.py
    execution_risk.py
    portfolio.py
    surface_engine.py
    market_repricing.py
    surface_shocks.py
    surface_quality.py
    surface_interpolation.py
    signals.py
    signals_market.py
    pages/
```

## Operating model

### Batch layer
Use for:
- historical computation
- S3 partition processing
- RV/IV context
- vol regime state
- risk/portfolio context
- dashboard artifacts

### Snapshot layer
Use for:
- latest chain refinement
- local surface fitting
- local repricing
- reliability gating
- final market-first candidate generation

## Important note
This repo treats:
- market quotes as primary truth
- fitted surface as the main local state object
- Black-style math as a translation tool, not exchange truth
