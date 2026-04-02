# EXP-1240-max: Volatility Risk Premium Harvester

## Hypothesis

Implied volatility persistently exceeds realised volatility (the VRP).
By systematically selling IV and buying RV across multiple tenors with
regime-conditional sizing and gamma scalping protection, we generate
consistent alpha uncorrelated with directional credit spread strategies.

## Method

1. Compute VRP at 4 tenors: 1W, 2W, 1M, 2M
2. Select optimal tenor based on term structure shape (steepest VRP)
3. Regime sizing: full in calm, reduced in stress, halted in crisis
4. Gamma scalp overlay: delta-hedge frequently to capture convexity
5. Backtest 2020-2025 with realistic execution costs

## Success Criteria

- VRP positive > 70% of months
- Annualised Sharpe > 1.5
- Max DD < 15%
- Correlation with credit spread P&L < 0.3
- Gamma scalp offsets > 30% of tail losses
