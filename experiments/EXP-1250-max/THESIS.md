# EXP-1250-max: Sentiment Regime Detector

## Hypothesis

Combining put/call ratio, VIX term structure slope, SKEW index, and
credit spreads into a composite sentiment index detects fear/greed
regimes earlier than VIX alone, enabling better timing for EXP-880.

## Components

1. **Put/call ratio** (25%) — high ratio = fear, inverted to score
2. **VIX term slope** (30%) — backwardation = fear, contango = calm
3. **SKEW index** (20%) — high SKEW = tail fear, inverted
4. **Credit spreads** (25%) — wide = fear, inverted

Each normalised via rolling z-score to [-1, +1], then weighted-averaged.

## Methods

- **CUSUM changepoint detection** on composite for regime shifts
- **Contrarian signals** at extremes (fear = buy, greed = reduce)
- **Timing filter backtest** for EXP-880 (1.5x in fear, 0.5x in greed)
- **Comparison vs VIX-only** (lead time measurement)

## Status: COMPLETE
- compass/sentiment_regime.py: 390+ lines
- tests/test_sentiment_regime.py: 35 tests, all passing
