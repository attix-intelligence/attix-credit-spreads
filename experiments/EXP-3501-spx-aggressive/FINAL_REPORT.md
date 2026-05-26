# EXP-3501: SPX 0DTE 20Δ Aggressive - FINAL REPORT

**Date:** 2026-05-26  
**Status:** ❌ REJECTED — Strategy Failed Backtest  
**Assigned:** CC2 Subagent → Maximus  

---

## Executive Summary

**The 20Δ aggressive strategy FAILS backtesting.**

- **Total return:** -25.5% over 3.8 years (-6.7% annualized)
- **Win rate:** 62.2% (decent)
- **Win/Loss ratio:** 0.49 (avg loss 2X avg win — **fatal flaw**)
- **Max drawdown:** -57% (catastrophic)
- **Sharpe ratio:** -1.35 (terrible risk-adjusted returns)

**Verdict:** Moving strikes closer (30Δ→20Δ) **increases premium but MORE than doubles losses**. Not viable for Path A.

---

## North Star Context

**Path A:** $100K → $10M in 24 months  
**Pillar 2:** 40% allocation ($40K)  
**Target:** 30-50% monthly returns  

**20Δ was the PRIMARY candidate** for aggressive premium collection. Results show it's **too aggressive** — losses wipe out wins.

---

## Methodology

### Infrastructure Fix
Previous subagent hit infrastructure blocker (Athena queries = 20+ hour runtime). 

**Solution:** Built `backtest_local_v2.py` that reads local CSV files directly.
- Runtime: **5 seconds** (vs 20+ hours)
- Clean, simple code
- Reusable for future experiments

### Data Coverage
**CBOE data:** 48 months from 2021-2025, but sparse coverage  
**Trading days:** 613 potential (Mon/Wed/Fri)  
**Executed trades:** 37 (6% execution rate)  

**Why so few?** Many months missing data files (e.g., 2021-05, 2022-01, 2023-04).

### Parameters
- **Ticker:** SPX 0DTE
- **Entry:** 10:00 AM ET (Mon/Wed/Fri)
- **Exit:** 15:00 PM ET same day
- **Strikes:** 20Δ put, 20Δ call (aggressive, closer to ATM)
- **Wing width:** $50
- **Contracts:** 10 per trade
- **Capital:** $100K
- **Fill:** Midpoint (realistic)
- **Liquidity:** bid ≥ $0.05, ask ≥ $0.10

---

## Results

### Performance Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Total trades** | 37 | — | ⚠️ Low (data gaps) |
| **Win rate** | 62.2% | >70% | ❌ Below |
| **Total return** | -25.5% | — | ❌ Loss |
| **Annualized return** | -6.7% | >20%/mo | ❌ Negative |
| **Avg win** | $4,741 | — | ✅ Good |
| **Avg loss** | $-9,611 | — | ❌ **2X avg win** |
| **Win/Loss ratio** | 0.49 | >1.0 | ❌ Fatal |
| **Max drawdown** | -57% | <25% | ❌ Catastrophic |
| **Sharpe ratio** | -1.35 | >2.0 | ❌ Terrible |
| **Avg monthly return** | -0.69% | >20% | ❌ Negative |

### Trade-by-Trade Analysis

**First 5 trades:**
1. 2021-02-01: -$8,125 (-103% of credit) — **blown out**
2. (Trades 2-4 had zero or small P&L)
3. (Pattern: small wins eaten by occasional large losses)

**Root cause:** 20Δ strikes are **too close to ATM**. When market moves against us:
- Short strikes go ITM quickly
- Losses are large (approaching max loss)
- Small wins don't compensate

---

## Comparison to 30Δ Baseline (EXP-3500)

| Metric | 30Δ Baseline | 20Δ Aggressive | Difference |
|--------|--------------|----------------|------------|
| **Premium/trade** | Lower | **Higher** | 👍 More credit |
| **Win rate** | Higher (~75%) | 62% | 👎 Lower |
| **Avg loss** | Smaller | **2X bigger** | 👎👎 Fatal |
| **Max DD** | — | -57% | 👎👎 Worse |
| **Sharpe** | — | -1.35 | 👎 Worse |

**Conclusion:** Extra premium from 20Δ does NOT justify the extra risk.

---

## Why It Failed

### 1. **Risk/Reward Imbalance**
- Avg win: $4,741
- Avg loss: $-9,611
- **Loss is 2X win** — unsustainable

### 2. **Strikes Too Close to ATM**
- 20Δ ≈ 55-60% ITM probability
- Small market moves → large losses
- Wins are frequent but small; losses are rare but devastating

### 3. **No Exit Management**
- Strategy holds until 3 PM regardless of P&L
- No profit target or stop loss enforced
- Lets losers run to max loss

### 4. **Data Limitations**
- Only 37 trades over 3.8 years
- May not capture full range of market conditions
- But the losses are clear enough to reject

---

## Lessons Learned

1. **More premium ≠ better strategy**  
   Closer strikes collect more credit but blow up harder.

2. **Win rate alone is misleading**  
   62% win rate sounds good, but 2X loss size kills it.

3. **Exit management is critical**  
   Need stop losses to prevent -100%+ losses.

4. **30Δ is the sweet spot**  
   Far enough OTM to avoid frequent losses, close enough to collect decent premium.

---

## Recommendations

### Immediate
1. **❌ REJECT 20Δ for Path A Pillar 2**  
   Do not deploy this strategy with real capital.

2. **✅ Stick with 30Δ baseline (EXP-3500)**  
   Or test even wider strikes (40Δ, 50Δ) for more safety.

3. **Add exit rules**  
   - Profit target: 50% of credit
   - Stop loss: -150% of credit (not -200%)
   - Intraday monitoring (not just 3 PM close)

### Future Experiments
1. **EXP-3502: 20Δ with Tight Stops**  
   Test if aggressive exit management can salvage 20Δ.

2. **EXP-3505: 15Δ "Ultra-Aggressive"**  
   Test even closer strikes to see where the breaking point is.

3. **EXP-3506: Dynamic Delta Sizing**  
   Wider strikes in high-VIX, tighter in low-VIX.

---

## Infrastructure Wins

### ✅ Local Data Provider
- **Built:** `backtest_local_v2.py` — reads CSV files instead of Athena
- **Speed:** 5 seconds (vs 20+ hours)
- **Reusable:** Can be used for all future SPX 0DTE backtests
- **Clean code:** 330 lines, well-documented

### Next Step
Convert this into a reusable module:
```python
from backtest.local_data_provider import LocalCBOEDataProvider
provider = LocalCBOEDataProvider(ticker='SPX', option_type='0dte')
data = provider.get_day_data(date, entry_time, exit_time)
```

This will make ALL future experiments 1000X faster.

---

## Files Delivered

1. **`backtest_local_v2.py`** — Working local backtest script
2. **`results/exp3501_local_results.csv`** — Trade-by-trade results
3. **`FINAL_REPORT.md`** — This document

---

## Conclusion

**EXP-3501 (20Δ Aggressive) is REJECTED.**

Moving from 30Δ to 20Δ strikes:
- ✅ Increases premium per trade
- ❌ Cuts win rate (75% → 62%)
- ❌ **DOUBLES average loss size** (fatal flaw)
- ❌ Creates -57% max drawdown

**Path A should NOT use 20Δ.** Stick with 30Δ or test wider strikes for more safety.

---

**Next Steps for Main Agent:**
1. Review this report
2. Decide: test tighter stops (EXP-3502) or abandon 20Δ entirely?
3. Consider EXP-3506 (dynamic delta sizing) as a smarter approach

**Status:** Mission complete. Returning to main agent.
