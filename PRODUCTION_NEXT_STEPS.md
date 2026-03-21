# Production next steps

## What was added now
- S3-aware parquet ingestion and partition filtering
- delta/tenor surface table
- HAR-RV and regime-conditioned RV forecast
- Plotly/Streamlit page split by engine
- contract-level signal table gated by execution filters

## What is still only approximate
- scenario PnL is Greek-based, not full repricing
- delta bucket interpolation is approximate
- event premium uses front/back IV spread proxy
- signal EV is still a proxy, not fully pathwise expected PnL

## Recommended hardening order
1. Add your own Black-style repricer
2. Use exact delta-based surface interpolation per timestamp
3. Add realized semivariance / jump filters
4. Add maker/taker and impact assumptions
5. Add portfolio margin approximation
6. Backtest signal table against actual realized path and execution assumptions
