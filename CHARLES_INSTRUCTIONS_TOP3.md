# Charles — Top 3 Experiment Deployment Instructions

**Date:** 2026-05-21  
**Requested by:** Carlos  
**Context:** Deploy the top 3 un-paper-traded experiments for live validation on Mac Studio

---

## Overview

Run these 3 experiments in paper trading mode to validate performance before T1 live capital:

1. **EXP-3311** — NFP Entry Filter (defensive, risk-reducer)
2. **EXP-3309** — Pre-Close Execution Window (offensive, execution alpha)
3. **EXP-3303b** — Per-Stream Selective Regime Gate (defensive, SPX-VRP protection)

**Expected Runtime:** 4-6 weeks paper testing per experiment (stagger start dates for clean isolation)

---

## Pre-Deployment Checklist

- [ ] Alpaca paper API keys configured in `config/alpaca_paper.env`
- [ ] IronVault `options_cache.db` synced to Mac Studio (latest version from `/home/node/.openclaw/workspace/pilotai-credit-spreads/data/`)
- [ ] Baseline v8a strategy running clean in paper mode (control group)
- [ ] Monitoring dashboard configured for comparative metrics (Sharpe, DD, CAGR, fill rates)
- [ ] Paper account funded to $100K per experiment (total $400K: $100K baseline + $100K × 3)

---

## Experiment 1: EXP-3311 — NFP Entry Filter

### What It Does
Skips credit spread entries on days **before** NFP (Non-Farm Payrolls) announcements. Protects against payroll volatility spikes that historically cause worst drawdowns.

### Implementation
1. **Calendar Blackout List:**
   - Download NFP calendar for 2026: https://www.bls.gov/schedule/news_release/empsit.htm
   - Add NFP dates to `config/event_blacklist.json`:
     ```json
     {
       "nfp_dates": [
         "2026-06-05",
         "2026-07-02",
         "2026-08-07",
         "2026-09-04",
         "2026-10-02",
         "2026-11-06",
         "2026-12-04"
       ]
     }
     ```

2. **Code Changes:**
   - Edit `compass/orchestrator/entry_gate.py`:
     ```python
     def should_skip_entry(self, today: datetime.date) -> bool:
         """Skip entries day before NFP announcements."""
         nfp_dates = load_json("config/event_blacklist.json")["nfp_dates"]
         nfp_dates_dt = [datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in nfp_dates]
         
         # Skip if tomorrow is NFP
         tomorrow = today + datetime.timedelta(days=1)
         return tomorrow in nfp_dates_dt
     ```

3. **Launch Command:**
   ```bash
   cd ~/pilotai-credit-spreads
   source venv/bin/activate
   python compass/main.py live \
     --account paper_exp3311 \
     --config config/v8a_nfp_filter.yaml \
     --log-level INFO
   ```

4. **Config File:** `config/v8a_nfp_filter.yaml`
   ```yaml
   strategy: v8a_net
   entry_gate:
     nfp_filter: true
     blacklist_path: config/event_blacklist.json
   execution:
     window: "09:30-16:00"  # baseline timing
   risk:
     max_drawdown: 0.12
     vol_target: 0.12
   ```

### Expected Results (from backtest)
- **Net Sharpe:** 4.984 (vs 6.386 baseline)
- **Max DD:** 5.89% (−2.07pp improvement)
- **CAGR:** 84.8% (vs 118% baseline)
- **Trade Impact:** ~30% fewer exp1220 trades, ~51% fewer qqq_cs trades

### Success Criteria
- Max DD < 7% over 6 weeks
- Sharpe > 4.5 (live degradation expected)
- Zero trades placed day-before-NFP (verify log files)

---

## Experiment 2: EXP-3309 — Pre-Close Execution Window

### What It Does
Routes **all** spread entries and exits to 15:30-16:00 window. Captures pre-close liquidity surge (2× midday ADV) for tighter spreads and lower slippage.

### Implementation
1. **Execution Timing Override:**
   - Edit `compass/execution/order_router.py`:
     ```python
     def get_execution_window(self) -> tuple[time, time]:
         """Force all orders to pre-close window."""
         return (time(15, 30), time(16, 0))
     
     def should_delay_order(self, now: datetime) -> bool:
         """Hold orders until 15:30 if outside window."""
         window_start, window_end = self.get_execution_window()
         current_time = now.time()
         
         if current_time < window_start:
             logger.info(f"Delaying order until {window_start}")
             return True
         if current_time > window_end:
             logger.warning(f"Market closed, order rejected")
             return True
         return False
     ```

2. **Launch Command:**
   ```bash
   python compass/main.py live \
     --account paper_exp3309 \
     --config config/v8a_preclose.yaml \
     --log-level INFO
   ```

3. **Config File:** `config/v8a_preclose.yaml`
   ```yaml
   strategy: v8a_net
   execution:
     window: "15:30-16:00"  # PRE-CLOSE ONLY
     order_delay: true
     fill_timeout_sec: 1800  # 30min max wait
   entry_gate:
     nfp_filter: false
   risk:
     max_drawdown: 0.12
     vol_target: 0.12
   ```

### Expected Results (from backtest)
- **Net Sharpe:** 5.879 (+0.174 vs baseline stack)
- **CAGR:** 265.7%
- **Cost Savings:** 343 bps/year (bid-ask −15%, slippage −29%)
- **Fill Rate:** 98%

### Success Criteria
- All fills occur 15:30-16:00 (verify execution logs)
- Average bid-ask spread < 85% of midday baseline (measure from fill prices)
- Fill rate > 95%
- Sharpe > 5.0 over 6 weeks

### CRITICAL CAVEAT
**The backtest cost model uses literature coefficients (Chordia et al., Doshi-Patel 2025), NOT measured IronVault data.**

The paper test will validate:
- Actual fill times
- Actual spread compression
- Actual slippage reduction

If cost savings don't materialize, the Sharpe lift will evaporate. This is an **empirical validation test**, not a guaranteed improvement.

---

## Experiment 3: EXP-3303b — Per-Stream Selective Regime Gate

### What It Does
Gates only SPX-sensitive streams (exp1220, qqq_cs) at 50% size during regime transitions. Keeps carry streams (XLF/XLI/GLD/SLV/cross_vol/v5_hedge) running at 100%.

### Implementation
1. **Regime Detection:**
   - Uses Ledoit-Wolf covariance matrix regime classification from `compass/risk/regime_detector.py`
   - Triggers on 30-day rolling correlation > 0.7 across SPY/QQQ/VIX

2. **Selective Gating Logic:**
   - Edit `compass/orchestrator/position_sizer.py`:
     ```python
     def get_stream_size_multiplier(self, stream_id: str, regime: str) -> float:
         """Reduce SPX-sensitive streams during regime transitions."""
         if regime in ["transition", "high_stress"]:
             spx_streams = ["exp1220", "qqq_cs"]
             if stream_id in spx_streams:
                 return 0.5  # Half size
         return 1.0  # Full size for all other streams
     ```

3. **Launch Command:**
   ```bash
   python compass/main.py live \
     --account paper_exp3303b \
     --config config/v8a_regime_gate.yaml \
     --log-level INFO
   ```

4. **Config File:** `config/v8a_regime_gate.yaml`
   ```yaml
   strategy: v8a_net
   risk:
     regime_gate: true
     spx_streams: ["exp1220", "qqq_cs"]
     gate_multiplier: 0.5
     max_drawdown: 0.12
     vol_target: 0.12
   execution:
     window: "09:30-16:00"
   entry_gate:
     nfp_filter: false
   ```

### Expected Results (from backtest)
- **Net Sharpe:** 6.334 (−0.052 vs baseline)
- **CAGR:** 247.9%
- **Max DD:** 10.455% (same as baseline)
- **Gated Days:** 4% (51 days over 1260)

### Success Criteria
- Max DD < 11% over 6 weeks
- Sharpe > 5.5
- exp1220/qqq_cs position size correctly reduced during regime transitions (verify logs)
- XLF/XLI/GLD/SLV positions unchanged during gates

---

## Deployment Schedule (Staggered)

**Week 1 (May 21-27):**
- Start baseline v8a control (paper_baseline account)
- Start EXP-3311 (NFP filter)

**Week 2 (May 28 - June 3):**
- Start EXP-3309 (pre-close execution)

**Week 3 (June 4-10):**
- Start EXP-3303b (regime gate)

**Week 7 (July 2-8):**
- Analyze comparative results
- Generate performance report (Sharpe, DD, CAGR, fill rates, cost analysis)
- Recommend stack for T1 live deployment

---

## Monitoring & Reporting

### Daily Checks
- [ ] All 4 accounts running (baseline + 3 experiments)
- [ ] No order rejections or API errors
- [ ] Position sizes within risk limits
- [ ] Fill rates > 95%

### Weekly Reports (Send to Carlos)
- Comparative Sharpe (baseline vs each experiment)
- Max DD progression
- Fill rate statistics
- Cost analysis (bid-ask, slippage, commissions)
- Trade count by stream

### Red Flags (Alert Immediately)
- Max DD > 15% on any account
- Fill rate < 90% sustained for 3+ days
- Sharpe < 3.0 over rolling 2-week window
- Any account loses > 10% in single day

---

## Rollback Plan

If any experiment shows:
- Max DD > 15%
- Sharpe < 2.5 over 4 weeks
- Critical execution failures

**Action:** Kill the experiment, analyze logs, report to Carlos with root cause analysis.

---

## Post-Experiment Decision Tree

After 6 weeks:

**If EXP-3311 + EXP-3309 combined Sharpe > 5.5 AND max DD < 7%:**
→ Deploy stack to T1 live ($10K initial capital)

**If EXP-3309 alone shows Sharpe > 5.5 AND cost savings validated:**
→ Deploy execution timing change to live (free Sharpe lift)

**If EXP-3311 alone shows max DD < 6%:**
→ Deploy NFP filter to live (risk management improvement)

**If EXP-3303b shows Sharpe > 6.0 with same DD:**
→ Consider as alternate to EXP-3311 for regime protection

**If all fail to meet success criteria:**
→ Return to baseline v8a, run EXP-3312 integration analysis, propose new experiments

---

## Contact

Questions or issues during deployment:
- Telegram: @hatoshi19 (Carlos)
- Maximus (this agent) available 24/7 via OpenClaw workspace

**Experiments are live — let's validate the alpha.** ⚡
