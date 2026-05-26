# EXP-3400: QQQ 0DTE Iron Condors — 10 Strategy Sweep

**Created:** May 25, 2026 05:00 UTC  
**Objective:** 2× $100K in 30 days using QQQ 0DTE iron condors  
**Critical Focus:** Mitigate tech concentration risk (NVDA/AAPL/MSFT/GOOGL = 40%+ of QQQ)

---

## CC Session Assignments

### **CC1: Data Validation & QQQ Coverage**
**Task:** Verify IronVault QQQ 0DTE data quality (2023-2024)
- Count QQQ 0DTE contracts (where expiry = quote_date)
- Check bid-ask spread coverage
- Verify Mon/Wed/Fri 0DTE expiries exist
- Measure date coverage (how many trading days?)
- Rule Zero: No synthetic data

**Output:** QQQ_DATA_VALIDATION.md (PASS/FAIL)

---

### **CC2: Baseline + Tech Risk Mitigation (EXP-3401, 3402)**

**EXP-3401: Baseline (Conservative)**
- 30Δ strikes, $10 wings, 9:45 AM entry, 50% profit target
- Standard parameters (no special tech mitigation)
- Benchmark for comparison

**EXP-3402: Tech Earnings Blacklist**
- Same as 3401 BUT skip days when NVDA/AAPL/MSFT/GOOGL report earnings
- Also skip week AFTER earnings (momentum risk)
- Test: Does earnings blacklist improve Sharpe?

**Design questions:**
- How to identify mega-cap earnings days? (use earnings_calendar)
- How much does earnings blacklist reduce trade frequency?
- Does it improve win rate enough to justify fewer trades?

**Output:** Baseline + earnings blacklist configs

---

### **CC3: Dynamic Strike Width (EXP-3403, 3404, 3405)**

**EXP-3403: Wider Strikes During Tech Earnings Season**
- Baseline: 30Δ strikes
- During tech earnings season (Jan, Apr, Jul, Oct): 35Δ strikes
- Hypothesis: Wider strikes = safer during high-uncertainty periods

**EXP-3404: Adaptive Strike Width Based on VIX**
- VIX <15: 25Δ strikes (tighter, more premium)
- VIX 15-25: 30Δ strikes (baseline)
- VIX >25: 35Δ strikes (wider, safer)
- Hypothesis: Volatility-adjusted positioning reduces tail risk

**EXP-3405: Asymmetric Strikes (Tech Hedge)**
- Call side: 25Δ (tighter — QQQ has upward drift)
- Put side: 35Δ (wider — protect against tech selloff)
- Hypothesis: Asymmetry captures upside while protecting downside

**Design questions:**
- How to measure "tech earnings season"? (count of mega-cap earnings/week)
- VIX thresholds: Are 15 and 25 the right levels?
- Asymmetric: Does it sacrifice too much premium for protection?

**Output:** 3 adaptive strike strategies

---

### **CC4: Position Sizing & Exit Rules (EXP-3406, 3407)**

**EXP-3406: Dynamic Position Sizing**
- Baseline: 20 contracts
- During tech earnings season: 10 contracts (50% size reduction)
- High VIX days (>25): 10 contracts
- Calm days (VIX <15): 30 contracts
- Hypothesis: Size down during risk-on periods = lower max DD

**EXP-3407: Fast Exit with Stop Loss**
- Profit target: 25% (take profits faster than 50%)
- Stop loss: -200% of credit received (cut losers early)
- Hypothesis: Early exit + stop = reduce tail risk from tech shocks

**Design questions:**
- Does dynamic sizing improve Sharpe or just reduce absolute returns?
- Is -200% stop too tight? (May stop out of winners during intraday whipsaw)

**Output:** Position sizing + exit rule strategies

---

### **CC5: Hedging & Correlation (EXP-3408, 3409, 3410)**

**EXP-3408: SPY Hedge (Cross-Index)**
- Sell QQQ 30Δ iron condor (collect premium)
- Buy SPY 40Δ put spread (tail hedge, 10% of capital)
- Hypothesis: SPY put hedge protects against QQQ tech crash (but costs premium)

**EXP-3409: VIX Call Hedge**
- Sell QQQ 30Δ iron condor
- Buy 5 VIX calls (OTM, expires in 1 week)
- Hypothesis: VIX spike = QQQ drawdown → hedge pays off

**EXP-3410: Tech Sector Rotation (Defensive)**
- Only trade QQQ on days when XLK (tech sector) IV rank <50th percentile
- Skip high-uncertainty tech days
- Hypothesis: Trade when tech is calm → higher win rate

**Design questions:**
- SPY hedge cost: Does it eat too much profit?
- VIX calls: Expensive protection, worth it?
- XLK IV rank: Is this a good filter for tech calm?

**Output:** 3 hedging strategies

---

## Tech Concentration Risk Mitigation Matrix

| Strategy | Mitigation Approach | Trade-off |
|----------|---------------------|-----------|
| **EXP-3401** | None (baseline) | Full exposure |
| **EXP-3402** | Earnings blacklist | Fewer trades |
| **EXP-3403** | Wider strikes (earnings season) | Lower premium |
| **EXP-3404** | Adaptive strikes (VIX) | Complexity |
| **EXP-3405** | Asymmetric (wider put side) | Less call premium |
| **EXP-3406** | Dynamic sizing (50% on risk days) | Lower absolute returns |
| **EXP-3407** | Fast exit + stop loss | May exit winners early |
| **EXP-3408** | SPY put hedge | Premium cost |
| **EXP-3409** | VIX call hedge | Premium cost |
| **EXP-3410** | XLK IV filter | Fewer trades |

---

## Backtest Parameters (All Experiments)

**Data:**
- Source: IronVault options_cache.db (QQQ contracts)
- Period: Jan 1, 2023 - Dec 31, 2024 (2 years)
- Expiration: 0DTE (quote_date = expiration_date)
- Days: Mon/Wed/Fri (QQQ 0DTE expiries)

**Capital:**
- Starting: $100,000
- Fixed sizing (no compounding) to isolate strategy performance
- Margin: Reg-T (20% of notional)

**Slippage & Costs:**
- Bid-ask spread: Use real IronVault spreads
- Commission: $0.65/contract × 4 legs = $2.60/iron condor
- Slippage: 5% of bid-ask spread (conservative)

**Risk Controls:**
- Max drawdown circuit breaker: 30% (halt trading if account down >30%)
- Daily loss limit: 5% (no new trades if day down >5%)

**Validation:**
- Walk-forward: 6-month train, 1-month test (rolling)
- Out-of-sample: 2024 only (if 2023 used for training)
- Monte Carlo: 1,000 paths with parameter perturbation

---

## Success Criteria

**For strategy to be viable:**
1. Win rate: >75% (QQQ more volatile than SPX → lower baseline)
2. Avg daily profit: >$2,000/day (need $60K profit/month for 2× in 30 days)
3. Max drawdown: <35% (acceptable for aggressive 30-day strategy)
4. Sharpe ratio: >1.5 (annualized)
5. Tech concentration events: Max 2 catastrophic losses (>$20K) in 2 years

**Best experiment:**
- Highest Sharpe ratio
- Win rate >80%
- Max DD <30%
- Passes tech concentration stress test (NVDA earnings, Aug 2023 selloff)

---

## Tech Concentration Stress Tests

**Specific events to analyze:**

1. **NVDA Earnings (May 24, 2023):** Stock up 24% → QQQ +3.5%
2. **AAPL Earnings (Aug 3, 2023):** Stock down 5% → QQQ -2.2%
3. **July 2023 Tech Selloff:** QQQ down 7% in 5 days
4. **MSFT Earnings (Jan 30, 2024):** Stock up 11% → QQQ +2.8%
5. **March 2024 AI Rally:** QQQ up 6% in 3 days (NVDA +40%)

**For each event, measure:**
- Did strategy lose money that day?
- How much? (as % of capital)
- Did it recover within 1 week?
- Would earnings blacklist have avoided it?

---

## Timeline

**Phase 1: Data Validation (CC1) — 30 minutes**
- Verify QQQ 0DTE coverage in IronVault
- If insufficient data → ABORT, recommend Polygon upgrade

**Phase 2: Strategy Design (CC2-CC5 parallel) — 2 hours**
- CC2: Baseline + earnings blacklist
- CC3: Adaptive strikes (3 variants)
- CC4: Position sizing + exit rules
- CC5: Hedging (3 variants)

**Phase 3: Backtest Execution — 3 hours**
- Run all 10 experiments in parallel
- Generate equity curves, trade journals, reports

**Phase 4: Tech Stress Analysis — 1 hour**
- Analyze performance on 5 specific tech events
- Rank strategies by tech-risk-adjusted Sharpe

**Phase 5: Consolidation & Recommendation — 1 hour**
- Top 3 strategies identified
- HTML report with detailed analysis
- Paper trading config ready

**Total ETA: 7.5 hours (complete by 12:30 UTC / 8:30 AM ET)**

---

## Output Structure

```
experiments/EXP-3400_QQQ_0DTE/
├── CC1_QQQ_DATA_VALIDATION.md
├── CC2_BASELINE_EARNINGS.md
├── CC3_ADAPTIVE_STRIKES.md
├── CC4_SIZING_EXITS.md
├── CC5_HEDGING.md
├── [after execution]
│   ├── EXP-3401_baseline_results.json
│   ├── EXP-3402_earnings_blacklist_results.json
│   ├── ... (3403-3410)
│   ├── TECH_STRESS_ANALYSIS.md
│   └── FINAL_RECOMMENDATION.html
```

---

**Starting CC1 data validation NOW.**
