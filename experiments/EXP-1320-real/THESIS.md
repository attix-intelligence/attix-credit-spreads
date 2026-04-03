# EXP-1320-real: Intraday Vol Clustering — Real Data Re-Backtest

## Hypothesis
Re-backtest EXP-1320 (Intraday Volatility Clustering) using ONLY real
intraday option data from IronVault. The original EXP-1320-max reported
Sharpe 3.05 using `np.random`-generated synthetic 5-min sessions.

## Data Source
- `data/options_cache.db` via `shared.iron_vault.IronVault`
- 1.4M+ real intraday option bars, 2020-2025
- 1,500 real trading sessions analyzed
- NO `simulate_sessions_from_daily()`, NO np.random

## Results — REAL vs SYNTHETIC

| Metric               | Real Data  | Synthetic (EXP-1320-max) |
|---------------------|------------|--------------------------|
| Avg Autocorrelation | **0.0964** | 0.1258                   |
| Expansion→EOD AUC   | **0.4313** | 0.2916                   |
| Standalone Sharpe   | **-14.10** | 3.047                    |
| Trade Sharpe        | **0.92**   | —                        |
| Overlay Improvement | **+66.7pp**| -11.1pp                  |
| Win Rate            | **90.2%**  | —                        |

### Yearly Breakdown (Real Trades)
| Year | Trades | P&L    | Win Rate | Max DD | Sharpe |
|------|--------|--------|----------|--------|--------|
| 2020 | 7      | $20    | 85.7%    | 0.3%   | 0.06   |
| 2021 | 6      | $222   | 100.0%   | 0.0%   | 10.37  |
| 2022 | 6      | -$234  | 66.7%    | 0.4%   | -0.68  |
| 2023 | 7      | $258   | 100.0%   | 0.0%   | 4.48   |
| 2024 | 5      | $162   | 100.0%   | 0.0%   | 7.29   |
| 2025 | 10     | $84    | 90.0%    | 0.2%   | 0.30   |

### Vol Clustering Signals (Real)
- 1,500 real sessions analyzed
- sell_premium: 215 signals, avoid: 8 signals, neutral: 1,277
- Real autocorrelation lower than synthetic (0.096 vs 0.126)
- AUC actually improved (0.431 vs 0.292) — real data shows better
  expansion→EOD prediction than synthetic

## Key Finding
**The synthetic Sharpe of 3.05 is fabricated.** The standalone Sharpe with
real data is deeply negative (-14.10), because the premium-selling proxy
(short vol) gets destroyed by real market moves. The trade Sharpe of 0.92
is more reasonable but still far below 3.05. The overlay result (+66.7pp)
looks good but is based on only 4 signal-matched trades — too few to be
meaningful. Real intraday autocorrelation (0.096) is even lower than the
synthetic estimate (0.126), confirming that option-level intraday clustering
is weak.

## Status
COMPLETE
