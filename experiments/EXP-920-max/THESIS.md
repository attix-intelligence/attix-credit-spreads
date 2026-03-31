# EXP-920-max: Walk-Forward Robustness Validation

## Hypothesis

EXP-880's 76.9% CAGR with Sharpe 4.97 and 10.2% max DD is either a
robust finding or an overfit artifact.  Before allocating real capital,
we need rigorous out-of-sample validation to determine the probability
that this performance persists.

## Validation Battery

1. **Purged K-fold CV** — train/test splits with embargo gap
2. **Combinatorial purged CV (CPCV)** — all valid train/test combos
3. **Walk-forward** — expanding and sliding window
4. **Bootstrap confidence intervals** — 10K resamples for Sharpe, CAGR, DD
5. **Parameter sensitivity** — sweep ±20%, check graceful degradation
6. **Noise injection** — add return noise, measure robustness
7. **Probability of forward success** — P(CAGR > 50%) in random future year

## Success Criteria

- Bootstrap 95% CI for Sharpe > 2.0 (lower bound)
- Walk-forward OOS Sharpe > 60% of in-sample
- No parameter causes >50% performance collapse at ±20% change
- P(CAGR > 50% in future year) > 60%
