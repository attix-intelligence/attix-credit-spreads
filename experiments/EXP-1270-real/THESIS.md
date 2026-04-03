# EXP-1270-real: Adaptive Stop-Loss — Real Data Re-Backtest

## Hypothesis
Re-backtest EXP-1270 (Adaptive Stop-Loss) using ONLY real options data from
IronVault (options_cache.db). The original EXP-1270-max reported Sharpe 5.25
using synthetic/heuristic trade data.

## Data Source
- `data/options_cache.db` via `shared.iron_vault.IronVault`
- SPY daily option prices, 2020-2025 (5.9M daily bars)
- NO synthetic data, NO np.random for prices/returns

## Results — REAL vs SYNTHETIC

| Metric       | Real Data | Synthetic (EXP-1270-max) |
|-------------|-----------|--------------------------|
| Sharpe      | **-0.25** | 5.25                     |
| CAGR        | **-0.1%** | 163.1%                   |
| Max DD      | **1.1%**  | 3.2%                     |
| Win Rate    | **90.2%** | —                        |
| Trades      | 41        | —                        |

### Yearly Breakdown (Real)
| Year | Trades | P&L      | Win Rate | Max DD | Sharpe |
|------|--------|----------|----------|--------|--------|
| 2020 | 7      | $20      | 85.7%    | 0.3%   | 0.06   |
| 2021 | 6      | $222     | 100.0%   | 0.0%   | 10.37  |
| 2022 | 6      | -$1,020  | 66.7%    | 1.1%   | -1.03  |
| 2023 | 7      | $258     | 100.0%   | 0.0%   | 4.48   |
| 2024 | 5      | $162     | 100.0%   | 0.0%   | 7.29   |
| 2025 | 10     | $84      | 90.0%    | 0.2%   | 0.30   |

### Adaptive Stop Optimization (Real)
Best strategy: **trailing_regime** (Sharpe 4.34, WR 90.2%)

## Key Finding
**The synthetic Sharpe of 5.25 is dramatically inflated.** Real data produces
an overall Sharpe of -0.25 due to 2022 bear market losses. The high win rate
(90.2%) masks small average gains that don't compensate for occasional large
losses. The trailing_regime stop would improve P&L from -$274 to +$1,099 —
confirming the value of adaptive stops, but at far more modest Sharpe (4.34
per-trade, not 5.25 portfolio-level).

## Status
COMPLETE
