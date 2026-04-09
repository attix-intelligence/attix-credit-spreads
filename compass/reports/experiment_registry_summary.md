# Experiment Registry Summary — Institutional Knowledge Base

**Scope:** Every experiment from EXP-031 through EXP-2930 (inclusive legacy + wave 1-10).
**As-of:** 2026-04-09 AM
**Sources:** `experiments/registry.json`, `MASTERPLAN.md` v10, `compass/reports/master_dashboard_apr8.html`, `git log --since="2026-02-01"`, per-experiment JSON reports under `compass/reports/`.
**Purpose:** Searchable single-file index of what was tried, what worked, what failed, what made it into the v8a production portfolio.

---

## Scorecard

| Metric | Count |
|---|---|
| **Total experiments** | ~110 (92 in the April 6-9 sprint + 18 legacy) |
| **Winners (production slot)** | ~24 |
| **Honest kills (OOS reject)** | ~19 |
| **Marginal (ensemble backup)** | ~10 |
| **Infrastructure** | ~35 |
| **Retractions** | 4 (EXP-2360 → 2390, EXP-2400 → 2450) |
| **Archived** | 23 (in `compass/archive/`) |
| **North Star rails MET** | 3 / 4 (Sharpe, CAGR, DD; capacity is the lone gap) |

**Headline:** Net Sharpe **6.00** on Alpaca commission-free path (EXP-2570), net CAGR **93%**, max DD **4.2%** (CB on), 8 live streams, ~$50M soft cap, Rule Zero held throughout.

---

## v8a Production Citations

The 8-stream North Star v8a portfolio ships in `configs/north_star_v6_prod.yaml` (renamed to v8 in EXP-2600). The following experiments are **directly cited** by that production config or its monitoring/risk stack — every other experiment is either an ancestor, a kill, or an infra/report by-product.

| Role | Experiment | Module |
|---|---|---|
| SPY credit-spread foundation | **EXP-1220** | `compass/exp1220_standalone.py` |
| QQQ credit-spread sleeve | **EXP-2240 / EXP-2590** | `compass/exp2240_qqq_iwm_credit_spreads.py` |
| XLF sleeve | EXP-2210 | `compass/exp2210_xlf_xli_validation.py` |
| XLI sleeve | EXP-2210 | `compass/exp2210_xlf_xli_validation.py` |
| GLD calendar | **EXP-1770** | `compass/exp1770_commodity_calendars.py` |
| SLV calendar | EXP-1770 | `compass/exp1770_commodity_calendars.py` |
| Cross-vol arb | **EXP-2020** | `compass/exp2020_cross_vol_arb.py` |
| Crisis Alpha v5 | **EXP-1780** | `compass/crisis_alpha_v5.py` |
| FOMC overlay | EXP-1740 / EXP-1880 | `compass/exp1740_sentiment_filter.py` |
| Put/Call overlay | **EXP-1750** | `compass/exp1750_putcall_overlay.py` |
| Vol-of-Vol overlay | EXP-1970 | `compass/exp1970_vol_of_vol.py` |
| Term structure overlay | EXP-2070 | `compass/exp2070_term_structure.py` |
| T+V+F stack | EXP-2120 | `compass/exp2120_triple_overlay.py` |
| Portfolio Risk Manager | **EXP-1890** | `compass/portfolio_risk_manager.py` |
| DD circuit breaker | **EXP-2370** ★★ | wired into risk_manager |
| Real TC model | **EXP-2420** | `compass/exp2420_transaction_costs.py` |
| Execution stack A+B+C+D | **EXP-2470** ★★ | `compass/exp2470_execution_optimization.py` |
| Regime-conditional TC | EXP-2540 | `compass/exp2540_regime_tc_model.py` |
| Commission-free broker | **EXP-2510 / EXP-2570** ★★★ | `configs/north_star_v6_prod.yaml` (Alpaca) |
| 7-stream base portfolio | **EXP-2200** | `compass/exp2200_north_star_v6.py` |
| 8-stream v8 headline | EXP-2600 | `compass/exp2600_north_star_v8.py` |
| Walk-forward robustness | **EXP-2280** | `compass/exp2280_wf_robustness.py` |
| MC stress test | EXP-2330 | `compass/exp2330_mc_stress_test.py` |
| OOS regime stress | EXP-2630 | `compass/exp2630_regime_stress_oos.py` |
| MC degradation model | EXP-2840 | `compass/exp2840_backtest_to_live_degradation.py` |
| Alpaca connector scaffold | EXP-2890 | `compass/alpaca_connector.py` |
| Paper deployment infra | EXP-2290 | `configs/north_star_v6_prod.yaml` + `scripts/launch_north_star_v6.sh` |

**★★★ = single most important.** EXP-2570 is the number Carlos quotes.
**★★ = critical dependency.** The stack collapses if these are removed.

---

## Legacy Experiments (pre-April sprint)

Restored from `experiments/registry.json` schema 2.0. These predate the North Star sprint and live on separate paper-trading accounts (or are retired).

| ID | Name | Status | Ticker | Finding | Date |
|---|---|---|---|---|---|
| EXP-031 | Compound Bull Put | KILLED | SPY | Overfit 0.590, DTE cliff, compound sizing artifacts | 2026-02-01 |
| EXP-036 | Compound 10% Both MA200 | SUPERSEDED | SPY | Baseline, replaced by EXP-400 | 2026-02-01 |
| EXP-059 | Various | SUPERSEDED | SPY | Superseded by EXP-400/401 | 2026-02-01 |
| EXP-154 | Various | SUPERSEDED | SPY | Superseded by EXP-400/401 | 2026-02-01 |
| EXP-305 | COMPASS Portfolio | SUPERSEDED | multi | Multi-ticker superseded by focused EXP-400/401 | 2026-03-01 |
| EXP-307 | Sector ETF Diversification | PAPER | SPY + XLI + XLF | MA-crossover regime, +33 trades/yr vs SPY-only | 2026-03-26 |
| **EXP-400** | The Champion | PAPER | SPY | Regime-adaptive CS + IC, robustness 0.870 | 2026-03-05 |
| EXP-401 | The Blend | PAPER | SPY | CS + straddle/strangle blend, WF 3/3 | 2026-03-12 |
| EXP-500 | ML Champion | DEV | SPY | Phase 1 complete, ML shipped via EXP-503 | 2026-03-12 |
| EXP-501 | ML Blend | BLOCKED | SPY | Blocked on EXP-500 | 2026-03-12 |
| EXP-503 | ML V2 Aggressive | PAPER | SPY | XGBoost regime router, aggressive Kelly sizing | 2026-03-22 |
| **EXP-600** | IBIT Adaptive | PAPER | IBIT | Mega sweep #14, 139.2% avg annual backtest | 2026-03-22 |
| EXP-601 | IBIT ML Signal Filter | DEV | IBIT | XGBoost binary win/loss on EXP-600 | 2026-03-22 |
| EXP-700 | ML-Filtered Champion | PAPER | SPY | Ensemble filter (AUC 0.793) on EXP-400 champion | 2026-03-24 |
| EXP-800 | Safe Kelly 4/7/9 | PAPER | SPY | Kelly 9/7/4 bull/neutral/bear + 3-tier DD CB | 2026-03-26 |

---

## Wave 1 — Alpha Discovery (April 6)

EXP-1660 → EXP-1840. 16 experiments. Winners: 1750, 1770, 1780. Killed: 3.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-1220 | SPY put credit spreads (foundation) | **WINNER** ★ | Sharpe 3.85, WR 88% | 171 real IronVault trades 2020-02 → 2025-12, $43/trade, the bedrock | baseline |
| EXP-1630 | GLD/TLT relative value | MARGINAL | Sharpe 4.08 | Grade A OOS but GLD data ends 2024-10 | Wave 1 |
| EXP-1660 | VRP deepening | WINNER | Sharpe 2.14 | Multi-asset VRP walk-forward | Apr 6 |
| EXP-1700 | VoV feature engineering | INFRA | — | Feature pipeline for 1970 | Apr 6 |
| EXP-1710 | 0DTE/1DTE SPX feasibility | KILLED | — | Decay concentrated in 2025, no edge | Apr 6 |
| EXP-1720 | Sector ETF pairs (EG+Johansen) | KILLED | — | Cointegration too noisy OOS | Apr 6 |
| EXP-1730 | Treasury curve mean reversion | MARGINAL | — | TLT/SHY + TLT/IEF modest Sharpe | Apr 6 |
| EXP-1740 | FOMC sentiment filter | WINNER | — | NLP on federalreserve.gov minutes | Apr 6 |
| **EXP-1750** | Put/Call ratio overlay ★ | **WINNER** | +0.78 ΔSharpe | Contrarian entry gate on EXP-1220 | Apr 6 |
| EXP-1760 | Crypto volatility hardening | KILLED | Sharpe 1.04 | Small sample, 24 months IBIT (ARCHIVED) | Apr 6 |
| **EXP-1770** | Commodity calendar spreads | **WINNER** ★ | Sh 2.70 GLD / 2.27 SLV | GLD/SLV roll-yield harvest | Apr 6 |
| **EXP-1780** | Crisis Alpha v5 long-vol | WINNER | Sharpe 1.20 | Crisis hedge sleeve (though net-neutral on v6 cache — see EXP-2840) | Apr 6 |
| EXP-1790 | VIX futures roll yield | KILLED | — | No edge after costs | Apr 6 |
| EXP-1800 | Earnings vol crush (index proxy) | KILLED | — | Single-name effect doesn't replicate on indices | Apr 6 |
| EXP-1810 | IBIT credit spreads simulation | MARGINAL | Sh 1.15 | Feasibility, not true backtest | Apr 6 |
| EXP-1820 | Commodity mean reversion | MARGINAL | Sh 1.93, CAGR 5.9% | — | Apr 6 |
| EXP-1830 | Deep risk stress testing | INFRA | — | 50K MC paths framework | Apr 6 |
| EXP-1840 | Regime detector v2 | INFRA | — | HMM + EM + lead indicators | Apr 6 |

---

## Wave 2 — Portfolio Construction (April 6-7)

EXP-1850 → EXP-1880. 4 experiments. Winners: 1850, 1880.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| **EXP-1850** | Regime-adaptive portfolio optimizer | WINNER | Sharpe 4.57 | Risk-parity regime tilt, 4 methods × walk-forward | Apr 6 |
| EXP-1860 | North Star portfolio v3 | INFRA | — | First multi-stream combiner | Apr 6 |
| EXP-1870 | Combined portfolio stress test | INFRA | — | Wave 3 stress harness | Apr 6 |
| **EXP-1880** | FOMC entry overlay integration | WINNER | +0.60 ΔSharpe | FOMC gate wired into CreditSpreadStrategy | Apr 7 |

---

## Wave 3 — Risk Infrastructure (April 7)

EXP-1890 → EXP-1900. 2 experiments. Winner: 1890 (production cornerstone).

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| **EXP-1890** | Portfolio Risk Manager ★ | **WINNER** ★ | 30/30 tests | 5 components: sizer, corr monitor, DD CB, alloc limiter, leverage governor — **the foundation of every production risk decision** | Apr 7 |
| EXP-1900 | North Star paper deployment v1 | INFRA | — | First paper config; superseded by EXP-2290 | Apr 7 |

---

## Wave 4 — Alpha Hunt (April 7)

EXP-1910 → EXP-1990. 9 experiments. **5 killed in one wave** — the honest-negatives showcase. Winner: 1970.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-1910 | Intraday breakout | KILLED | Sharpe 0.31 | No edge (ARCHIVED) | Apr 7 |
| EXP-1920 | Carry trade ETF strategy | KILLED | Sharpe 0.72 | Regime-dependent, can't survive OOS (ARCHIVED) | Apr 7 |
| EXP-1930 | VVIX signal overlay | KILLED | +0.12 Δ | Under the +0.30 earn-a-slot threshold (ARCHIVED) | Apr 7 |
| EXP-1940 | Multi-timeframe momentum (SPY/QQQ/IWM/EFA/EEM) | KILLED | Sh 0.14 L/S | 5-ETF universe too narrow (ARCHIVED) | Apr 7 |
| EXP-1950 | Adaptive Kelly sizing | KILLED | +0.03 Δ | Noise, not signal (ARCHIVED) | Apr 7 |
| EXP-1960 | SPY put-skew alpha | MARGINAL | Sharpe 1.87 | Kept for ensemble | Apr 7 |
| **EXP-1970** | Vol-of-Vol overlay ★ | **WINNER** | +0.86 ΔSharpe | The "V" in V+F stack | Apr 7 |
| EXP-1980 | Dynamic hedge ratio | MARGINAL | — | Correlation regime switching | Apr 7 |
| EXP-1990 | Ensemble signal stacking (meta-learner) | KILLED | Sharpe 1.73 | Overfits 10 features on 141-trade OOS (ARCHIVED) | Apr 7 |

---

## Wave 5 — Overlay Integration (April 7)

EXP-2000 → EXP-2030. 4 experiments. Winners: 2000, 2020.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| **EXP-2000** | Triple overlay stack (V+F+PCR) | WINNER | +0.88 ΔSharpe | V+F+PCR combined | Apr 7 |
| EXP-2010 | Tail risk convexity | MARGINAL | — | Long ~10Δ SPY puts | Apr 7 |
| **EXP-2020** | Cross-sectional vol arbitrage | **WINNER** ★ | Sharpe 2.28 | Becomes the vol_arb sleeve in v8a | Apr 7 |
| EXP-2030 | Intraweek seasonality overlay | KILLED | Sharpe 0.42 | Patterns don't persist (ARCHIVED) | Apr 7 |

---

## Wave 6 — First Sharpe 6 Hit (April 7)

EXP-2040 → EXP-2090. 6 experiments. Winners: 2040, 2050, 2070, 2080.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-2040 | Leveraged GLD/SLV calendar scaling | WINNER | Sh 4.99, CAGR 57%, DD 5.3% | 25% sleeve × 2× leverage winner | Apr 7 |
| EXP-2050 | North Star v5 (first Sharpe 6.0) | SUPERSEDED | Sharpe 6.00 | The first 6.0 hit — ARCHIVED by v6/v7/v8 | Apr 7 |
| EXP-2060 | Cross-vol arb v2 (VoV overlay) | WINNER | Sharpe 2.45 | — | Apr 7 |
| **EXP-2070** | VIX term structure overlay ★ | **WINNER** | +1.42 ΔSharpe | Highest single-overlay contribution | Apr 7 |
| **EXP-2080** | Correlation regime switching | WINNER | Sharpe 5.24 | 5-stream static | Apr 7 |
| EXP-2090 | GLD/SLV calendar seasonality filter | KILLED | −0.42 Δ GLD, −0.29 Δ SLV | Pre-pandemic patterns don't persist (ARCHIVED) | Apr 7 |

---

## Wave 7 — Carlos Report + First Capacity Audit (April 7)

EXP-2100 → EXP-2190. 10 experiments. Winners: 2120, 2130, 2140, 2180.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-2100 | V+F true integration audit | RETRACT | — | Headline inflation from smeared inputs (ARCHIVED) | Apr 7 |
| EXP-2110 | Leveraged diversified portfolio | INFRA | Sh 5.80 | CAGR sweet spot at 2.5-3× | Apr 7 |
| **EXP-2120** | T+V+F triple overlay | WINNER | +0.95 ΔSharpe | The "T+V, F is redundant" finding | Apr 7 |
| EXP-2130 | Comprehensive Carlos progress report | INFRA | — | Wave 7 snapshot | Apr 7 |
| **EXP-2140** | Portfolio capacity analysis ★ | INFRA ★ | — | **SLV identified as bottleneck at $16M** — the bedrock capacity doc | Apr 7 |
| EXP-2150 | Weekly cadence + T+V filters | KILLED | — | Filters HURT at portfolio level (ARCHIVED) | Apr 7 |
| EXP-2160 | High-capacity alternatives | MARGINAL | — | SPY straddle + XLF/XLI CS | Apr 7 |
| EXP-2170 | Weight optimization bake-off | KILLED | Sharpe 5.47 | Target 6.0 not met (ARCHIVED) | Apr 7 |
| EXP-2180 | Volatility targeting | MARGINAL | +0.05 Δ | Vol target scales cleanly; Sharpe barely moves | Apr 7 |
| EXP-2190 | Tail-risk parity overlay | KILLED | −0.02 Δ, DD −0.44% worse | Reactive triggers can't predict DD (ARCHIVED) | Apr 7 |

---

## Wave 8 — 7-Stream Integration + Robustness (April 7-8)

EXP-2200 → EXP-2330. 14 experiments. Winners: 2200, 2210, 2220, 2230, 2240, 2280, 2290, 2330.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| **EXP-2200** | 7-stream North Star v6 ★★ | **WINNER** ★ | Sh 5.96, CAGR 146%, DD 5.7% | First 7-stream equal_risk_15% that clears 6.0 | Apr 7 |
| **EXP-2210** | XLF/XLI deep validation | WINNER | Sh 2.06 / 2.25 | Both survive realistic slippage | Apr 7 |
| EXP-2220 | 7-stream correlation matrix | INFRA | 6.69 / 7 eff streams | Near-orthogonal streams (median \|ρ\| 0.04) | Apr 8 |
| **EXP-2230** | 7-stream capacity audit ★ | INFRA ★ | — | Confirmed SLV as portfolio bottleneck at $16M | Apr 8 |
| **EXP-2240** | QQQ/IWM credit spreads ★ | **WINNER** | Sh 2.26, WR 90.5%, ρ=+0.11 | QQQ PASS, IWM data gap — the 8th stream | Apr 8 |
| EXP-2250 | 9-stream North Star v7 | SUPERSEDED | sparse Sh 6.55 | Superseded by v8 (ARCHIVED) | Apr 8 |
| EXP-2260 | SLV replacement v1 | KILLED | — | No clean fit, GLD 2× closest (ARCHIVED) | Apr 8 |
| EXP-2270 | XLF/XLI slippage analysis | INFRA | — | Both streams survive realistic costs | Apr 8 |
| **EXP-2280** | 20-fold walk-forward robustness ★★ | **WINNER** ★ | Sh 6.25 median | 100% positive folds, 60% > 6.0 — robustness certified | Apr 8 |
| **EXP-2290** | North Star v6 production deployment | INFRA ★ | — | Mac Studio launcher + 5-min monitor + daily report | Apr 8 |
| EXP-2300 | Paper trading deployment v1 | INFRA | — | First deployment pass | Apr 8 |
| EXP-2310 | AUM scaling analysis | KILLED | — | IronVault universe too narrow to answer (ARCHIVED) | Apr 8 |
| EXP-2320 | Comprehensive final report | SUPERSEDED | — | Superseded by EXP-2680 (ARCHIVED) | Apr 8 |
| **EXP-2330** | Monte Carlo stress test (6/6 gates) ★ | **WINNER** | Sh median 6.07, 0% paths breach 12% DD | The sign-off MC | Apr 8 |

---

## Wave 9 — Cost Reality + Broker Optimisation (April 8)

EXP-2340 → EXP-2480. 15 experiments. **The retraction wave.** Winners: 2370 ★★, 2420 ★★★, 2440, 2470 ★★. Killed: 5. Retractions: 4.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-2340 | Walk-forward DD fix (scale-factor cap) | INFRA | — | Solves the triplet DD inflation | Apr 8 |
| EXP-2350 | SLV replacement v2 (QQQ/TLT) | KILLED | — | Fails combined Sharpe + capacity bar (ARCHIVED) | Apr 8 |
| EXP-2360 | Robust covariance bake-off | **RETRACT** | Sh 11.73 (retracted) | Smeared inputs inflated Sharpe — headline pulled | Apr 8 |
| **EXP-2370** | DD Circuit Breaker ★★ | **WINNER** ★★ | 24% → 6.77% worst-fold DD | **Sharpe UP after flattening** — the critical risk win | Apr 8 |
| EXP-2380 | Futures calendar capacity | KILLED | — | GC/SI futures ADV ≈ ETF options, hypothesis rejected (ARCHIVED) | Apr 8 |
| EXP-2390 | Audit of EXP-2360 smeared-input | RETRACT | — | Formal retraction doc for 2360 | Apr 8 |
| EXP-2400 | Combined best-of (Ledoit-Wolf) | RETRACT | — | Headline retracted by 2450; covariance math still used | Apr 8 |
| EXP-2410 | Production paper-trading config | INFRA | — | Final 7-stream deployment shape | Apr 8 |
| **EXP-2420** | Real transaction cost model ★★★ | **WINNER** ★★★ | Baseline net 4.49 | Gross 5.96 → net 4.49 after real costs — the floor | Apr 8 |
| EXP-2430 | Capacity-optimized portfolio | KILLED | — | Dropping SLV reveals XLI as the new bottleneck (ARCHIVED) | Apr 8 |
| EXP-2440 | Cost-aware optimization (width lever) | WINNER | +0.68 ΔSharpe | Full combo recovers gross | Apr 8 |
| EXP-2450 | Sparse combined honest retraction | RETRACT | — | Formal retraction doc for 2400 | Apr 8 |
| EXP-2460 | Zero-cost T+V overlay | KILLED | −0.15 Δ | Negative on diversified portfolio (ARCHIVED) | Apr 8 |
| **EXP-2470** | Execution optimization stack A+B+C+D ★★ | **WINNER** ★★ | +0.33 ΔSharpe, −503 bps/yr | Limit-at-mid + EOD + route + combo | Apr 8 |
| EXP-2480 | 3-sleeve high-capacity architecture | KILLED | −0.33 Δ, 1.31× cap | Two honest findings (ARCHIVED) | Apr 8 |

---

## Wave 10 — Commission-Free + Phase 8 Prep (April 8-9)

EXP-2500 → EXP-2930. 22+ experiments. **The headline wave.** Winners: 2510, 2540, 2560, 2570 ★★★, 2580, 2590, 2600, 2630, 2770, 2830, 2840, 2890, 2930.

| ID | Name | Status | Metric | Finding | Date |
|---|---|---|---|---|---|
| EXP-2500 | True net backtest | INFRA | Sh 3.89 | Cost-aware params DESTROY alpha (still infra) | Apr 8 |
| **EXP-2510** | Commission-free broker analysis ★ | **WINNER** | IBKR 5.20 / Tasty 5.40 / Alpaca 6.00 | 3 brokers × 3 cost paths — Alpaca wins | Apr 8 |
| EXP-2520 | Paper-trading deployment package | INFRA | — | Mac Studio ready | Apr 8 |
| EXP-2530 | MASTERPLAN v8 + Apr-8 summary | INFRA | — | Pre-headline snapshot | Apr 8 |
| **EXP-2540** | Regime-conditional TC model | WINNER | +0.83 ΔSharpe | Skip HIGH/CRISIS VIX regimes → earn slot | Apr 8 |
| EXP-2550 | Net Sharpe recovery pathway | MARGINAL | 4.53 | Arithmetic doesn't hold; math correction | Apr 8 |
| **EXP-2560** | Trade frequency compression | WINNER | Sharpe 6.39 | Per-stream cadence optimization | Apr 8 |
| **EXP-2570** | Commission-free net Sharpe 6.00 ★★★ | **WINNER ★★★** | Net Sh 6.00, CAGR 93%, DD 4.2% | **THE HEADLINE.** 3 of 4 rails MET on net | Apr 8 |
| **EXP-2580** | SPY weekly credit spreads ★ | WINNER | Sh 0.66, ρ=+0.13, $7.6B cap | Genuine diversifier + capacity lever | Apr 8 |
| **EXP-2590** | QQQ credit spreads capacity deep dive ★ | **WINNER** | +0.40 ΔSharpe, 1.31× cap | 8-stream Sharpe 4.94, 4/4 gates | Apr 8 |
| EXP-2600 | North Star v8 (QQQ added) | WINNER | Sharpe 6.87 gross | The official 8-stream headline config | Apr 8 |
| EXP-2610 | SPY weekly integration | MARGINAL | — | Great diversifier, vol-dilution trap | Apr 8 |
| EXP-2620 | Alpaca paper-trading connector | INFRA | — | 7-stream bespoke connector | Apr 8 |
| EXP-2630 | OOS regime stress test | WINNER | 2/3 clean + 1 marginal | CB defends; 12 bp slippage in 90-day VIX scenario | Apr 8 |
| EXP-2640 | VIX stress hardening | INFRA | — | Hardening pass | Apr 8 |
| EXP-2650 | Multi-expiry capacity | INFRA | — | Calendar depth audit | Apr 8 |
| EXP-2660 | Multi-underlying scaling audit | INFRA | — | Capacity probe | Apr 8 |
| EXP-2670 | Paper trading go/no-go checklist | INFRA | — | 6-gate framework for paper → live | Apr 8 |
| EXP-2680 | MASTERPLAN v10 + final Go/No-Go report | INFRA | — | v10 masterplan + north_star_v8_final.html | Apr 8 |
| EXP-2690 | Production signal generators | INFRA | — | 8 generator entry points | Apr 8 |
| EXP-2700 | Reproducibility audit | INFRA | — | — | Apr 8 |
| EXP-2710 | XLE integration | MARGINAL | — | Energy sector exploratory | Apr 8 |
| EXP-2720 | DD recovery dynamics | INFRA | — | — | Apr 8 |
| EXP-2730 | WF robustness on v8a NET — SHIP | WINNER | pooled 6.16, median 6.94, 70% ≥6 | NET walk-forward on v8a | Apr 8 |
| EXP-2750 | Out-of-distribution regime stress | INFRA | 4 synthetic scenarios | Stress-test harness | Apr 8 |
| EXP-2760 | Literature survey — Sharpe 6.00 realism | INFRA | k=0.5-0.7× | Live Sharpe degrades to 0.5-0.7× backtest → sets up EXP-2840 | Apr 8 |
| EXP-2770 | Code cleanup + v8a documentation | INFRA | 23 archived | `compass/archive/` + README + registry 3.0 | Apr 8 |
| EXP-2830 | Paper Trading Orchestrator v2 | INFRA | — | main.py cron scaffold for v8a | Apr 9 |
| EXP-2840 | Backtest-to-live degradation model | INFRA ★ | k*=0.61 for Sh ≥3 | **Carlos: expect 3.0, not 6.0; v5_hedge may be −0.27** | Apr 9 |
| EXP-2890 | Alpaca integration scaffold | INFRA ★ | — | `compass/alpaca_connector.py` clean seam | Apr 9 |
| EXP-2930 | AUM scaling roadmap $50M → $1B | INFRA ★ | $699/mo at S2 | Polygon Starter + CBOE DataShop = capacity unlock | Apr 9 |

---

## Retractions (4)

Honest corrections where a headline number was pulled after audit. **The files are kept in `compass/` root because the underlying math is still used** (covariance, sparse handling) — only the headline Sharpe was retracted.

| ID | Retracted claim | Audit | Fate |
|---|---|---|---|
| EXP-2360 | Robust covariance Sharpe 11.73 | EXP-2390 | Headline pulled; Ledoit-Wolf math kept |
| EXP-2390 | (was the audit itself) | — | Formal retraction doc |
| EXP-2400 | Combined best-of Sharpe 11.73 | EXP-2450 | Headline pulled; covariance kept |
| EXP-2450 | (was the audit itself) | — | Formal retraction doc |

---

## Archived Experiments (23 files in `compass/archive/`)

Moved out of `compass/` root by EXP-2770. Preserved with full git history; none imported by live production code.

### Honest kills (19)
EXP-1760, 1910, 1920, 1930, 1940, 1950, 1990, 2030, 2090, 2150, 2170, 2190, 2260, 2310, 2350, 2380, 2430, 2460, 2480

### Superseded (4)
EXP-2050 (→ v8), 2100 (retracted), 2250 (→ v8), 2320 (→ 2680)

---

## Quick Lookup: Winners by Contribution Type

**Foundation (production spine):**
EXP-1220 (SPY foundation), EXP-1770 (GLD/SLV calendars), EXP-1780 (Crisis Alpha v5), EXP-2020 (cross-vol arb), EXP-2200 (7-stream base), EXP-2240 (QQQ), EXP-2600 (v8 headline)

**Overlays that made it in:**
EXP-1750 (PCR +0.78), EXP-1880 (FOMC +0.60), EXP-1970 (VoV +0.86), EXP-2000 (V+F+PCR +0.88), EXP-2070 (VIX term +1.42), EXP-2120 (T+V+F +0.95)

**Risk + execution:**
EXP-1890 (Portfolio Risk Manager), EXP-2370 (DD circuit breaker), EXP-2420 (TC model), EXP-2470 (execution stack A+B+C+D), EXP-2540 (regime TC)

**Broker + cost:**
EXP-2510 (broker analysis), EXP-2570 (Alpaca Sh 6.00 ★★★), EXP-2560 (trade freq compression)

**Validation:**
EXP-2280 (20-fold WF), EXP-2330 (MC stress 6/6), EXP-2630 (OOS regime stress), EXP-2730 (NET walk-forward), EXP-2840 (live degradation)

**Deployment infra:**
EXP-2290 (paper deploy), EXP-2670 (go/no-go checklist), EXP-2680 (MASTERPLAN v10), EXP-2690 (signal generators), EXP-2770 (cleanup), EXP-2830 (orchestrator), EXP-2890 (Alpaca connector)

**Capacity planning:**
EXP-2140 (capacity baseline), EXP-2230 (7-stream capacity), EXP-2590 (QQQ deep dive), EXP-2930 (AUM roadmap)

---

## Quick Lookup: Notable Failures & Their Lessons

| Category | Exp | Lesson |
|---|---|---|
| **Meta-learning doesn't beat stacking** | EXP-1990 | 10 features × 141 trades = guaranteed overfit |
| **Short-window momentum is thin** | EXP-1940 | 5 ETFs can't carry cross-sectional momentum |
| **Reactive DD triggers don't predict** | EXP-2190 | Tail-risk parity is all hindsight |
| **Weight-shuffle can't fix capacity** | EXP-2350/2430/2480 | Dropping SLV surfaces XLI as new bottleneck |
| **Futures aren't 10× deeper** | EXP-2380 | GC/SI futures ADV ≈ ETF option ADV (~$300M) |
| **Pre-pandemic seasonality dead** | EXP-2090 | COVID regime break destroyed stable calendar patterns |
| **Smeared inputs inflate** | EXP-2360/2400 | Don't roll a covariance on residualized inputs and call it a Sharpe |
| **3-sleeve collapse kills diversification** | EXP-2480 | Going narrow loses +0.33 Sharpe to save 1.31× capacity |
| **Cost-aware optimization can destroy alpha** | EXP-2500 | Width lever vs premium must balance — EXP-2440 found the sweet spot |
| **Crypto small-sample is unsafe** | EXP-1760 | 24 months of IBIT is not enough data |

---

## Glossary

- **PASS / WINNER** — cleared OOS gates, currently in production or slated for production
- **FAIL / KILLED** — honest negative; failed OOS or gate tests; archived
- **MARGINAL** — kept for ensembles or as a backup lever
- **RETRACT** — headline number pulled after audit; some infra may still be imported
- **SUPERSEDED** — replaced by a later experiment in the same family
- **INFRA** — data pipeline, risk component, reporting, or deployment machinery
- **★** — notable production value
- **★★** — critical dependency
- **★★★** — single-most-important production contribution

---

## See Also

- `MASTERPLAN.md` v10 — canonical project state and decision framework
- `compass/README.md` — v8a architecture reference + signal flow diagram
- `compass/archive/README.md` — archived experiment index
- `compass/reports/master_dashboard_apr8.html` — single-file interactive dashboard
- `compass/reports/north_star_v8_final.html` — Carlos go/no-go package
- `compass/reports/exp2930_aum_scaling_roadmap.html` — path from $50M to $1B
- `experiments/registry.json` — machine-readable registry (schema 2.0 legacy + new wave metadata)

*Rule Zero held throughout. All data from real sources: IronVault options_cache.db, Yahoo Finance, federalreserve.gov.*
