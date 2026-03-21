# Deribit Options Intelligence — Detailed Module Architecture

This document expands the starter pipeline into four deeply specified engines.

---

# Module 1 — Position State Engine

## Purpose
Translate a live/snapshot option chain into a compact **book-state representation** that answers:

- What are my current Greek exposures?
- Where is convexity concentrated?
- Which expiries dominate risk?
- How does the book respond to spot, IV, and time shocks?
- Where do higher-order risks (charm, vanna) matter even if not fully modeled yet?

## Inputs
Required:
- `timestamp`
- `instrument`
- `currency`
- `expiry`, `expiry_dt`
- `strike`
- `type`
- `underlying`
- `bid`, `ask`, `mark_price`, `mark_iv`
- `delta`, `gamma`, `theta`, `vega`
- `open_interest`, `volume_24h`

Derived:
- `hour`
- `tte_days`, `tte_bucket`
- `mid`, `spread`, `spread_bps_mid`
- `moneyness`, `abs_log_moneyness`
- `notional_oi_usd`, `volume_24h_usd`

Optional / future:
- `charm`
- `vanna`
- `vomma`
- `speed`

## Core submodules

### 1.1 Real-time Greeks
Outputs:
- net delta
- net gamma
- net theta
- net vega
- gross gamma / gross vega
- Greek density normalized by OI or notional

Why it matters:
- delta = directional bias
- gamma = convexity and hedge instability
- theta = carry / bleed
- vega = exposure to implied vol repricing

### 1.2 Scenario shocks
Run shock ladders on:
- spot: -15%, -10%, -5%, 0, +5%, +10%, +15%
- IV: -10 vol pts, -5 vol pts, 0, +5, +10
- time: 0, 1, 3 days

Approximation:
dP ~= delta*dS + 0.5*gamma*dS² + vega*dIV + theta*dT

Use case:
- pre-trade sanity
- post-trade monitoring
- stress alerting
- kill-switch gating

Warning:
This is a monitoring approximation only.  
Production trading should use a full repricer.

### 1.3 Expiry sensitivity
Aggregate Greeks and notional by:
- hour × expiry
- hour × TTE bucket

Goal:
- detect front-end gamma dominance
- detect back-end vega loading
- quantify expiry roll risk
- identify whether apparent book neutrality hides concentrated short-dated convexity

### 1.4 Charm / vanna awareness
Even if venue snapshots do not provide them reliably, the architecture must reserve hooks for:
- charm = delta drift over time
- vanna = delta sensitivity to vol / vega sensitivity to spot

Why:
- these are critical around short-dated options
- delta neutrality can decay fast
- surface changes can reconfigure directional exposure without large spot moves

### 1.5 Break-even and convexity maps
Produce:
- strike-bucket gamma concentration map
- strike-bucket vega concentration map
- local break-even corridor around ATM
- convexity ratio = net gamma / gross gamma

Interpretation:
- concentrated negative gamma near current spot is dangerous
- concentrated positive gamma may justify higher transaction turnover
- OI walls are not enough; gamma and vega walls matter more

## Failure modes
- Greeks are venue-supplied, not your own
- local approximation breaks under jumps
- sparse snapshot timing can distort “real-time” state
- OI is not position ownership; it is open contracts, so direction is not fully known

---

# Module 2 — Volatility Surface Engine

## Purpose
Describe the state of the volatility surface and its dynamics.

Questions:
- Where is ATM IV?
- Is skew steepening or flattening?
- Is front vol rich vs back vol?
- Is implied rich vs realized?
- Is near-dated premium event-driven or general stress?
- Which regime are we in?

## Core submodules

### 2.1 ATM IV monitor
Method:
- within each hour × expiry bucket × type
- rank by absolute log-moneyness
- keep closest-to-ATM contracts
- compute median ATM-ish IV

Outputs:
- ATM IV level
- ATM spread
- ATM notional OI
- ATM notional volume

### 2.2 Skew monitor
Track IV across moneyness buckets:
- deep OTM
- OTM
- ATM
- ITM
- deep ITM

Outputs:
- put skew / call skew proxies
- slope of smile by expiry bucket
- skew change through time

Use cases:
- detect crash-premium build
- detect wing richness
- detect asymmetry around event windows

### 2.3 Term structure monitor
Track IV across expiry buckets:
- 0–2d
- 3–7d
- 8–30d
- 31–90d
- 91–180d
- 180d+

Outputs:
- term slope
- term curvature
- front-back spread
- normalization versus OI

Interpretation:
- steep front premium often means event or stress
- inverted term structure often signals acute realized risk
- flat structure in a moving market can indicate underpricing

### 2.4 Realized vs implied tracker
Build hourly underlying series and compute:
- log returns
- RV over 6h / 24h / 72h
- IV proxy from ATM-ish or chain median

Outputs:
- IV - RV
- rolling VRP proxy
- IV percentile
- RV percentile

### 2.5 Event-premium decomposition
Approximate event premium as:
- near-expiry IV minus medium-expiry IV

Use cases:
- detect local event inflation
- separate short-dated panic from broad regime repricing
- avoid selling front vol blindly when event premium is justified

### 2.6 Vol regime labeling
Regime examples:
- `rich_calm`
- `cheap_calm`
- `realized_stress`
- `joint_stress`
- `neutral`

Based on:
- z-score of IV
- z-score of RV
- optional additions: skew z-score, term-slope z-score

## Failure modes
- chain median IV is a rough proxy; better to compute delta-specific slices
- surface interpolation is missing in the starter build
- event premium proxy is simplistic if multiple clustered events exist

---

# Module 3 — Edge Engine

## Purpose
Move from description to **economic judgment**.

Questions:
- Is the trade likely positive expectancy after costs?
- Is variance premium actually present?
- What is the conditional forecast of realized vol?
- How much premium is event/jump-related?
- Is a contract rich or cheap relative to its local surface neighborhood?

## Core submodules

### 3.1 Expected value after costs
Compute proxy costs:
- half-spread
- fee proxy
- optional impact proxy

Then build:
- expected vol edge = forecast RV - implied IV
- EV proxy = expected edge - total trading cost

This is a first-pass filter, not full expected PnL.

### 3.2 Variance premium monitor
Compute:
- IV² - RV²

Use over several horizons:
- 6h
- 24h
- 72h

Interpret carefully:
- positive premium may justify premium selling
- but only if jump risk, skew, liquidity, and stress are tolerable

### 3.3 Conditional RV forecast
Starter version:
- weighted blend of recent RV and current absolute-return pressure

Production version should add:
- HAR-RV style forecasting
- regime-conditioned model
- event dummies
- order-flow / perp-funding / basis features
- realized semivariance split

### 3.4 Event / jump premium estimation
Combine:
- event premium proxy from Module 2
- IV minus forecast RV residual

This gives a rough split between:
- baseline vol
- event premium
- jump premium

### 3.5 Surface-relative cheap/rich scoring
Within each:
- hour × expiry bucket × type

Compute local z-score:
- contract IV relative to local bucket median and std

Outputs:
- `cheap`
- `fair`
- `rich`

This is more useful than global IV ranking because options must be judged relative to their local surface neighborhood.

## Failure modes
- EV proxy is not a substitute for pathwise PnL simulation
- RV forecast quality determines everything
- local z-scores can be unstable in thin buckets
- chain mispricings may be execution-untradeable

---

# Module 4 — Execution and Risk

## Purpose
Prevent intelligent analytics from turning into unintelligent trades.

Questions:
- Is this even tradable?
- Are we too short gamma?
- What happens under gap + vol shock?
- How should size depend on liquidity?
- How do we aggregate risk across expiries / underlyings?

## Core submodules

### 4.1 Spread / slippage guardrails
Simple rules:
- maximum spread in bps of mid
- minimum OI
- minimum 24h volume

Output:
- `tradable_flag`

Later upgrades:
- impact curve estimate
- queue / maker-taker model
- passive vs aggressive fill choice

### 4.2 Max short-gamma limits
At book level:
- if net gamma < threshold, raise breach

Needed because:
- short premium can look attractive while hiding explosive intraday hedge risk
- gamma should be capped at both instrument and portfolio level

### 4.3 Stress tests
Run:
- spot gap shocks
- IV up/down shocks
- combined stress matrix

Outputs:
- worst-case approximate PnL
- breach flags
- scenario concentration diagnostics

### 4.4 Liquidity-weighted sizing
Base idea:
- larger size where OI and recent activity are higher
- smaller size where spread is wider

Starter score:
log(1 + OI) + log(1 + volume) - log(1 + spread_bps)

Production upgrades:
- realized fill history
- participation-rate cap
- venue throttling and margin-aware scaling

### 4.5 Portfolio aggregation
Aggregate risk by:
- hour
- currency
- expiry / TTE bucket
- option type

Outputs:
- portfolio delta/gamma/theta/vega
- expiry concentration
- notional concentration
- short-gamma hotspots

## Failure modes
- volume_24h is not true interval liquidity
- OI does not guarantee executable size
- stress matrix still relies on approximate Greeks unless repriced

---

# Recommended build order

1. Stabilize ingestion, derived fields, and ATM extraction
2. Finish Module 1 state tables and stress ladders
3. Finish Module 2 IV / skew / term / regime tables
4. Add Module 3 RV forecasting and cheap/rich scoring
5. Gate everything through Module 4 before any signal is allowed
6. Only then add trade selection / execution logic

---

# Required next upgrades for a serious production version

- Own Black-style repricer with contract multipliers and full scenario repricing
- Surface interpolation by delta and expiry
- HAR-RV / regime-conditioned realized vol forecasting
- Optional event calendar inputs
- Execution simulator with spread / fill assumptions
- Portfolio margin approximation
- Signal attribution and post-trade decomposition
