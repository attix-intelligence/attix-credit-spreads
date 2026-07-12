# Profitability Experiment Program

**Date:** 2026-07-12 · **Author:** cc1 (from Maximus's slate `PROFITABILITY_EXPERIMENT_SLATE.md`) · **For:** Carlos
**Status:** PROGRAM DESIGN — not a pre-registration. Each experiment becomes its own prereg (committed before any run) once approved, per the binding checklist in `reports/honest_fills_fleet/EXPECTANCY_SEARCH_GOVERNANCE_DECISION.md` (Maximus-approved, 2026-07-10).
**Ground rules inherited:** marketable fills only, everywhere. 2020–2024 = in-sample dev only, labeled as such. 2025–2026Q1 holdout is single-use, spent on the program's single best passer, Carlos signs the spend. New mechanisms only (underlier / structure / signal source); written provenance per variant; V1/V6 and every SPY put-credit-vertical variant stay closed. **No backtest has been run for this document.**

---

## 0 · Data audit (verified against `options_cache.db` / `historical_indices.sqlite`, 2026-07-12)

The slate's "have it" claims checked line-by-line — two corrections found:

| Data | Status | Detail |
|---|---|---|
| SPY options daily | ✅ | 4.61M bars → **2026-07-02**; plus 1.59M 5-min intraday bars 2020-01 → 2026-02-24 (SPY is the only underlier with intraday) |
| QQQ options daily | ✅ (stale) | 780k bars, ends **2025-12-19** |
| XLF / XLI options daily | ✅ | 244k / 201k bars → **2026-04-02** |
| GLD options daily | ✅ (stale) | 190k bars, ends **2025-12-19** |
| TLT options daily | ✅ (stale, unused so far) | **294k bars → 2025-12-19** — a new-underlier candidate nobody has touched |
| **SLV options** | ❌ **absent** | Slate's P1B says "have it" — we do not. Backfillable with the existing Polygon key (time, $0) |
| **VIX options** | ❌ **absent** | Slate's P1C "VIX call ladders" have no data; index-option availability on our Polygon tier unverified |
| XLE / XLK / SOXX daily | ⚠️ thin | 19–37k bars each; band-limited — usable for spot checks, not primary experiments |
| VIX / VIX3M / SPX indices | ✅ | full window (SQLite fallback path, post-8f1bc8c) |
| **VVIX** | ❌ absent | P1C's vol-of-vol trigger must use VIX/VIX3M inversion instead |
| FOMC / CPI / NFP calendars | ⚠️ 2026 only | `compass/orchestrator/calendars/{fomc,cpi,nfp}_2026.csv`; NFP 2020–2025 already reconstructed deterministically (`search.py` port). FOMC/CPI 2020–2025 need a one-time deterministic build from public schedules ($0, ~half day) |
| Dealer OI (for GEX) | ❌ | IronVault OI is NULL by convention; CBOE DataShop ~$50/yr, needs Carlos approval |

**Zero-spend backfill queue** (existing Polygon keys, time only): SLV listing+aggs; QQQ/GLD/TLT extension 2025-12→2026-07; FOMC/CPI 2020–2025 calendar build. Each follows the EXP-3570 backfill protocol (DB backup, probe cross-check, integrity counts).

**Fill-model caveat for all non-SPY underliers:** only daily bars exist, so FIX #3 marketable fills degrade to static day-limit semantics, and bars without opens book naively (counted in `fill_model_naive_fallbacks`). Every non-SPY prereg must report the fallback share and carries a fill-realism haircut until P0B live probes calibrate it.

## 1 · Program-wide gates (every experiment, no exceptions)

1. Prereg committed before any run; pass criteria **at least**: total return > 0, expectancy > $0 net of the P0A friction ledger, MaxDD ≥ −20 %, worst calendar year ≥ −15 %, ≥ 40 closed trades, **plus** `fill_model_naive_fallbacks` ≤ 20 % of entries (else the result is graded "fill-uncertain" and cannot pass, only inform).
2. Marketable fills only; P0A ledger cited in every prereg; new-mechanism confirmation in writing (Maximus or Carlos) before the prereg commit; provenance statement per variant.
3. 2020–2024 in-sample dev; single-use holdout as above; forward paper months are the only OOS after the holdout is spent.
4. Config-to-code parity audit precedes any live/paper deployment claim (standing item since the EXP-1220 dead-config finding).
5. Attribution before selection: single-mechanism variants before composites, always.

## 2 · The experiments

Ordered by **expected information gain per hour of effort** (§3 has the ranking table). "Runtime" = wall-clock per engine run observed on this box (fleet runs: 3–6 min per underlier-window); build time is the real cost.

---

### EXP-P0A · Friction Budget Ledger — *run first, kills ideas for free*

- **Hypothesis (measurement, not strategy):** for each structure × underlier, the minimum gross edge per trade needed to clear commissions + honest entry/exit spread cost at measured fill rates is computable from data we already have, and will disqualify some Phase-1/2 candidates before any backtest.
- **Mechanism/provenance:** measured execution facts — explicitly permitted by the governance one-way door (friction arithmetic is fact, not fitted parameter).
- **Data:** ✅ all in `options_cache.db` (per-leg commission $0.65 from the engine config; spread cost from bar OHLC; fill rates from the fleet's marketable runs: honest unfillable 23–60 %).
- **Output & pass/fail:** a committed table `research/FRICTION_LEDGER.md`: per (structure, underlier, width/DTE class) → friction $/trade and min-edge-%-of-credit. No pass/fail — it is an input. **Every subsequent prereg must cite it.**
- **Runner sketch:** pure-Python over `option_daily` (no engine): sample historical spreads per class, compute credit distributions, apply commission + FIX #3-style limit-fill test for cost realism.
- **Runtime:** ~2–4 h build + minutes to run. **Cost: $0. Can run immediately.**
- **Kill criterion (for downstream ideas):** any candidate whose median credit < 2× its friction budget is dead on arrival and its prereg is not written.

### EXP-P0B · Tradier Fill-Quality Probes — *live ground truth for the fill engine*

- **Hypothesis:** real fill rates / time-to-fill / effective slippage for 1-lot SPY (+1 sector ETF) spread orders at mid, mid−1¢, and marketable prices are measurably different from the FIX #3 model, and inside-NBBO posting (P1D's premise) captures part of the quoted spread.
- **Mechanism/provenance:** forward live data (always admissible); `research/MM_OPTIONS_FEASIBILITY.md`.
- **Data:** none needed — generates data. Fixed schedule (e.g., 2 probes/day × 4 weeks ≈ 40–60 lots), **not strategy signals**; every probe closed same day; 1-lot hard cap in config.
- **Pass/fail (prereg-able):** n ≥ 40 probes; deliverable = calibration table (fill probability by limit-vs-NBBO placement) with 95 % CIs; "pass" = CIs tight enough to bound the P1D uplift estimate within ±30 %.
- **Runner sketch:** small scheduler script → executor API (the audited order path), tagged `probe_`, auto-flatten by 15:45 ET; daily reconciliation against broker records (the IBKR-assessment tooling reused).
- **Runtime:** ~1 day build; 4 weeks calendar, ~zero attention. **Cost:** commissions, low hundreds of $. Needs Carlos nod on probe commissions only.
- **Kill criteria:** any probe unfilled-and-unflattened at EOD → halt probes, fix ops first. Slippage found *worse* than model → all Phase-1 results get re-haircut before any holdout spend.

### EXP-P1A · Defined-risk premium on sector ETFs (XLF/XLI) — *new underlier*

- **Hypothesis:** short defined-risk premium (put credit verticals and iron condors) on XLF/XLI has positive expectancy net of friction at weekly-or-slower cadence with rich-premium floors, where SPY failed.
- **Mechanism/provenance:** sector-ETF option books carry different dealer-flow imbalances than SPY's (retail/institutional hedging mix), per the dealer-positioning literature surveyed in `research/lit_review_2024_2026.md`; XLF/XLI were the highest-attribution streams in v8a portfolio research (registry, pre-dating the mined search). Cadence/floor settings are justified causally (overlap-stacking; P0A ledger) — *not* by V1/V6 rank. ⚠️ Honesty note: this is the weakest new-mechanism claim in the program (verticals on a correlated equity underlier); it requires the written Maximus/Carlos confirmation gate more than any other item, and the prereg must argue the underlier distinction explicitly.
- **Data:** ✅ XLF/XLI → 2026-04-02, daily bars only (fill-realism haircut applies).
- **Pass/fail:** program-wide gates; additionally worst-year ≥ −10 % (stricter, because 2022's financials/industrials bear is in-window and this family's known failure mode is bear years).
- **Runner sketch:** `experiments/honest-fills-fleet/run.py` generalized: engine already takes any ticker with cached marks; per-underlier configs, single-mechanism variants (cadence, credit floor, IC-vs-vertical) pre-registered, ≤ 8 variants total across both underliers.
- **Runtime:** ~1 h adaptation + 3–6 min/run. **Cost: $0. Can run immediately after P0A.**
- **Kill criteria:** P0A ledger DOA test; `naive_fallbacks` > 20 %; both underliers negative at every cadence → family closed, no parameter escalation.

### EXP-P1F · Rate-vol premium on TLT — *new underlier, new macro driver* (NEW — added by cc1)

- **Hypothesis:** defined-risk premium selling on TLT (put and call credit verticals; strangle-of-verticals) has positive expectancy in a book whose risk driver (rate volatility) is distinct from the equity-vol book that just failed.
- **Mechanism/provenance:** the bond variance-risk-premium literature documents persistent overpricing of Treasury-vol (e.g., Choi–Mueller–Vedolin, *Bond Variance Risk Premiums*; surveyed in `research/lit_review_2024_2026.md`); mechanism is the same VRP economics on a different-macro underlier — squarely a "new underlier" under the checklist, with zero derivation from the mined leaderboard (TLT has never been backtested here: 294k bars sitting unused).
- **Data:** ✅ TLT daily → 2025-12-19 (extendable, $0); daily-bars haircut applies.
- **Pass/fail:** program-wide gates; plus the 2022 clause inverted — 2022 was a *rates* bear (TLT −31 %), so the prereg must show worst-year ≥ −15 % **including 2022**, which is the honest stress test for this idea.
- **Runner sketch:** same engine path as P1A (verticals both directions; the engine's bear-call finder gives call-side coverage); ≤ 6 variants.
- **Runtime:** ~1 h adaptation + minutes/run. **Cost: $0. Can run immediately after P0A.**
- **Kill criteria:** DOA on friction ledger (TLT option spreads are wider than SPY's — this may die in P0A, which is exactly what P0A is for); both directions negative 2020–2024 → closed.

### EXP-P2B · Event-premium harvesting (FOMC/CPI/NFP) — *new signal source*

- **Hypothesis:** index/ETF option premium into scheduled macro events is systematically overpriced; selling defined-risk structures **only** when a measured pre-event richness threshold is met (and being flat otherwise) is positive-expectancy, with overlap impossible by construction (~30 events/yr).
- **Mechanism/provenance:** event-vol overpricing literature (`research/lit_review_2024_2026.md`); EXP-3311's NFP gate is *rejection-side* evidence (event days carry uncompensated gap risk for always-on sellers) — this flips the same fact into a conditional seller. Signal source = event calendar + measured richness: new under the checklist.
- **Data:** ⚠️ calendars 2026-only in repo; FOMC/CPI 2020–2025 need the deterministic build ($0, ~half day). Richness measure from cached option marks (straddle price vs trailing realized move). SPY event-structures OK on cached marks; note SPY *verticals* remain closed — this prereg uses **iron flies / defined-risk straddade structures or QQQ/XLF underliers** to stay clear of the closed family, decided at prereg time with Maximus sign-off.
- **Pass/fail:** program-wide gates with trade-count floor kept at ≥ 40 (≈ 1.5 yrs of events × structures — window supports ~150 events).
- **Runner sketch:** calendar builder + richness computation (pure Python over marks) + direct-marks multi-leg harness (shared with P1B/P1C/P1E, see below).
- **Runtime:** ~1.5 d build (calendar + richness + harness share) + minutes/run. **Cost: $0.**
- **Kill criteria:** richness signal shows no cross-sectional spread (overpricing indistinguishable from zero pre-cost) → dead before backtest; DOA on ledger.

### EXP-P1B · Calendar/diagonal spreads on GLD (+SLV after backfill) — *new structure*

- **Hypothesis:** term-structure VRP (short front-month, long back-month) on metals ETFs is positive-expectancy net of friction, with tail risk structurally capped by the long-dated leg (addresses "2022" by construction, not by gate).
- **Mechanism/provenance:** term-structure carry literature; v8a's GLD/SLV calendar streams (research pre-dating the mined search — provenance-clean). Structure = calendars: new under the checklist.
- **Data:** ✅ GLD → 2025-12-19; ❌ SLV absent (backfill first, $0). Daily-bars haircut applies.
- **Pass/fail:** program-wide gates; plus max single-trade loss ≤ 1.5× the modeled max (calendar risk models are mark-dependent; a breach means the pricing path is untrustworthy, which fails the experiment regardless of P&L).
- **Runner sketch:** **new direct-marks harness** (the engine only knows verticals/ICs): positions as leg lists over `option_daily`; entry = FIX #3-semantics limit test on the day bar per leg-pair; daily MTM from closes; exits on PT/time/roll rules. This harness is shared by P1B/P1C/P1E/P2B — build once (~1–1.5 d), amortized.
- **Runtime:** harness build + minutes/run. **Cost: $0 (GLD now; SLV after backfill).**
- **Kill criteria:** DOA on ledger (calendars = 2 spreads of friction per round trip — the ledger may kill this class outright); >20 % of days missing back-leg marks → data insufficient, not a strategy verdict.

### EXP-P1E · Skew-harvest broken-wing butterflies / put ratios — *new structure* (NEW — added by cc1)

- **Hypothesis:** harvesting equity index put-skew with structures that are tail-flat or tail-long (broken-wing butterflies; 1×2 put ratios with defined width) achieves positive expectancy where short verticals died, because the structure sells the overpriced wing while capping or inverting the crash payoff.
- **Mechanism/provenance:** skew-premium literature (steep index put skew persistently overpriced relative to realized jump risk — surveyed in `research/lit_review_2024_2026.md`); the mined window contributes only the *rejection* fact that naked-short-tail verticals fail — the structure is new under the checklist (payoff sign differs in the tail; this is not a vertical variant).
- **Data:** ✅ SPY marks incl. intraday (best fill realism in the program); QQQ as second underlier.
- **Pass/fail:** program-wide gates; plus 2020-03 and 2022 sub-window P&L reported separately (the structure's entire claim is tail behavior — a passer that bled in both stress windows fails on mechanism even if the total passes).
- **Runner sketch:** direct-marks multi-leg harness (shared build, above); ≤ 6 variants (wing geometry × DTE class), single-mechanism first.
- **Runtime:** shared harness + minutes/run. **Cost: $0.**
- **Kill criteria:** DOA on ledger (3–4 legs of friction); fill test shows multi-leg marketable fills < 40 % on SPY intraday bars → structure untradeable at our size/venue, closed.

### EXP-P1C · Long-vol convexity book — *new structure (the other side)*

- **Hypothesis:** a small book of cheap convexity (SPY put backspreads; VIX calls **if** data is acquired) bought only when VIX/VIX3M inverts from below, loses small in calm regimes and pays multiples in stress — positive expectancy is *not* required standalone if it passes as a portfolio hedge (see pass/fail).
- **Mechanism/provenance:** convexity/crisis-alpha literature; v8a stream-8 VIX-ladder research (pre-dating the search). Structure = net-long options: new.
- **Data:** ✅ SPY backspreads; ❌ VIX options absent (Polygon-tier availability unverified — treat VIX legs as out of scope until confirmed); VVIX absent → trigger is VIX/VIX3M only.
- **Pass/fail (dual-track, pre-registered as such):** *standalone* = program-wide gates; *hedge-mode* = allowed to run at small negative carry (≥ −3 %/yr) **iff** 2020 + 2022 sub-windows each return > +10 % — the criterion a structural hedge must meet to earn a book slot alongside any future premium passer.
- **Runner sketch:** direct-marks harness; trigger evaluation from indices DB; ≤ 5 variants.
- **Runtime:** shared harness + minutes/run. **Cost: $0** (SPY side).
- **Kill criteria:** calm-regime bleed > 6 %/yr under marketable fills (double the budget) → dead; trigger fires < 8× in 2020–2024 → sample too thin, park.

### EXP-P1D · Execution alpha — inside-NBBO liquidity provision — *mechanism-agnostic multiplier*

- **Hypothesis:** posting inside the NBBO captures 25–50 % of the quoted spread vs paying it, uplifting *every* structure's expectancy by a measurable, strategy-independent amount.
- **Mechanism/provenance:** `research/MM_OPTIONS_FEASIBILITY.md`; microstructure literature. Signal source = none (execution layer).
- **Data:** ⚠️ backtest side is crude (no NBBO history in cache — hourly CBOE quotes at best); **the real instrument is P0B's live probes.** This experiment is therefore sequenced *behind* P0B and consumes its calibration table.
- **Pass/fail:** measured live: fill-probability-weighted effective spread at inside-posting beats marketable by ≥ 15 % of quoted spread with 95 % CI excluding zero (from P0B data, n ≥ 40).
- **Runner sketch:** analysis of P0B fills + a haircut/uplift module added to the shared harness so every other prereg can run "marketable" and "calibrated-inside" columns side by side (marketable remains the gating column — program rule).
- **Runtime:** ~half day analysis once P0B lands. **Cost: $0 incremental.**
- **Kill criteria:** P0B shows inside-posting fill probability < 25 % → uplift illusory, closed; any sign the probes chase price → halt (ops).

### EXP-P2A · Dealer-GEX regime gate — *new signal source (needs $ approval)*

- **Hypothesis:** premium-selling expectancy is conditional on dealer gamma positioning; gating any Phase-1 passer (or the P2B event seller) to net-short-dealer-gamma regimes materially improves its expectancy.
- **Mechanism/provenance:** dealer-hedging-flow literature (Dew-Becker line, surveyed in `research/lit_review_2024_2026.md` — note: the slate's `DEALER_GEX_LITERATURE.md` filename doesn't exist in-repo; reconcile citation at prereg time); prior sprint could not test it because IronVault OI is NULL and the volume proxy was rejected as inconclusive — so this signal is genuinely untested, not mined.
- **Data:** ❌ requires real OI history (CBOE DataShop ~$50/yr). **Blocked on Carlos approval.**
- **Pass/fail:** the gate must improve a base strategy's in-sample expectancy by ≥ 25 % *and* not reduce trade count below 40; evaluated only on top of an already-passing or near-passing base (a gate on a ruin is still a ruin — the fleet proved that).
- **Runner sketch:** OI ingest → daily GEX estimate → gate flag consumed by the shared harness; ≤ 3 gate definitions pre-registered.
- **Runtime:** ~1 d ingest/build after data arrives. **Cost: ~$50/yr.**
- **Kill criteria:** GEX regime split shows no expectancy difference on the *measurement* (pre-strategy) level → dead before any strategy run; base candidates all failed Phase 1 → park until one exists.

---

## 3 · Ranking by expected information gain per hour

"Info gain" = how much the result changes what we do next, divided by effort hours (calendar time noted separately). Zero-spend items marked ●.

| Rank | Exp | Why this position | Effort to first result | Immediate? |
|---|---|---|---|---|
| 1 | **P0A friction ledger** ● | Prunes every downstream idea; hours of work; converts 8 open questions into ≤ 5 | ~half day | **Yes** |
| 2 | **P1A XLF/XLI** ● | Harness exists; minutes per run; first genuine new-underlier read on the only structure we can already backtest | ~1 h + runs | **Yes** (after P0A) |
| 3 | **P1F TLT** ● | Same harness, fully untouched underlier, distinct macro driver; 2022 gives it a built-in stress test | ~1 h + runs | **Yes** (after P0A) |
| 4 | **P0B fill probes** | Small effort, 4-week calendar tail; calibrates every other result; the only forward-data item | ~1 d build | Yes (probe commissions) |
| 5 | **P2B event premium** ● | Crisp hypothesis, overlap-free by construction; needs calendar build + shared harness | ~1.5 d | Yes |
| 6 | **P1E BWB/skew** ● | New payoff shape on our best data (SPY intraday); shares harness cost with P1B/P1C/P2B | ~1 d (shared) | Yes |
| 7 | **P1B GLD calendars** ● | Structurally addresses the bear-year problem; friction-heavy (may die in P0A); SLV needs backfill | shared harness | Yes (GLD) |
| 8 | **P1C long-vol** ● | Valuable mainly as hedge-mode for a future book; standalone pass unlikely; cheap once harness exists | shared harness | Yes (SPY side) |
| 9 | **P1D inside-NBBO** | High leverage but blocked on P0B's 4-week calendar; backtest-side evidence is weak alone | ~half day post-P0B | No (sequenced) |
| 10 | **P2A dealer GEX** | Potentially the most important *signal* in the program, but blocked on $ approval + ingest, and needs a base strategy worth gating | ~1 d post-data | No ($ + prereq) |

**Suggested wave plan:** Wave 1 (this week): P0A → P1A + P1F preregs; P0B build+start; calendar/harness build begins. Wave 2: P2B, P1E, P1B, P1C preregs on the shared harness. Wave 3: P1D analysis; P2A if approved and if Wave 1–2 produced a base worth gating.

## 4 · Carlos decision list

1. Approve the program frame (this document) — each item then goes to individual prereg with the new-mechanism written confirmation.
2. Approve P0B probe commissions (low hundreds of $, 1-lot, same-day-flat, fixed schedule).
3. Approve ~$50/yr CBOE DataShop for P2A (can wait for Wave 3).
4. Standing items unchanged: EXP-800 Tradier halt-and-drain + live-authority pull; config-to-code parity audit; dashboard credential rotation.

## 5 · What is deliberately NOT in this program

- Any SPY put-credit-vertical variant, any V1/V6 descendant, any parameter re-jitter of the mined 12 — closed by the signed governance decision.
- Leverage, wider strikes, or sizing escalation as "edge" — established anti-improvements.
- ML overlays — nothing to overlay until a base mechanism passes; the EXP-503 lesson stands.
- Any holdout touch: no experiment in this document reads a single bar past 2024-12-31 until Carlos signs the one-shot spend for the program's best passer.
