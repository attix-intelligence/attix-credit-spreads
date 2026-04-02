# EXP-1480-max: Reinforcement Learning Portfolio Manager

## Hypothesis

An RL agent trained on portfolio state (positions, P&L, regime, Greeks)
can learn dynamic allocation policies that outperform static optimization
(HRP, equal-weight, risk parity).

## Method

- Lightweight PPO agent (numpy-only, no torch dependency)
- State: portfolio metrics + regime + market features (10-dim)
- Action: allocation weights across N strategies (softmax)
- Reward: risk-adjusted return with drawdown penalty
- Train: 2020-2023, validate: 2024-2025
- Compare vs HRP, equal-weight, risk parity baselines

## Success Criteria

- RL Sharpe > best baseline Sharpe by 10%
- RL max DD < worst baseline DD
- Learned policy interpretable (regime-dependent allocations)
- OOS (2024-2025) performance within 30% of IS
