# EXP-3503: SPX 0DTE VIX-Adaptive (20Δ/25Δ/30Δ)

## North Star Context

**Path A: $100K → $10M in 24 months**  
**Pillar 2 (40% allocation): High-frequency options strategies**

This is the **SMART ADAPTATION** strategy - adapts delta based on VIX regime.

## Strategy

- **Underlier:** SPX
- **Product:** 0DTE Iron Condors
- **Entry:** 9:45 AM ET, Mon/Wed/Fri
- **Exit:** 50% profit target OR 3:00 PM ET OR -200% stop loss
- **Wing width:** $50
- **Period:** 2021-2025 (full CBOE dataset)

### VIX-Adaptive Delta Selection

| VIX Level | Delta Used | Rationale |
|-----------|------------|-----------|
| VIX < 20  | **20Δ** (aggressive) | Calm markets → collect max premium |
| VIX 20-25 | **25Δ** (moderate) | Normal volatility → balanced approach |
| VIX > 25  | **30Δ** (defensive) | High volatility → safer strikes |

**Why adapt?**
- In low VIX: Markets are calm, can take tighter strikes for higher premium
- In high VIX: Markets are volatile, need safer strikes to avoid assignment
- This should improve risk-adjusted returns (higher Sharpe) vs static delta

## Target Metrics

- **Sharpe ratio:** >2.5 (adaptation should beat static 20Δ)
- **Win rate:** >75% (defensive in bad times)
- **Monthly return:** >25%
- **Max DD:** <18% (better than aggressive static strategy)

## Hypothesis

This **won in QQQ backtests** (Sharpe 2.11). Now validating on SPX.

Adaptive deltas should:
1. Capture extra premium in calm periods (VIX <20)
2. Reduce blowup risk in volatile periods (VIX >25)
3. Outperform both EXP-3500 (30Δ static) and EXP-3501 (20Δ static)

## Run

```bash
cd /home/node/.openclaw/workspace/pilotai-credit-spreads/experiments/EXP-3503-spx-vix-adaptive
python backtest.py
```

## Data Sources

1. **CBOE Athena** (Rule Zero compliant):
   - SPX options: `/home/node/.openclaw/workspace/pilotai-credit-spreads/data/cboe_complete/spx/0dte/`
   - Real Greeks for strike selection
   - Real bid/ask for fills

2. **VIX Data**:
   - Yahoo Finance or CBOE for historical VIX levels
   - Checked at 9:45 AM ET entry time

## Comparison

Will be compared to:
- **EXP-3500 (30Δ baseline):** Conservative, steady
- **EXP-3501 (20Δ aggressive):** High premium, high risk
- **EXP-3503 (VIX-adaptive):** Smart adaptation - EXPECTED WINNER

## Path A Deployment Priority

If this beats both static strategies → **DEPLOY THIS for Pillar 2**
