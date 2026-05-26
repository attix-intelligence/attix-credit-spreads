# EXP-3504: SPX 0DTE with XLK IV Filter

## Strategy

**Baseline:** 20Δ iron condors (aggressive)  
**Filter:** Skip trade when VIX > 25% (proxy for XLK IV / tech sector risk)

## Hypothesis

This strategy was the QQQ winner in previous testing:
- Sharpe 2.10
- Avoided 3/5 major tech events
- Lower trade frequency but higher quality

Validate whether the same filter works on SPX.

## North Star Context

**Path A:** $100K → $10M in 24 months  
**Pillar 2:** Risk management filters that skip catastrophic events

Tech concentration risk is real. When XLK (tech sector) is volatile:
- QQQ bleeds (ρ = 0.97 per EXP-2930)
- SPX can suffer from tech contagion
- Skipping these days may preserve capital

## Parameters

- Ticker: SPX
- Entry: 9:45 AM ET, Mon/Wed/Fri
- Strikes: 20Δ short (aggressive baseline)
- Filter: Skip if VIX > 25%
- Wing width: $50
- Exit: 50% profit target OR 3:00 PM ET OR -200% stop
- Period: 2021-2025 (CBOE data)

## Success Criteria

- Sharpe > 2.0
- Win rate > 80%
- Monthly return > 15%
- Max DD < 15%

## Data Source

- CBOE Athena data (real greeks, real prices)
- VIX from Yahoo Finance (proxy for XLK IV)

## Run

```bash
cd /home/node/.openclaw/workspace/pilotai-credit-spreads/experiments/EXP-3504-spx-xlk-iv-filter
python3 backtest.py 2>&1 | tee backtest_run.log
```

## Expected Output

- `results/EXP-3504_trades.csv` - All trades
- `results/EXP-3504_report.html` - Performance report
- `backtest_run.log` - Execution log
