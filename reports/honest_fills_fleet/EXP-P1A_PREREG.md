# EXP-P1A PRE-REGISTRATION — Defined-risk premium on sector/index ETFs (XLI + QQQ)

**Date:** 2026-07-12 · **Author:** cc1 · **Status: SIGNED OFF — committed before any run.**
**Program:** `research/PROFITABILITY_PROGRAM.md` §EXP-P1A · **Friction basis:** `research/FRICTION_LEDGER.md` (cited throughout, per program rule)
**Governance:** new-mechanism confirmation required before commit (this document is that request). Maximus ruling 2026-07-12 on QQQ admissibility is recorded in §2. Carlos program GO 2026-07-12.

## 1 · Scope changes forced by the friction ledger (before any backtest)

The slate's P1A was "XLF/XLI defined-risk premium." The ledger (`EXP-P0A`, committed `811166f`) rules under the program's DOA criterion:

- **XLF is excluded entirely.** All 8 XLF vertical classes are DOA (median credits $3–24 vs the $35.20 threshold); the XLF 30-DTE iron condor clears DOA by $0.6 (median $71 vs $70.4) — within measurement noise of the line, on close-based marks. Trading the flagship sector ETF at our friction is not viable; this prereg does not test it.
- **XLI survives narrowly:** the 30-DTE wide 2 %-OTM vertical (median $38, min-edge 46 %) and the 30-DTE iron condor (median $128, min-edge 27.5 %).
- **QQQ is friction-viable** (verticals 7–13 %, ICs 8–9 %) and admissible per Maximus's ruling (§2).

## 2 · Mechanism, provenance, and the QQQ underlier-distinction argument

**Hypothesis:** defined-risk option premium on XLI and QQQ has positive expectancy net of measured friction at weekly cadence with a rich-premium floor, where SPY put-credit verticals (the closed family) failed.

**Mechanism (new underlier):** dealer/end-user flow composition differs by underlier — index-hedging supply/demand concentrates in SPX/SPY complex; sector and NDX-complex books carry different positioning imbalances (dealer-positioning literature surveyed in `research/lit_review_2024_2026.md`; v8a per-stream attribution research pre-dating the mined search identified XLF/XLI streams as highest-attribution — provenance-clean, though its XLF half is now friction-dead).

**QQQ distinction (required by ruling):** (a) different index complex (NDX vs SPX) with materially different skew/vol-surface dynamics and dealer positioning; (b) QQQ was **never touched by the mined search** (2020–2024 mining = SPY verticals only; QQQ appears only in the V8A portfolio proxy, a different strategy); (c) different friction/credit profile (ledger). Honest counterpoint, stated plainly: QQQ-SPY correlation ≈ 0.9, so this is the weakest admissible underlier distinction — which is why every QQQ variant carries the stricter worst-year gate (≥ −10 %) per the ruling, same as XLI.

**Base-config provenance (not mined-leaderboard-derived):** weekly cadence and the credit floor enter the *base*, not the variant axis, on causal grounds pre-approved by the governance decision's one-way door: "overlapping short-vol positions stack tail exposure" (causal statement, supported by the live broker record and literature) and the P0A friction arithmetic (measured facts). Exits use family defaults (PT 50 % / SL 2.0×); the mined window is used only in reject-mode (no SL 1.0×, no delta-targeted strikes).

## 3 · Fixed base configuration (all variants)

| Parameter | Value | Basis |
|---|---|---|
| Window | **2020-01-02 → 2024-12-31 only** (in-sample dev; holdout untouched) | governance |
| Fill model | **marketable only** | program rule |
| Entry cadence | Mondays only (1 entry/underlier/week max) | causal (overlap-stacking), §2 |
| Credit floor at entry | credit ≥ 2× structure friction ($35.20 verticals / $70.40 ICs) | P0A ledger, per-trade DOA test |
| DTE | 21–45, target 30 | ledger: 30-DTE classes are the viable ones |
| Sizing | flat 5 % max-loss/trade of $100k, non-compounding; ≤ 3 concurrent positions; ≤ 2 per expiration; ≤ 10 contracts | cc1 proposal §2 risk framework |
| Exits | PT 50 % of credit; SL 2.0× credit; manage_dte ≤ 5 (live semantics); no rolling | family defaults + live-code audit |
| VIX gate | no entries when VIX > 35 | live mechanism (risk_gate rule 7.5) |
| Direction | puts-only for verticals (bear-call finder disabled in harness); ICs entered regardless of regime (pure premium harvest — no regime/direction engine anywhere) | EXP-800 lesson: direction engines unvalidated |

## 4 · Variants (6 of ≤ 8 allowed; single-mechanism differences from base)

| # | Underlier | Structure / class (ledger row) | Differs from base only by | Ledger min-edge |
|---|---|---|---|---|
| A1 | XLI | put vertical, wide (~3 % of spot), 2 % OTM, 30 DTE | — (base, XLI) | 46 % ⚠️ |
| A2 | XLI | iron condor 30 DTE (4 %P/3 %C, wide) | structure | 27.5 % |
| A3 | QQQ | put vertical, wide, 2 % OTM, 30 DTE | underlier | 7.4 % |
| A4 | QQQ | put vertical, wide, 5 % OTM, 30 DTE | strike distance | 13.4 % |
| A5 | QQQ | iron condor 30 DTE (4 %P/3 %C, wide) | structure | 7.7–9.1 % |
| A6 | QQQ | as A3 **without** the credit floor | floor attribution (isolates the floor's effect) | 7.4 % |

No composites. No XLF. No parameter re-jitter of mined mechanisms (no SL/delta/cadence variants).

## 5 · Pass/fail (per variant; fixed before any run)

**ALL of:** total return > 0 · expectancy > $0 net of P0A friction · MaxDD ≥ −20 % · **worst calendar year ≥ −10 %** (stricter P1A gate, per program + Maximus ruling, applied to XLI *and* QQQ) · ≥ 40 closed trades · `fill_model_naive_fallbacks` ≤ 20 % of entries (else "fill-uncertain": cannot pass, only inform — XLI/QQQ have daily bars only, so this gate is live).

**Experiment-level outcomes:** any passer → candidate list for the single-use holdout decision (Carlos signs; nothing in this prereg touches data past 2024-12-31). All six fail → sector/index-ETF defined-risk premium closed at this friction; no parameter escalation; result recorded.

**Kill criteria (before/without full runs):** per-trade credit floor unfillable > 80 % of weeks in either underlier (structural, from entry logs) → that variant void, not "loosened"; `naive_fallbacks` > 20 % → variant graded fill-uncertain; any harness change after first result → whole prereg void, restart.

## 6 · Runner and runtime

`experiments/honest-fills-fleet/` harness (committed, used for the fleet + search): per-ticker engine configs; Monday gate + puts-only gate + credit-floor check as harness shims (same pattern as `search.py`; engine code untouched); IC path via engine's iron-condor finder with `neutral_regime_only: false`. 6 runs × ~3–6 min. Results to `results/p1a_{A1..A6}.json`; scored report `reports/honest_fills_fleet/EXP-P1A_RESULTS.md` with the standard machine-readable block. Zero spend.

## 7 · Sign-off block

- New-mechanism confirmation (Maximus/Carlos, in writing, per governance checklist): **APPROVED — Maximus, 2026-07-12** ("commit the prereg unchanged and run all six variants"); QQQ admissibility ruling same date.
- On sign-off: this file is committed **unchanged**, then runs execute. Any edit after sign-off requires re-sign-off.
