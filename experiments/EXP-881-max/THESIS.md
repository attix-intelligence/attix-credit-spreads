# EXP-881-max: Combined Strategy CPCV Validation

## Hypothesis

EXP-880 validated the crisis-hedged strategy (76.9% CAGR, Sharpe 4.97,
10.2% DD).  EXP-920 validated robustness of individual components.
This experiment validates the COMBINED strategy (crisis hedge V2 +
regime leverage + production ensemble) using CPCV — the gold standard
for time-series overfitting detection.

## What This Adds Beyond EXP-920

- EXP-920 used simple bootstrap on yearly returns
- EXP-881 uses **monthly granularity** with proper purging and embargo
- EXP-881 sweeps **all 3 key parameters simultaneously** (min_scale,
  leverage, delever thresholds) to find cliff edges
- EXP-881 computes **Calmar ratio CIs** (not just Sharpe/CAGR/DD)

## Success Criteria

- CPCV 5-fold: ≥4/5 folds with positive OOS Sharpe
- Bootstrap Sharpe 95% CI lower bound > 1.5
- No parameter within ±20% causes >40% Sharpe collapse
- Combined Calmar 95% CI lower bound > 2.0
