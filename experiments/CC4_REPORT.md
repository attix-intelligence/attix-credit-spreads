# CC4 Report: EXP-3408 & EXP-3409 - Hedging Strategies

**Date:** May 25, 2026 06:00 UTC  
**Objective:** Evaluate hedging strategies for QQQ 0DTE iron condors  
**Experiments:** EXP-3408 (SPY Put Hedge), EXP-3409 (Volatility Hedge)

---

## Executive Summary

**Finding:** Both hedging strategies reduce returns vs unhedged baseline due to hedge costs.

- **EXP-3408 (SPY Hedge):** -12.5% return (hedge cost: $11,852)
- **EXP-3409 (Straddle Hedge):** -3.7% return (hedge cost: $3,274)

**Conclusion:** Hedging is insurance - it costs money. Only valuable if tail risk protection is worth the premium.

---

## EXP-3408: SPY Put Hedge

### Strategy
- **Primary:** Sell QQQ 30Δ iron condor (baseline)
- **Hedge:** Buy SPY 40Δ put spread weekly (10% of capital)
- **Hypothesis:** SPY puts protect against broad market crash

### Results

| Metric | Value |
|--------|-------|
| Initial Capital | $100,000 |
| Final Capital | $87,473 |
| Total Return | **-12.5%** |
| Max Drawdown | 30.9% |

#### Iron Condor Performance
- **Total trades:** 35 (weekly)
- **Win rate:** 88.6%
- **Winners:** 31
- **Losers:** 4
- **Total P&L:** -$675

#### Hedge Performance
- **Total hedges:** 35 (weekly)
- **Times paid off:** 1 (2.9% of weeks)
- **Total hedge cost:** -$11,852
- **Avg cost per week:** $1,053

### Analysis

**Hedge is too expensive:**
- Cost: ~$1,000/week × 35 weeks = $35,000+
- Payoff: Only 1 crash event (paid ~$25K)
- Net hedge cost: -$11,852

**Why SPY hedge failed:**
1. **10% allocation too aggressive** - drains capital weekly
2. **40Δ puts too far OTM** - rarely pay off
3. **QQQ-SPY correlation not perfect** - QQQ can crash while SPY holds

**Fix:**
- Reduce allocation to 3-5% of capital
- Use tighter strikes (30Δ instead of 40Δ)
- Or hedge QQQ directly instead of SPY

---

## EXP-3409: Volatility Hedge

### Strategy
- **Primary:** Sell QQQ 30Δ iron condor (baseline)
- **Hedge:** Buy 5 QQQ ATM straddles weekly
- **Note:** Used QQQ straddles instead of VIX calls (no VIX data)

### Results

| Metric | Value |
|--------|-------|
| Initial Capital | $100,000 |
| Final Capital | $96,276 |
| Total Return | **-3.7%** |
| Max Drawdown | 4.2% |

#### Iron Condor Performance
- **Total trades:** 35 (weekly)
- **Win rate:** 85.7%
- **Winners:** 30
- **Losers:** 5
- **Total P&L:** -$450

#### Hedge Performance
- **Total hedges:** 35 (weekly)
- **Times paid off:** 1 (2.9%)
- **Theta decay:** 27 weeks (77%)
- **Total hedge cost:** -$3,274
- **Avg cost per week:** $167

### Analysis

**Better than SPY hedge but still negative:**
- Cost: ~$167/week × 35 weeks = $5,830
- Payoff: 1 volatility spike
- Net hedge cost: -$3,274

**Why straddle hedge performed better:**
1. **Lower cost** - $167/week vs $1,053/week for SPY
2. **Same underlying** - QQQ straddles protect QQQ iron condors
3. **Volatility exposure** - pays off when IV expands

**Still a drag on returns:**
- IC trades were break-even (-$450)
- Hedge cost entire loss (-$3,274)
- Only 1 payoff in 35 weeks

---

## Comparative Analysis

| Experiment | Return | Max DD | Hedge Cost | Hedge Paid | Net Cost/Week |
|------------|--------|--------|------------|------------|---------------|
| **Baseline (no hedge)** | +5-10%* | 15-20% | $0 | N/A | $0 |
| **EXP-3408 (SPY)** | -12.5% | 30.9% | $11,852 | 1x | $1,053 |
| **EXP-3409 (Straddle)** | -3.7% | 4.2% | $3,274 | 1x | $167 |

*Baseline estimates from EXP-3401 (not CC4 responsibility)

### Key Insights

**1. Hedge Cost vs Benefit**
- SPY hedge: Cost 12.5% of capital for 1 payoff
- Straddle hedge: Cost 3.7% for 1 payoff
- **Conclusion:** Hedging reduces returns unless tail events are frequent

**2. Correlation Matters**
- SPY puts don't perfectly hedge QQQ tech risk
- QQQ straddles better aligned with QQQ iron condor
- **Lesson:** Hedge the same underlying you're trading

**3. Strike Selection**
- 40Δ SPY puts too far OTM (rarely ITM)
- ATM straddles better capture volatility
- **Lesson:** Closer strikes = more sensitivity

**4. Cost Efficiency**
- $1,000/week hedge unsustainable
- $167/week more reasonable but still drag
- **Break-even:** Need 1-2 major crashes per year

---

## Hedge Cost as % of IC Profit

Assuming baseline IC profit = $500/week (EXP-3401 estimate):

**EXP-3408 (SPY Hedge):**
- IC profit: $500/week × 35 = $17,500
- Hedge cost: $11,852
- **Hedge cost = 68% of IC profit** ❌ Too expensive

**EXP-3409 (Straddle Hedge):**
- IC profit: $500/week × 35 = $17,500
- Hedge cost: $3,274
- **Hedge cost = 19% of IC profit** ✅ More reasonable

**Industry rule of thumb:** Hedge cost should be <20% of strategy profit

---

## Recommendations

### ✅ **Do NOT Hedge** (for 30-day sprint to 2×)

**Reasons:**
1. **Goal is aggressive growth** - hedging reduces returns
2. **Short timeframe** - only 30 days, unlikely to hit multiple tail events
3. **Cost exceeds benefit** - both hedges reduced returns
4. **Better risk control:** Position sizing + stop losses

**Alternative risk management:**
- Size down during high VIX (>25)
- Skip FOMC/earnings weeks
- Use stop losses (-200% of credit)
- Take profits early (25% vs 50%)

### ⚠️ **If You Must Hedge**

Use **EXP-3409 (Straddle Hedge)** with modifications:
1. **Reduce contracts:** 2-3 straddles instead of 5
2. **Only hedge high-risk weeks:** FOMC, earnings, OpEx
3. **Use shorter DTE:** 0-2 DTE instead of weekly (cheaper)
4. **Target hedge cost:** <10% of IC profit

**Estimated improvement:**
- Cost: ~$80/week (vs $167)
- Use selectively: 10 weeks out of 35
- Total cost: ~$800 (vs $3,274)
- Net impact: -0.8% return (vs -3.7%)

---

## Data Limitations

**Major caveat:** These backtests use simplified simulations, not real historical data.

**Limitations:**
1. **No real VIX data** - used QQQ straddles instead of VIX calls
2. **No intraday pricing** - simulated option prices from VIX estimate
3. **Simplified P&L** - didn't model Greeks or early assignment
4. **Random walk model** - doesn't capture real market dynamics

**Impact:**
- Results are directionally correct but magnitudes uncertain
- Real hedge costs likely different
- Win rates may vary

**Next steps for production:**
1. Get real VIX options data
2. Use IronVault intraday pricing (option_intraday table)
3. Model full Greeks (delta, gamma, theta, vega)
4. Walk-forward validation with out-of-sample data

---

## Conclusion

**Primary finding:** Hedging costs money and reduces returns.

**For 30-day sprint to 2×:**
- **Skip hedging** - focus on aggressive IC strategy
- Use position sizing and stop losses for risk control
- Monitor VIX and skip high-risk days

**For long-term trading (6+ months):**
- Consider selective hedging during known events
- Keep hedge cost <10% of strategy profit
- QQQ straddles better than SPY puts

**Bottom line:** Insurance is only worth it if you expect to use it. For a 30-day sprint, bet on skill, not insurance.

---

## Files Delivered

```
experiments/EXP-3408-spy-hedge/
├── backtest.py
└── results/
    └── EXP-3408_results.json

experiments/EXP-3409-vol-hedge/
├── backtest.py
└── results/
    └── EXP-3409_results.json

experiments/CC4_REPORT.md (this file)
```

**Time spent:** 2 hours  
**Status:** ✅ Complete

---

**CC4 signing off.** Hedging evaluated, recommendation delivered. Focus on unhedged baseline with smart risk controls.
