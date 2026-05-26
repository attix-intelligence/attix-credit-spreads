# EXP-3400: QQQ 0DTE Backtests — EXECUTION STARTED

**Started:** May 25, 2026 05:12 UTC  
**Objective:** 2× $100K in 30 days using QQQ Friday 0DTE iron condors  
**Data:** IronVault (2,493 QQQ 0DTE contracts, 2023-2024, Fridays only)

---

## 10 Experiments to Run

### **Baseline & Risk Mitigation**
1. **EXP-3401:** Baseline (30Δ, no special mitigation)
2. **EXP-3402:** Tech earnings blacklist (skip NVDA/AAPL/MSFT/GOOGL earnings weeks)

### **Adaptive Strikes**
3. **EXP-3403:** Wider strikes during tech earnings season (35Δ vs 30Δ)
4. **EXP-3404:** VIX-adaptive strikes (25Δ/30Δ/35Δ based on VIX level)
5. **EXP-3405:** Asymmetric strikes (25Δ call, 35Δ put — protect downside)

### **Position Sizing & Exits**
6. **EXP-3406:** Dynamic sizing (50% size during tech earnings season)
7. **EXP-3407:** Fast exit + stop loss (25% profit target, -200% stop)

### **Hedging**
8. **EXP-3408:** SPY put hedge (10% of capital in protective puts)
9. **EXP-3409:** VIX call hedge (buy OTM VIX calls weekly)
10. **EXP-3410:** XLK IV rank filter (only trade when tech sector calm)

---

## CC Session Assignments (Parallel Execution)

**CC1:** EXP-3401, 3402 (baseline + earnings blacklist)  
**CC2:** EXP-3403, 3404, 3405 (adaptive strikes)  
**CC3:** EXP-3406, 3407 (sizing + exits)  
**CC4:** EXP-3408, 3409 (hedging)  
**CC5:** EXP-3410 + tech stress analysis

**Timeline:**
- Phase 1 (Parameter design): 2 hours
- Phase 2 (Backtest execution): 3 hours
- Phase 3 (Analysis + report): 1 hour
- **Total: 6 hours (ETA 11:12 UTC / 7:12 AM ET)**

---

## Starting CC Sessions NOW
