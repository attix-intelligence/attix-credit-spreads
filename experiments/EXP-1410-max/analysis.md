# EXP-1410-max: Correlation Monitor — Analysis

## Results
- **30 elevated-correlation days** detected across 1,512 trading days (2%)
- DD reduction: minimal on synthetic data (correlations spike briefly)
- **DCC estimator and alert system operational**

## Key Finding
The monitoring system correctly identifies correlation spikes during crisis periods. On synthetic data the effect is small because:
1. Synthetic correlations spike for only ~20-30 days
2. Real multi-strategy portfolios have sustained correlation breakdowns lasting months
3. The value is **insurance-like**: rarely needed, critical when it triggers

## Production Value
- Monitor avg pairwise correlation across EXP-880 sub-strategies
- Alert when any pair exceeds 0.50 (diversification breakdown)
- Auto-delever from 100% to 30% as correlation rises from 0.35 to 0.50
- DCC estimator provides smoother, less noisy correlation tracking than rolling window

## Integration
Feeds into: `compass/drawdown_protection.py` (correlation-conditional threshold tightening) and `compass/live_trading_blueprint.py` (pre-trade correlation check).
