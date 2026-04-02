# EXP-1300-max: Mean Reversion Z-Score Strategy

## Hypothesis
Bollinger Band z-score < -2 with RSI divergence + volume spike → high-probability put spread entry. Mean reversion to z=0 captures credit spread premium with improved timing.

## Module
`compass/mean_reversion_zscore.py` — 42/42 tests passing

## Entry
z20 < -2 AND bullish RSI divergence (price new low, RSI higher low) AND volume > 2× avg

## Exit
z20 crosses above 0 (mean reversion), or z20 < -3.5 (stop), or 20-day max hold
