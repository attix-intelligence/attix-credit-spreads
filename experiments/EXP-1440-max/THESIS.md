# EXP-1440-max: Market Regime Transition Predictor

## Hypothesis

A Hidden Semi-Markov Model (HSMM) with duration-dependent transitions
predicts regime changes 1-5 days ahead, enabling preemptive position
adjustments that outperform reactive switching.

## Key Innovation: Duration Modeling

Standard HMMs assume geometric (memoryless) durations. The HSMM adds:
- Per-regime expected durations (bull ~120d, crisis ~15d)
- Minimum duration before transitions allowed
- Hazard rate that increases with time in regime
- P(exit) rises as regime exceeds expected duration

## Components

1. **HSMM detector** — duration-adjusted transition matrix + Gaussian emissions
2. **Transition forecasting** — P(regime_t+k) for k = 1-5 days
3. **Early-warning signals** — warn_exit (P>30%), imminent_exit (P>50%)
4. **Preemptive vs reactive backtest** — measures lead time and PnL improvement

## Status: COMPLETE
- compass/regime_transition.py: 450+ lines
- tests/test_regime_transition.py: 35 tests, all passing
