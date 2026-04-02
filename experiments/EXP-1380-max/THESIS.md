# EXP-1380-max: Adaptive Greeks-Based Trade Sizing

## Hypothesis

Sizing options trades by Greeks exposure (target portfolio theta, cap
gamma/vega) instead of fixed notional produces better risk-adjusted
returns.  Fixed sizing ignores the fact that a 30-DTE ATM spread has
very different Greeks from a 7-DTE OTM spread.

## Method

1. Set daily theta target ($X/day, scaled by regime and capital)
2. Size each trade to contribute proportional theta
3. Cap gamma and vega at portfolio level (regime-dependent limits)
4. Dynamic delta budget: bull allows +30Δ, bear caps at ±10Δ
5. Compare vs fixed-size and Kelly sizing on same trade set

## Success Criteria

- Sharpe improvement > 15% vs fixed sizing
- Smoother theta income (lower std of daily theta)
- Gamma/vega never exceed regime limits
- DD reduction > 10% vs fixed sizing
