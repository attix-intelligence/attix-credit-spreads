# EXP-3501: SPX 0DTE Aggressive (20Δ)

## North Star Context

**Path A: $100K → $10M in 24 months**  
**Pillar 2 (40% allocation): High-frequency options strategies**

This is the **TARGET STRATEGY** for Pillar 2.

## Strategy

- **Underlier:** SPX
- **Product:** 0DTE Iron Condors
- **Delta:** 20Δ (AGGRESSIVE - tighter strikes than 30Δ baseline)
- **Entry:** 9:45 AM ET, Mon/Wed/Fri
- **Exit:** 50% profit target OR 3:00 PM ET OR -200% stop loss
- **Wing width:** $50
- **Period:** 2021-2025 (full CBOE dataset)

## Why 20Δ vs 30Δ?

| Metric | 30Δ (Baseline) | 20Δ (Aggressive) |
|--------|----------------|------------------|
| Strikes | Further OTM | Closer to ATM |
| Premium | Lower | **Higher** |
| Win rate | Higher (~75-80%) | Lower (~65-75%) |
| Risk | Lower | **Higher** |
| Target | Steady income | **Max returns** |

**20Δ is aggressive:** Collect more premium, accept more risk, aim for 30-50% monthly returns.

## Target Metrics

- **Sharpe ratio:** >2.0
- **Win rate:** >70% (lower than 30Δ but acceptable)
- **Monthly return:** >30% (aggressive target)
- **Max DD:** <25%

## Run

```bash
cd /home/node/.openclaw/workspace/pilotai-credit-spreads/experiments/EXP-3501-spx-aggressive
python backtest.py
```

## Data Source

CBOE Athena (Rule Zero compliant):
- `/home/node/.openclaw/workspace/pilotai-credit-spreads/data/cboe_complete/spx/0dte/`
- Real Greeks for strike selection
- Real bid/ask for fills

## Comparison

This will be compared to EXP-3500 (30Δ baseline) to determine:
1. Is the extra premium worth the extra risk?
2. Does 20Δ meet Path A Pillar 2 targets?
3. Should we deploy 20Δ or 30Δ for live trading?
