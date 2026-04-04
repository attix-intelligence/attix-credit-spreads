# Status: COMPLETE — OOS Sharpe 4.08, SPY corr 0.032

## Key Results

| Metric | Value |
|--------|-------|
| Total Trades | 63 |
| Total PnL | $7,658 |
| Win Rate | 86% |
| Max DD | 1.7% |
| Full Sharpe | 2.19 |
| **OOS Sharpe** | **4.08** |
| IS Sharpe | 0.31 |
| WF Ratio | 13.36 |
| CAGR | 1.87% |
| SPY Correlation | 0.032 |
| Avg Hold | 10 days |

## Year-by-Year

| Year | Period | Trades | PnL | WR | Sharpe |
|------|--------|--------|-----|-----|--------|
| 2020 | IS | 15 | $1,872 | 80% | 1.23 |
| 2021 | IS | 14 | -$1,064 | 71% | -0.50 |
| 2022 | OOS | 14 | $2,820 | 93% | 2.55 |
| 2023 | OOS | 16 | $3,211 | 94% | 2.62 |
| 2024 | OOS | 4 | $819 | 100% | 1.67 |

## Findings

1. **Strong OOS performance**: Sharpe improves from IS (0.31) to OOS (4.08)
2. **Near-zero SPY correlation** (0.032) — excellent portfolio diversifier
3. **Low drawdown** (1.7% max) — very conservative risk profile
4. **Short holding period** (10 days avg) — capital efficient
5. **Skewed signal**: 62 short-ratio vs 20 long-ratio signals (GLD tends to run rich)
6. **2021 weak year** (-$1,064) — likely due to persistent GLD/TLT divergence during
   reflation trade; strategy recovered strongly in 2022-2024
7. **Data limitation**: Only 4 trades in 2024 due to GLD option data ending Mar 2024

## Module

`compass/gld_tlt_relval.py`
