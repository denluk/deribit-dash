# Market-First Surface Design

## Why this layer exists
Real options markets do not price contracts by blindly applying a theoretical Black-Scholes number.

This repo therefore treats:
- executable market quotes as primary truth
- implied volatility surface as the normalization object
- Black-style formulas as local translation/repricing tools only

## Added modules

### `surface_engine.py`
Builds:
- observed surface nodes
- fitted surface grid by hour × option type × tenor × log-moneyness
- fit confidence and distance metrics

### `market_repricing.py`
Builds:
- local market-surface repricing
- local Greeks conditional on the fitted surface
- market-relative value table

Outputs are explicitly named:
- `local_delta`
- `local_gamma`
- `local_vega`
- `surface_conditional_theta`

### `surface_shocks.py`
Defines shock families:
- sticky strike spot shifts
- parallel IV shifts
- crash-style put skew steepening
- front-end event premium expansion
- front-end event crush

### `surface_quality.py`
Scores:
- surface fit confidence
- liquidity reliability
- combined surface reliability
- uncertainty report

### `signals_market.py`
Builds signals only after combining:
- regime RV forecast
- tradability filters
- market-relative repricing
- surface reliability

## Design principles
1. Never treat surface fit as ground truth
2. Always carry fit confidence
3. Penalize sparse, wide-spread, thin-OI regions
4. Prefer local surface-relative value over global theoretical mispricing
5. Shock the surface, not just the Greeks

## Still approximate
- surface fit is nearest/local weighted smoothing, not arbitrage-free spline calibration
- local repricing still uses Black-style translation
- no full forward curve / rate / carry calibration
- no full bid/ask execution simulator yet

## Best next upgrades
- exact delta-space interpolation
- arbitrage-aware surface smoothing
- bid/ask aware surface bands
- full shock repricing from the fitted surface
- backtest harness on surface-reliability-gated signals
