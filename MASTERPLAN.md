# MASTERPLAN.md — Operation Crack The Code

## Mission
Build a validated, multi-strategy options trading system on SPY. Data-driven approach: kill losing strategies, optimize winners, follow what the data says. Paper trade the winners, then go live.

## North Star (Updated 2026-04-04 — Real Data)

| Target | Original (Synthetic) | Real Data Actual | Status |
|--------|---------------------|-----------------|--------|
| **Avg annual return** | 55% | **77.3% CAGR** (EXP-1220 @ 1x) | EXCEEDED |
| **Sharpe ratio** | 6.0 | **5.78** (EXP-1220 @ 1x) | CLOSE — 5.68 at 1.2x |
| **Max drawdown** | ≤30% | **6.6%** (EXP-1220 @ 1x) | EXCEEDED (5x better) |
| **Multi-strategy** | Yes | **3 validated** + 3 promising | IN PROGRESS |
| **All 6 years profitable** | Yes | **6/6 years** (EXP-1220) | MET |
| **100% CAGR path** | 3.5x leverage | **1.2x → 99% CAGR, 7.9% DD** | FOUND (lower leverage!) |

> **CRITICAL:** The "North Star" EXP-1470 (Sharpe 17.21, 206% CAGR) was based on synthetic data and collapsed to CAGR 0.42% on real data. All targets above are from **real IronVault data only.**
>
> **🚫 NO SYNTHETIC DATA — EVER.** All pricing must come from `IronVault.instance()` → `data/options_cache.db`. See `docs/DATA_ARCHITECTURE.md`.

---

## REAL DATA STRATEGY LEAGUE TABLE (2026-04-04)

> All results below use **IronVault real Polygon data only**. Zero `np.random`. Backtest window: 2020-2025.

### Tier 1: Validated & Profitable

| Strategy | Sharpe | CAGR | Max DD | Win Rate | Trades | SPY Corr | Report |
|----------|--------|------|--------|----------|--------|----------|--------|
| **EXP-1220 Tail Risk Hedge** (1x) | **5.78** | **77.3%** | **-6.6%** | N/A (overlay) | N/A | -0.65 (down days) | `reports/exp1220_robustness_report.html` |
| **EXP-1220 Tail Risk Hedge** (1.2x) | **5.68** | **99.0%** | **-7.9%** | N/A (overlay) | N/A | -0.65 (down days) | `reports/exp1220_leverage_optimization.html` |
| Cross-Asset Pairs (XLI→SPY) | **9.10** OOS | 0.5% | -0.4% | 95.6% | 68 (32 OOS) | 0.04 | `reports/strategy_discovery_round2.html` |
| Cross-Asset Pairs (TLT-QQQ) | **7.69** OOS | — | — | — | — | 0.02 | `reports/cross_asset_pairs_validation.html` |
| Vol Term Structure (SPY) | **2.45** | 0.5% | -0.2% | 96.2% | 53 | -0.32 | `reports/vol_term_structure_deep_dive.html` |
| Vol Term Structure (XLI) | **5.69** | — | 0.0% | 100% | 21 | 0.32 | `reports/vol_term_structure_deep_dive.html` |
| TLT Iron Condors | **2.85** OOS | — | -1.7% | — | — | — | `reports/xlf_iron_condor_optimization.html` |
| XLF Iron Condors | **2.28** OOS | 0.1% | -1.4% | 56.6% | 53 (32 OOS) | -0.16 | `reports/new_strategy_exploration.html` |

### Tier 2: Marginal / Needs More Data

| Strategy | Sharpe | CAGR | Max DD | Notes |
|----------|--------|------|--------|-------|
| VIX Mean-Reversion Puts | 3.51 OOS | 0.0% | -0.7% | Only 6 OOS trades — insufficient data |
| EXP-1320 Vol Clustering | 0.92 | 0.1% | -0.4% | 41 trades, low signal quality |
| EXP-1230 Microstructure | 0.89 | 0.0% | 0.0% | Standalone dead; potential as overlay filter |
| EXP-880 Puts-Only Variant | 0.84 | 6.0% | -7.6% | Salvaged from dead EXP-880; 266 trades, 85.3% WR |

### Tier 3: DEAD (Killed by Real Data)

| Strategy | Synthetic Claim | Real Data Result | Cause of Death |
|----------|----------------|-----------------|----------------|
| **EXP-1470 North Star** | Sharpe 17.21, 206% CAGR | CAGR 0.42%, 19 trades | Entirely synthetic — collapsed on real data |
| **EXP-880 ML Ensemble** | Sharpe 4.97, 76.9% CAGR | **Lost $101K**, Sharpe 0.41 | Bear calls destroyed it (31% WR); ML model never integrated into backtester |
| **EXP-1270 Adaptive Stop** | Sharpe 5.25 | Sharpe -0.25 | Synthetic data inflated all metrics |
| SPY Calendar Spreads | N/A (new) | Sharpe -0.62 OOS | Loses money on real data |

### EXP-1220 Deep Dive (The Clear Winner)

**Walk-forward validation (year-by-year, no look-ahead):**

| Year | Unprotected | Protected | DD Saved | OOS Sharpe |
|------|------------|-----------|----------|-----------|
| 2020 | +18.3%, DD 33.7% | +52.9%, DD 3.9% | 29.8pp | 4.03 |
| 2021 | +28.7%, DD 5.1% | +49.1%, DD 1.5% | 3.6pp | 5.22 |
| 2022 | **-18.2%**, DD 24.5% | **+14.8%**, DD 6.6% | 17.9pp | 1.26 |
| 2023 | +26.2%, DD 10.0% | +40.1%, DD 3.4% | 6.6pp | 3.45 |
| 2024 | +24.9%, DD 8.4% | +31.5%, DD 1.3% | 7.2pp | 4.69 |
| 2025 | +18.6%, DD 18.8% | +37.2%, DD 1.7% | 17.1pp | 4.67 |

**Leverage analysis:**

| Leverage | CAGR | Max DD | Sharpe | Sortino |
|----------|------|--------|--------|---------|
| 0.5x | 33.5% | 3.3% | 5.68 | 11.97 |
| 1.0x | 77.7% | 6.6% | 5.68 | 11.97 |
| **1.2x** | **99.0%** | **7.9%** | **5.68** | **11.97** |
| 1.8x | 179.1% | 11.6% | 5.68 | 11.97 |
| 2.0x | 212.1% | 12.8% | 5.68 | 11.97 |
| 3.0x | 442.0% | 18.8% | 5.68 | 11.97 |

**Stress test (1.2x leverage, 10K MC paths):**
- P5 drawdown: **9.6%** (North Star threshold: <=12%) — **PASS**
- Prob of profit: 100% | Prob of ruin: 0.0%
- CVaR(95%): -1.27% | Max consecutive losses: 5 days | Longest DD: 55 days
- Parameter sensitivity: CV < 0.03 for all 4 params — no cliff edges
- Alpha: +55.6%/yr | Beta: 0.071 | SPY corr on down days: -0.651
- Report: `reports/exp1220_stress_test.html`

---

## EXPERIMENT REGISTRY

> **Authoritative data:** `experiments/registry.json`
> **Rules:** `EXPERIMENT_PROTOCOL.md`

### Live Paper Trading

| ID | Name | Creator | Ticker | Account | Avg Return | Max DD | ROBUST | Live Since |
|----|------|---------|--------|---------|-----------|--------|--------|------------|
| **EXP-400** | **The Champion** | maximus | SPY | PA36XFVLG0WE | +32.7% | -12.1% | 0.870 | 2026-03-15 |
| **EXP-401** | **The Blend** | maximus | SPY | PA3Y2XDYB9I3 | +40.7% | -7.0% | TBD | 2026-03-15 |
| **EXP-503** | **ML V2 Aggressive** | maximus | SPY | PA3Z9PLVYUL5 | TBD | TBD | TBD | 2026-03-22 |
| **EXP-600** | **IBIT Adaptive** | charles | IBIT | PA3O14JAJHJ0 | +139.2% | -19.4% | 0.950 | 2026-03-22 |

### Real-Data Validated (Backtest Only — Awaiting Paper Trading)

| ID | Name | Real Sharpe | Real CAGR | Real DD | Trades | Validated |
|----|------|------------|-----------|---------|--------|-----------|
| **EXP-1220-real** | **Tail Risk Hedge** | 5.78 | 77.3% | -6.6% | N/A (overlay) | 2026-04-03 |
| **Cross-Asset Pairs** | **XLI→SPY Reversion** | 9.10 OOS | 0.5% | -0.4% | 68 | 2026-04-04 |
| **Vol Term Structure** | **SPY VTS** | 2.45 | 0.5% | -0.2% | 53 | 2026-04-04 |
| **TLT Iron Condors** | **Bond ICs** | 2.85 OOS | — | -1.7% | — | 2026-04-04 |

### In Development

| ID | Name | Creator | Phase | Next Step |
|----|------|---------|-------|-----------|
| **EXP-500** | **ML Champion** | maximus | 1 — Data Collection | Accumulate 200+ labeled samples from EXP-400, then train XGBoost |
| **EXP-501** | **ML Blend** | maximus | 0 — Blocked | Blocked on EXP-500. Start after EXP-500 proves concept. |
| **EXP-601** | **IBIT ML Signal Filter** | charles | 1 — Built & Trained | Accumulate 12+ months walk-forward data; retrain for out-of-sample test |

### Retired / Dead

| ID | Name | Why Retired |
|----|------|-------------|
| EXP-031 | Compound Bull Put | Overfit score 0.590 (hard gate failed). DTE cliff. |
| EXP-036 | Compound 10% Both MA200 | Superseded by EXP-400. |
| EXP-059, EXP-154 | Various | Superseded by EXP-400/401. |
| EXP-305 | COMPASS Portfolio | Multi-ticker approach superseded by focused EXP-400/401. |
| **EXP-1470** | **North Star Portfolio** | **DEAD on real data.** Synthetic Sharpe 17.21 → real CAGR 0.42%, 19 trades. |
| **EXP-880** | **ML Ensemble + Crisis Hedge** | **DEAD.** Lost $101K on real data. Bear calls killed it (31% WR). ML model never integrated. |
| **EXP-1270** | **Adaptive Stop-Loss** | **DEAD.** Synthetic Sharpe 5.25 → real Sharpe -0.25. |

---

## OPERATION REAL DATA — Synthetic Data Remediation (2026-04-03)

**Context:** Audit revealed 62/243 compass modules used synthetic data (`np.random`) instead of IronVault. All backtest results from these modules (including "North Star" EXP-1470) were unreliable.

### Step 1: Deploy IronVault DB for Backtesting ✅ DONE
- Downloaded `options_cache.db` (944MB) from Charles via Tailscale
- Verified: 248,074 contracts, 5.9M daily bars, 1.4M intraday bars
- Coverage: SPY (187K contracts, 2020-2026), QQQ, TLT, GLD, XLF, XLI, XLK, XLE, SOXX

### Step 2: Daily Data Updates ✅ DONE (2026-04-04)
- `scripts/daily_data_update.sh` — production-ready with lock file, retries, log rotation
- `scripts/backfill_gap.py` — targeted multi-ticker gap backfill
- Backfilled SPY through 2026-04-02 (6,294 new contracts, 17,271 bars)
- Backfilled SOXX/XLE/XLF/XLI/XLK through 2026-04-02 (4,238 contracts, 16,678 bars)
- 0 errors across 12,861 contract fetches
- DB: 258,606 contracts, 5.97M bars, 948 MB
- Cron not yet configured — awaiting Carlos decision
- Status report: `reports/data_backfill_status.html`

### Step 3: Re-Backtest Top Portfolios on Real Data ✅ DONE (2026-04-03)

| Experiment | Synthetic Claim | Real Data Result | Verdict |
|-----------|----------------|-----------------|---------|
| EXP-1220 (Tail Risk) | Sharpe 2.12 | **Sharpe 5.78, CAGR 77.3%** | **LEGITIMATE** — better than synthetic |
| EXP-1230 (Microstructure) | +21pp WR overlay | Standalone Sharpe 0.89, overlay untested | MARGINAL |
| EXP-1270 (Adaptive Stop) | Sharpe 5.25 | Sharpe -0.25 | **DEAD** |
| EXP-1320 (Vol Clustering) | Sharpe 3.05 | Sharpe 0.92, 41 trades | MARGINAL |
| EXP-1470 (North Star) | Sharpe 17.21, 206% CAGR | CAGR 0.42%, 19 trades | **DEAD** |
| EXP-880 (ML Ensemble) | Sharpe 4.97, 76.9% CAGR | Lost $101K, Sharpe 0.41 | **DEAD** |

**Lesson:** 3 of 6 top strategies were entirely synthetic illusions. Only EXP-1220 survived and actually *exceeded* its synthetic claims. Average real-data Sharpe ~1.3 vs ~6.5 heuristic — a 5x reality gap.

### Synthetic Data Audit Summary (2026-04-03)
| Category | Count | % |
|----------|-------|---|
| Real data only | 45 | 19% |
| Synthetic data | 62 | 25% |
| Mixed | 7 | 3% |
| Neutral (no data refs) | 129 | 53% |

Full audit report: `reports/synthetic_audit_report.html`

---

## PHASE COMPLETION STATUS (Updated 2026-04-04)

| Phase | Name | Status | Key Result |
|-------|------|--------|------------|
| 0 | Strategy Discovery Engine | ✅ COMPLETE | 7 strategies built, champion found |
| 1 | Parameter Sweep | ✅ COMPLETE | 87 experiments, regime-adaptive winner |
| 2 | Position Sizing | ✅ COMPLETE | Returns plateau at 10% risk. 8.5% near-optimal. |
| 3 | Portfolio Blending | ✅ COMPLETE | CS+S/S blend beats CS+IC. +39.1% avg, -9.5% DD |
| 4 | Regime Switching | ✅ COMPLETE | Dynamic allocation: +40.7% avg, -7.0% DD |
| 5 | Final Validation | ~~✅ COMPLETE~~ ⚠️ OBSOLETE | *Based on synthetic data. Re-validation on real data in Phase 7.* |
| 6 | Paper Trading | 🔄 LIVE — VALIDATING | EXP-400/401/503/600 deployed. 8-week clock: Mar 16 → May 11 |
| 6.5 | Operation Unified Front | ✅ COMPLETE | Entry + exit paths unified. All strategies use same code as backtester. |
| **7** | **Operation Real Data** | **✅ COMPLETE** | **Synthetic audit, IronVault deployed, re-backtests done. 3/6 strategies dead.** |
| **7.5** | **New Strategy Discovery (Real Data)** | **✅ COMPLETE** | **Cross-asset pairs (Sharpe 9.10), vol term structure (2.45), TLT ICs (2.85)** |
| **8** | **Portfolio Optimization (Real Data)** | **🔄 IN PROGRESS** | **3-strategy portfolio: Sharpe 6.25-6.66, CAGR 4-30%. EXP-1220 dominant.** |
| **8.5** | **Stress Testing** | **✅ COMPLETE** | **P5 DD 9.6% at 1.2x leverage — PASSES 12% North Star** |
| 9 | Paper Trading v2 (Real Data Strategies) | ⬜ NEXT | Wire EXP-1220 overlay into paper trader; Telegram alerts |
| 10 | Live Trading | ⬜ BLOCKED | Requires 8+ weeks paper validation of real-data strategies |

---

## CURRENT PRIORITY: Portfolio Optimization + Paper Trading Prep

### Active Track 1: Paper Trading (original strategies)
- EXP-400/401/503/600 running since Mar 15-22
- 8-week clock ends **May 11, 2026**
- Monitoring via Telegram alerts + daily heartbeat

### Active Track 2: Real-Data Portfolio Construction (new)
**Recommended portfolio (from 2026-04-04 analysis):**

| Strategy | Weight | Role | Source |
|----------|--------|------|--------|
| **EXP-1220 Tail Risk** (1.2x) | 70-80% | Core alpha + crash protection | Real data validated |
| **Cross-Asset Pairs** | 10-15% | Uncorrelated diversifier (SPY corr 0.02-0.04) | Real data validated |
| **Vol Term Structure** | 5-10% | Anti-correlated diversifier (SPY corr -0.32) | Real data validated |
| **TLT Iron Condors** | 5-10% | Bond diversifier | Real data validated |

**Combined portfolio results (2026-04-04):**
- max_sharpe allocation: Sharpe 6.25, CAGR 29.8%, DD 2.7%
- risk_parity allocation: Sharpe 6.66, CAGR 4.4%, DD 0.4%
- EXP-1220 solo at 1.2x: CAGR 99%, Sharpe 5.68, DD 7.9%
- Near-zero cross-correlations (-0.03 to 0.04) between all strategies

### Next Steps
1. ⬜ Wire EXP-1220 as overlay on existing paper trades (daily Telegram signal)
2. ⬜ Decide on portfolio weights (Carlos)
3. ⬜ Configure daily Polygon backfill cron
4. ⬜ Paper trade the real-data portfolio (8-week validation)
5. ⬜ Backfill stale tickers (QQQ: 2023-04, GLD: 2024-03, TLT: 2024-07)

---

## INFRASTRUCTURE

### Key Files
```
Iron Vault (Centralized Data Layer):
├── shared/iron_vault.py            ← THE single data provider (singleton)
├── scripts/iron_vault_setup.py     ← Bootstrap & validation
├── docs/DATA_ARCHITECTURE.md       ← Full architecture docs
├── data/options_cache.db           ← 948 MB, 258K contracts, 5.97M bars (2020-2026)
├── data/macro_state.db             ← Regime/sector data (COMPASS)
└── backtest/historical_data.py     ← Raw DB queries (wrapped by IronVault)

Daily Data Pipeline:
├── scripts/daily_data_update.sh    ← Cron-ready: lock, retries, log rotation
├── scripts/backfill_gap.py         ← Targeted multi-ticker gap backfill
└── scripts/backfill_polygon_cache.py ← Full SPY discovery + backfill

Real Data Reports (2026-04-03/04):
├── reports/exp1220_robustness_report.html     ← Walk-forward, sensitivity, regime breakdown
├── reports/exp1220_leverage_optimization.html  ← Leverage sweep 0.5x-3.0x
├── reports/exp1220_stress_test.html           ← 10K MC paths, crisis scenarios, tail risk
├── reports/master_strategy_dashboard.html     ← Unified league table (19 strategies)
├── reports/new_strategy_exploration.html      ← XLF ICs, VIX puts, momentum, calendars
├── reports/strategy_discovery_round2.html     ← Cross-asset pairs, vol term structure
├── reports/vol_term_structure_deep_dive.html  ← Multi-ticker VTS analysis
├── reports/cross_asset_pairs_validation.html  ← Walk-forward + regime validation
├── reports/exp880_postmortem.html             ← Why EXP-880 died
├── reports/data_backfill_status.html          ← Data coverage per ticker
└── reports/synthetic_audit_report.html        ← 62/243 modules used synthetic data

configs/
├── champion.json              ← EXP-400 raw params
├── paper_champion.yaml        ← EXP-400 paper trading config
├── paper_exp401.yaml          ← EXP-401 paper trading config
└── paper_exp503.yaml          ← EXP-503 ML V2 paper config
```

### GitHub
- **Repo:** `charlesattix/pilotai-credit-spreads`
- **Main branch:** Production code + alignment fixes
- **maximus/clean-features:** Current development branch (real-data work)

### Safety Rails (Paper Trading)
- `paper_mode: true` — blocks live API URLs
- Kill switch via DB flag or Telegram
- 40% drawdown circuit breaker
- 40% portfolio heat cap
- Max 10 positions, max 2 per ticker
- Write-ahead logging for crash recovery
- Isolated DB per experiment

---

## TIMELINE

| Date | Milestone |
|------|-----------|
| 2026-03-15 | Paper trading deployed (EXP-400, EXP-401) |
| 2026-03-22 | EXP-503, EXP-600 deployed |
| **2026-04-03** | **Operation Real Data: synthetic audit, IronVault deployed, 3/6 strategies killed** |
| **2026-04-04** | **Real-data discovery: EXP-1220 confirmed (Sharpe 5.78), cross-asset pairs (9.10), vol term structure (2.45)** |
| **2026-04-04** | **Stress test PASSES: P5 DD 9.6% at 1.2x leverage (threshold: 12%)** |
| **2026-04-04** | **Data pipeline verified: SPY/sector ETFs backfilled through Apr 2** |
| 2026-04-07 | (Next) Wire EXP-1220 overlay signals to Telegram |
| 2026-05-11 | Paper trading 8-week mark (original strategies) |
| 2026-05-19 | (Target) Begin paper trading real-data portfolio |
| 2026-07-14 | (Target) Paper trading v2 8-week mark → live trading decision |

---

## RULES

1. **Every experiment gets an ID** — EXP-NNN format, registered in this file
2. **Never skip validation** — overfit score ≥0.70 to be considered ROBUST
3. **Always log before AND after** — hypothesis → results → leaderboard
4. **Regime detector is mandatory** — all directional strategies use combo regime mode
5. **Paper before live** — nothing touches real money without 8+ weeks paper validation
6. **Follow the data** — kill losers fast, double down on winners
7. **MASTERPLAN is sacred** — single source of truth, update with every instruction from Carlos
8. **🚫 NO SYNTHETIC DATA** — all backtests use IronVault. Cache miss → skip trade, NEVER fabricate.
9. **Real data trumps synthetic** — if synthetic and real results disagree, trust real. Kill the synthetic.

---

*Victory is not won by the sword alone — it is won by the plan behind it.*
