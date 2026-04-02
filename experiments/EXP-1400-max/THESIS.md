# EXP-1400-max: Walk-Forward Ensemble Optimizer

## Hypothesis
Walk-forward optimization of ensemble weights adapts to changing regimes and outperforms static allocation by finding optimal strategy weights that maximize Sharpe while capping drawdown at 12%.

## Module
`compass/wf_ensemble_optimizer.py` — 35/35 tests passing

## Method
- Expanding window: optimize weights on train, evaluate on test (60-day OOS)
- Projected gradient ascent on Sharpe with DD penalty
- Compare: WF optimizer vs equal weight vs risk parity vs Bayesian selector
- Track: weight stability, turnover, OOS degradation
