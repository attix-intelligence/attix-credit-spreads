# EXP-3400: CC Session Consultation Plan

**Created:** May 25, 2026 04:40 UTC  
**Purpose:** Consult 5 CC sessions to design robust 0DTE iron condor backtests  
**Mandate:** NO SYNTHETIC DATA — Rule Zero absolute

---

## CC Session Assignments

### **CC1: Data Validation & Rule Zero Enforcement**
**Task:** Verify IronVault SPX 0DTE data quality
- Check: Does IronVault have SPX 0DTE data for 2023-2024?
- Verify: Bid-ask spreads present (not mid-price only)
- Confirm: Volume/OI available (even if sparse)
- Flag: Any synthetic data contamination
- Output: Data quality report (PASS/FAIL for each date)

**Files to check:**
- `data/options_cache.db` (IronVault database)
- Schema: Check for 0DTE expiry dates (same-day)
- SPX coverage: Count contracts per day

**Expected issues:**
- 0DTE may not exist pre-2022 (Cboe launched Mon/Wed in 2022)
- May need to adjust backtest period to 2022-2024

---

### **CC2: Baseline + Aggressive Strikes (EXP-3401, EXP-3402)**
**Task:** Design robust backtest for baseline and aggressive strike configurations

**EXP-3401 (Baseline: 30Δ strikes):**
- Entry logic: How to select 30Δ strikes at 9:45 AM?
- Exit logic: 50% profit or 3:30 PM — which triggers first?
- Edge cases: What if SPX gaps >3% at open?
- Slippage: How to model bid-ask spread execution?
- Position sizing: 20 contracts on $100K — margin calculation

**EXP-3402 (Aggressive: 20Δ strikes):**
- Strike selection: 20Δ vs 30Δ — how much more premium?
- Risk: How often do 20Δ strikes get breached vs 30Δ?
- Trade-off: Higher premium vs lower win rate — expected value?

**Output:** 
- Backtest config YAMLs for EXP-3401 and EXP-3402
- Parameter validation (delta ranges, entry times, exit rules)

---

### **CC3: Wing Width & Entry Timing (EXP-3403, EXP-3404, EXP-3405)**
**Task:** Optimize wing width and entry timing

**EXP-3403 (Wider Wings: $100 vs $50):**
- Risk-reward: Does $100 wing reduce losses enough to justify lower premium?
- Capital efficiency: Wider wings = more margin — how many contracts fit?

**EXP-3404 (Early Entry: 9:35 AM):**
- IV behavior: Does morning IV spike justify 9:35 vs 9:45 entry?
- Gap risk: What's the worst-case gap at open? (check historical)

**EXP-3405 (Late Entry: 10:30 AM):**
- Calmness: Does 10:30 reduce whipsaw? (measure intraday vol)
- Premium decay: How much IV decays by 10:30? (lost edge?)

**Output:**
- Wing width analysis (max loss vs premium collected)
- Intraday IV decay curve (9:30 AM → 3:30 PM)
- Entry time recommendation

---

### **CC4: Exit Strategies & Risk Management (EXP-3406, EXP-3407, EXP-3410)**
**Task:** Design robust exit rules and hedging

**EXP-3406 (Fast Exit: 25% profit target):**
- Frequency: How often does 25% hit vs 50%?
- Risk: Does early exit reduce tail risk?
- Trade-off: Smaller winners vs lower max DD

**EXP-3407 (Stop Loss: -200% of credit):**
- Effectiveness: Does stop loss cap losses at -200%?
- Slippage: Can we exit at -200% in fast markets? (check liquidity)
- Win rate impact: Does stop reduce win rate? (stop out of winners?)

**EXP-3410 (Gamma Hedge):**
- Hedge cost: How much does ATM straddle hedge cost?
- Effectiveness: Does hedge reduce tail risk?
- Complexity: Is gamma threshold (-100) realistic?

**Output:**
- Exit rule validation (profit targets, stops)
- Hedge cost-benefit analysis
- Risk-adjusted return comparison

---

### **CC5: Asymmetric & High Frequency (EXP-3408, EXP-3409)**
**Task:** Test asymmetric bias and frequency optimization

**EXP-3408 (Asymmetric: 25Δ call, 35Δ put):**
- Drift: Does SPX have upward drift intraday? (measure)
- Premium: How much more premium on wider put side?
- Risk: Does asymmetry increase directional risk?

**EXP-3409 (High Frequency: Mon/Wed/Fri only):**
- Liquidity: Are Mon/Wed/Fri 0DTE days more liquid? (check volume)
- Sizing: Can we size larger on 0DTE days? (3× per week vs 5×)
- Returns: 3 days/week × larger size = better than 5 days × smaller?

**Output:**
- Asymmetry test (symmetric vs asymmetric P&L)
- Frequency optimization (daily vs Mon/Wed/Fri)
- Liquidity analysis by day of week

---

## Parallel Execution Plan

**Phase 1: Data Validation (CC1) — 30 minutes**
- Run first, blocks everything else
- If IronVault lacks 0DTE data → ABORT, find alternative

**Phase 2: Parameter Design (CC2-CC5 parallel) — 2 hours**
- CC2: Baseline + aggressive strikes
- CC3: Wing width + entry timing
- CC4: Exit rules + hedging
- CC5: Asymmetry + frequency

**Phase 3: Backtest Execution (after Phase 2 complete) — 3 hours**
- Run all 10 experiments in parallel
- Use validated parameters from CC sessions
- Generate reports

**Phase 4: Consolidation (Maximus) — 1 hour**
- Aggregate results from 10 experiments
- Rank by Sharpe, win rate, max DD
- Identify top 3 for deep-dive

---

## Rule Zero Enforcement

**Before ANY backtest runs:**

1. **CC1 must certify:** Data is real (not synthetic)
2. **All CC sessions must confirm:** No parameter assumptions (test empirically)
3. **Maximus final check:** No yfinance, no fake options prices, no smeared P&L

**If ANY synthetic data detected → ABORT entire sweep, fix contamination first**

---

## Output Structure

```
experiments/EXP-3400/
├── CC1_DATA_VALIDATION.md          ← Pass/fail for IronVault
├── CC2_BASELINE_AGGRESSIVE.md      ← EXP-3401, 3402 configs
├── CC3_WING_TIMING.md              ← EXP-3403, 3404, 3405 configs
├── CC4_EXIT_RISK.md                ← EXP-3406, 3407, 3410 configs
├── CC5_ASYMMETRIC_FREQUENCY.md     ← EXP-3408, 3409 configs
├── CONSOLIDATED_PLAN.md            ← Final backtest parameters
└── [after execution]
    ├── EXP-3401_results.json
    ├── EXP-3402_results.json
    ├── ... (3403-3410)
    └── SUMMARY_REPORT.html
```

---

## Timeline

- **04:40-05:10 UTC:** CC1 data validation
- **05:10-07:10 UTC:** CC2-CC5 parameter design (parallel)
- **07:10-10:10 UTC:** Backtest execution (parallel)
- **10:10-11:10 UTC:** Consolidation + report generation
- **11:10 UTC:** Deliver results to Carlos

**ETA for complete results: ~6.5 hours from now (11:10 UTC / 7:10 AM ET)**

---

**Starting CC1 data validation NOW.**
