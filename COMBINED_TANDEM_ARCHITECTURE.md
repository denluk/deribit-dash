# Combined Tandem Architecture

This repository now combines two complementary layers:

1. **Expanded operational analytics layer**
   - S3 ingestion
   - RV models
   - dashboard pages
   - broad signal/risk pipeline
2. **Market-first surface layer**
   - observed surface nodes
   - fitted local surface grid
   - local repricing
   - surface quality / reliability
   - market-first gated signals

These are not competing stacks. They should work **in tandem**.

---

# 1. The correct mental model

Think of the system as two loops running at different levels:

## Loop A — broad market intelligence loop
This loop answers:
- what is the state of the book?
- what is happening in ATM IV?
- how is skew moving?
- how is term structure moving?
- what is RV doing versus IV?
- is the regime rich, calm, stressed, inverted, event-heavy?

This loop is mostly:
- descriptive
- monitoring-oriented
- relatively cheap to compute
- suitable for full-history batch runs and dashboards

Main modules:
- `s3_ingestion.py`
- `loaders.py`
- `features.py`
- `position_state.py`
- `vol_surface.py`
- `rv_models.py`
- `edge_engine.py`
- `execution_risk.py`
- `portfolio.py`

## Loop B — local market-surface valuation loop
This loop answers:
- what does the observed local surface imply here?
- how reliable is that local fit?
- is a contract rich or cheap relative to nearby surface nodes?
- how should I reprice the contract under a realistic surface scenario?
- should I suppress signals in sparse/illiquid regions?

This loop is:
- more local
- more selective
- more quality-sensitive
- more appropriate for latest snapshots or short rolling windows

Main modules:
- `surface_engine.py`
- `market_repricing.py`
- `surface_shocks.py`
- `surface_quality.py`
- `signals_market.py`

---

# 2. How they should work together

The correct dependency is:

## Stage 1 — ingest and normalize
Use:
- `run_s3_pipeline.py`
- `s3_ingestion.py`
- `loaders.py`
- `features.py`

Output:
- normalized parquet with timestamps, TTE, moneyness, spreads, notionals

This is the common base for everything else.

## Stage 2 — run broad intelligence in parallel
From the normalized dataset, compute in parallel:

### Branch A1 — position/risk state
- `position_state.py`
- `execution_risk.py`
- `portfolio.py`

Outputs:
- book Greeks
- expiry sensitivity
- convexity maps
- stress matrix
- portfolio aggregates

### Branch A2 — vol/rv state
- `vol_surface.py`
- `rv_models.py`
- `edge_engine.py`

Outputs:
- ATM monitor
- skew monitor
- term structure
- RV vs IV
- event premium
- variance premium
- regime-conditioned RV forecast

These two branches can run independently and in parallel because they share the same normalized base table.

## Stage 3 — use broad intelligence as context filters
Before the local market-first layer runs, use broad intelligence to define context:

Examples:
- only enable local repricing when vol regime is not `joint_stress` unless explicitly stress-testing
- downweight contracts when execution guardrails fail
- penalize front-end signals when event premium is extreme
- adjust thresholds when RV forecast uncertainty is high

So Loop A is the **context engine** for Loop B.

## Stage 4 — run market-first surface layer on selected snapshots
Use:
- latest snapshot per instrument, or
- rolling recent slices (for example last hour or last 4 hours)

Then run:
- `surface_engine.py`
- `market_repricing.py`
- `surface_quality.py`
- `surface_shocks.py`

Outputs:
- observed nodes
- fitted surface grid
- surface quality report
- repriced contracts
- reliability scores
- shocked surface scenarios

This branch should generally be more selective and not necessarily run over the full history unless you explicitly want historical surface reconstruction.

## Stage 5 — generate signals only after both loops agree
This is critical.

A contract should not reach the final signal layer unless:

### Broad loop says:
- the regime is interpretable
- RV forecast exists
- execution/risk guardrails are acceptable
- no hard portfolio breach is active

### Local loop says:
- surface fit confidence is acceptable
- contract reliability is acceptable
- market-relative cheap/rich score is meaningful
- local repricing is not coming from a sparse inferred wing

Then use:
- `signals.py` for broad exploratory scoring
- `signals_market.py` for the final market-first gated signal table

In practice:
- `signals.py` = research / exploratory layer
- `signals_market.py` = stricter candidate layer

---

# 3. What should run in parallel

## Safe to run in parallel
From the same normalized input:
- `position_state.py`
- `vol_surface.py`
- `rv_models.py`
- `execution_risk.py`
- `portfolio.py`

These are natural parallel branches.

## Should run after those branches
- `edge_engine.py`
  because it depends on RV/IV context
- `signals.py`
  because it uses RV forecast + execution filters

## Should run on selected snapshot context
- `surface_engine.py`
- `market_repricing.py`
- `surface_quality.py`
- `surface_shocks.py`

## Should run last
- `signals_market.py`

That ordering matters because the market-first signal layer should consume:
- RV forecast
- execution flags
- surface reliability
- local repricing outputs

---

# 4. Why not make the market-first layer the only layer?

Because it would be too narrow and too expensive as a first-pass scanner.

The broad operational layer is better for:
- whole-history monitoring
- regime detection
- dashboarding
- portfolio risk
- cheap large-scale screening

The market-first layer is better for:
- contract-level decision refinement
- confidence-aware repricing
- surface-relative dislocation detection
- realistic scenario analysis

So the best architecture is:

**broad loop scans the field**
→ **market-first loop zooms in**
→ **risk/execution layer decides whether anything is actually tradable**

---

# 5. Practical orchestration modes

## Mode A — historical research batch
Use full history.
Run:
1. normalize
2. broad intelligence tables
3. RV/IV and regime tables
4. optional periodic surface reconstruction
5. exploratory signals

Goal:
- research
- feature engineering
- regime study
- backtest data generation

## Mode B — production monitoring batch
Every hour (or other cadence):
1. ingest fresh S3 partitions
2. update broad tables
3. update RV forecasts and risk flags
4. rebuild latest surface snapshot
5. generate market-first top signals
6. publish dashboard/state tables

Goal:
- monitoring
- watchlists
- candidate generation

## Mode C — intraday decision refinement
On a fresh snapshot only:
1. pull latest normalized chain
2. run surface grid
3. run local repricing
4. run reliability scoring
5. apply surface shocks
6. output final gated candidate list

Goal:
- fine-grained trade selection or decision support

---

# 6. Recommended DAG

A good DAG is:

```text
S3 / local parquet
    ↓
loaders.py + features.py
    ↓
normalized_chain
    ├── position_state.py
    ├── execution_risk.py
    ├── portfolio.py
    ├── vol_surface.py
    └── rv_models.py
           ↓
       edge_engine.py
    ↓
broad_context_tables
    ↓
latest_snapshot_selector
    ↓
surface_engine.py
    ↓
market_repricing.py
    ↓
surface_quality.py
    ├── surface_shocks.py
    └── signals_market.py
```

This keeps the heavier local-surface computations downstream of the cheaper broad context layer.

---

# 7. Concrete role of the two signal modules

## `signals.py`
Use for:
- broad contract scanning
- research ranking
- hypothesis generation
- looser screening

Not ideal as final truth because it does not explicitly depend on the market-first surface reliability layer.

## `signals_market.py`
Use for:
- final candidate shortlist
- reliability-aware ranking
- market-relative scoring
- stricter gating

This should be treated as the **final downstream signal layer**.

---

# 8. Skeptical warning

Parallel does not mean independent truth.

Failure cases:
- broad RV forecast says “cheap vol”, but local surface fit is low-confidence
- market-relative repricing says “rich”, but execution filters fail
- term structure says event premium is extreme, making naive short-vol ranking dangerous
- portfolio gamma breach means otherwise attractive local signals must be suppressed

So the final ranking should always combine:
- broad regime context
- execution/risk constraints
- local surface reliability
- market-relative value

---

# 9. Best next implementation move

The strongest next step is to add an explicit orchestrator, for example:

- `orchestrate_batch.py`
- `orchestrate_snapshot.py`

where:
- batch orchestrator runs the broad layer over history
- snapshot orchestrator runs the market-first layer on the latest chain and consumes the batch outputs

That would formalize the tandem design into a real DAG rather than a collection of modules.
