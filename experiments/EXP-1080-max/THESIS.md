# EXP-1080-max: VIX Term Structure Trading

## Hypothesis

VIX futures contango/backwardation predicts SPY options premium direction.
The VIX term structure spends ~70% of time in contango (front < back),
creating a structural roll yield for premium sellers. Backwardation
signals fear and regime shift — time to buy protection, not sell.

## Key Features

1. **Term structure calculator** — slope, spot-to-front, contango %
2. **Regime detector** — contango / flat / backwardation with z-scores
3. **Mean-reversion signals** at extreme z-scores (|z| > 1.5)
4. **Position sizing** scaled by slope magnitude
5. **Backtest** — sell premium in contango, buy protection in backwardation

## Why This Matters for EXP-880

The VIX term structure is a leading indicator for the crisis hedge.
Backwardation often precedes VIX spikes by 1-3 days, giving the crisis
hedge an early warning before the spot VIX crosses the 25 threshold.

## Status: COMPLETE
- compass/vix_term_structure.py: 380+ lines
- tests/test_vix_term_structure.py: 33 tests, all passing
