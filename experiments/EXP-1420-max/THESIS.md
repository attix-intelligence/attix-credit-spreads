# EXP-1420-max: Transformer Price Predictor

## Hypothesis

A lightweight transformer (4 layers, 64-dim, 4 heads) trained on 20-day lookback windows of OHLCV + VIX + put/call ratio can predict next-day SPY direction with >55% accuracy out-of-sample, outperforming XGBoost which sees only flattened features.

## Why Transformers

- Capture sequential dependencies in price patterns (regime transitions)
- Self-attention weights reveal which past days matter most for prediction
- Positional encoding preserves temporal order (unlike tree models)
- Causal masking prevents future information leakage

## Architecture

- Input: 20-day × 8 features (OHLCV + VIX + volume ratio + returns)
- Positional encoding: sinusoidal
- 4 transformer encoder layers, 64 hidden dim, 4 attention heads
- Causal mask: each position only attends to prior positions
- Output: sigmoid → P(up tomorrow)

## Implementation

Pure numpy (no PyTorch dependency). Forward pass + gradient-free training via evolutionary strategy (CMA-ES style) or simple random search on small parameter space.

## Success Criteria

- OOS accuracy > 55%
- Sharpe as signal > 1.0
- Beats XGBoost baseline accuracy
