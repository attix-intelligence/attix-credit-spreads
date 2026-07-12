# RM Menu Evaluation — Atlas's EXP-800 Research Menu vs Governance & Program

**Date:** 2026-07-12 · **Author:** cc3 (for Maximus → Carlos) · **Task:** evaluate `research/EXP800_RESEARCH_MENU_ATLAS.html` (RM-A1..RM-F1)
**Evaluated against:** `reports/honest_fills_fleet/EXPECTANCY_SEARCH_GOVERNANCE_DECISION.md` (signed, binding) · `EXPECTANCY_SEARCH_RESULTS.md` (the mined 12) · `research/PROFITABILITY_PROGRAM.md` (approved) · `reports/honest_fills_fleet/EXP-P1A_RESULTS.md` · `research/FRICTION_LEDGER.md` (P0A)
**No backtest was run for this evaluation.**

---

## Bottom line

The menu is honest analysis with a fatal jurisdiction problem: **most of it re-opens the strategy family the signed governance decision closed, on the exact window it classified as mined** — and five of its items are near-verbatim re-runs of variants that already failed the pre-registered expectancy search (V4/V5/V6/V7/V8/V10 among the mined 12). Atlas did not have the governance decision in its inputs (its basis line cites only the reparam report and FIX #3 runs), and to its credit it reaches the program's conclusion on its own: ~15–20% odds, and the likeliest survivor "is effectively a different strategy inheriting EXP-800's plumbing." That different strategy — new structure / new underlier / new signal, honest fills, prereg discipline — **is the already-approved profitability program**. The menu's pivot branch is where we already live.

**Verdicts: 0 ADOPT (as backtest sweeps) · 2 ADOPT-AS-PROCESS · 4 ALREADY-COVERED · 8 BLOCKED-BY-GOVERNANCE.**

**One red flag needing immediate correction if anything from the menu is ever run:** RM-F1's protocol sets test = **2024-01 → 2026-04** with "one look at test per candidate" across ~130 runs. That window **contains the single-use 2025–2026Q1 holdout**. Running the menu as written would burn the program's only unmined data on dozens of looks at a closed family. This alone disqualifies the menu's execution plan in its current form, independent of the per-item verdicts.

## Verdict table

| ID | Item | Verdict | Governance / overlap basis |
|---|---|---|---|
| RM-A1 | DTE × OTM × width grid (80 cells) | **BLOCKED-BY-GOVERNANCE** | Textbook "parameter re-jitter" of the closed SPY-vertical family on the mined 2020–2024 window — the stop rule's named case. The informational content (premium vs friction by structure class) is already delivered measurement-side by P0A's ledger without strategy backtests. |
| RM-A2 | Delta-targeted strikes | **BLOCKED** (and empirically refuted) | = mined **V4/V5** (Δ0.15: −103%, Δ0.10: −96%, both ruins; V11 combo −106%, worst result of the search). One-way door: negative findings stand; no re-test. |
| RM-B1 | Credit-to-width floor sweep | **BLOCKED** | = mined **V6** (floor 10%: −10.8%, killed by 2022). A floor-value sweep is jitter on a mined mechanism; "weekly cadence + credit floor" was the *specific* prereg the governance decision refused to write (option-a rejection). |
| RM-B2 | Entry time-of-day | **ADOPT-AS-PROCESS** (execution layer) | The real content is a measured execution fact (09:30:02 opening-rotation quotes ~2.5× marketable), not a strategy parameter. Adopt: (a) P0B calibration reports fill quality by slot (its 10:15/13:45 slots already instrument this live); (b) program-wide fill-model hygiene rule — no backtest entry priced off pre-09:35 prints. As an EXP-800 rescue sweep it stays blocked. |
| RM-B3 | Stale-mark sanity gate | **ALREADY-COVERED** (ops hygiene) | The honest fill model exists precisely to kill phantom prices in backtests; live-side, P0B skips absent/zero/crossed quotes by design and the scanner has a fresh-quote guard. Atlas itself grades it "hygiene, not edge." Fold the k×prior-close check into the execution layer if not already present; no prereg. |
| RM-C1 | VIX-level buckets | **BLOCKED** | Post-hoc bucket selection on 383 mined-window fills is the multiple-comparisons machine the search shut down; the search's own gates (V9/V10/V12) proved protections bound losses but create no expectancy — "a gate on a ruin is still a ruin" (program P2A kill language). |
| RM-C2 | IV-rank / VRP entry gate | **BLOCKED as EXP-800 rescue; measurement component ALREADY-COVERED** | Gating the closed family = still the closed family. The genuinely sound part — an IV-richness/VRP series from real marks — is exactly P2B's pre-event richness measure; build it once there, strategy-independent. Program rule: gates are evaluated only on an already-passing base, and none exists. |
| RM-C3 | Term-structure (contango) gate | **BLOCKED** (and empirically refuted) | = mined **V10** verbatim (VIX<VIX3M gate: −68.8%). |
| RM-C4 | Day-of-week / FOMC-CPI avoidance | **ALREADY-COVERED** (P2B) / BLOCKED as rescue | Event *avoidance* on this family = mined **V9** (NFP gate: −70.7%). The program already flips the same fact into the stronger design: P2B sells event premium *conditionally* on richer structures. DOW slicing: Atlas's own "severe multiple-comparisons risk" note is correct — never as a selection axis. |
| RM-D1 | PT × SL exit grid | **BLOCKED** (and empirically refuted) | = mined **V7/V8** (SL 1.0×: −101% ruin; PT65/SL1.5: −89.5%). A 16-cell exit grid on the mined window is jitter; the search already showed exit geometry cannot flip the sign. |
| RM-D2 | Time-stop at N DTE | **BLOCKED** | The mined control (V0) already carried a 5-DTE time stop (`manage_dte: 5`) and lost −77%; sweeping {7,5,3,1} is jitter on an in-family mechanism. "Skip gamma week" was in the tested config all along. |
| RM-D3 | Kelly / breaker sweep | **BLOCKED / moot** | Atlas's own precondition ("only on an already sign-positive cell") never obtains; mined **V3** (real breaker) failed; sizing-as-edge is a named anti-improvement in the program (§5). Correctly self-deprioritized to last — it should simply not run. |
| RM-E1 | QQQ / IWM underliers | **ALREADY-COVERED** (QQQ, in flight) | QQQ verticals = **P1A A3/A4, already run 2026-07-12**: +5.8%/+6.3%, +$268–279/trade, graded *insufficient-sample* due to the QQQ cache collapsing after 2022 (255k→38k bars). The sanctioned path exists: $0 backfill → Maximus-signed addendum → byte-identical re-run. RM-E1 adds nothing to it. IWM: a genuine new underlier, but no IronVault coverage (backfill required) — park behind the QQQ resolution; if pursued, it is a fresh prereg under the checklist, not an EXP-800 sweep. |
| RM-E2 | XSP / SPX | **BLOCKED / park** | Atlas concedes it "improves economics, not edge" and gates it on a positive SPY/QQQ cell that doesn't exist. Also weakly "new": an SPX put vertical is the same structure, same signal, essentially the same premium pool as the closed family — the new-mechanism test is not satisfied by relabeling the index. Multi-day data cost for a non-edge question. |
| RM-F1 | Kill-or-pivot verdict protocol | **ADOPT-AS-PROCESS** (with one correction) | The protocol ideas are good and largely convergent with our preregs; three elements are worth adopting program-wide (below). The **date split must be fixed**: test may never overlap the 2025–2026Q1 single-use holdout (see red flag above). And its pivot branch — keep the plumbing, point it at positive-baseline families — is the profitability program, already approved and running. |

## What should actually be adopted

1. **Program-wide prereg additions (from RM-F1 + RM-B2), effective on the next prereg written:**
   - **Plateau-not-spike rule** for any pre-registered grid ≥ ~10 cells: a passing cell counts only if its adjacent cells are also ≥ 0. (An 80-cell grid produces ~4 false positives at 5%; our current preregs bound variant *count* but don't have an explicit neighborhood test.)
   - **Slippage stress**: a passer must survive an extra −$0.05/spread fill penalty. Cheap, kills fill-model-edge artifacts.
   - **Fill-rate disclosure**: every result reports fills/signals; a "profitable" cell filling a sliver of its signals is flagged as a different, fragile strategy (P1A's XLI void clause was this idea; make it standard).
   - **Fill-model hygiene**: no backtest entry priced off pre-09:35 prints (opening-rotation quotes are ~2.5× marketable per the reparam measurement); P0B's calibration table to include a by-slot breakdown as live confirmation.
2. **Nothing else from the menu becomes a prereg.** The QQQ thread proceeds under the already-recommended P1A addendum (backfill → signed re-run), not under RM-E1. The richness/VRP series gets built inside P2B where it already belongs. IWM is noted as a future new-underlier candidate *only* after QQQ resolves and only with its own data backfill and fresh prereg.

## What the menu gets right (worth saying plainly)

Working independently, Atlas reproduced three program findings: the naive edge was fabricated by fills (~54% fake, disproportionately favorable); concessions monotonically worsen results (structurally thin premium, not a limit-price tuning problem); and the honest end-state is kill-or-pivot with the plumbing preserved. Its 15–20% self-assessed odds and "effectively a different strategy" conclusion are more honest than most of this program's pre-July history. The failure is jurisdictional, not analytical: the menu was written without the governance decision in view, and 8 of its 14 items re-litigate a family that a signed decision closed after those exact mechanisms failed a pre-registered test.

## Recommendation to Maximus

- Do not schedule any RM sweep. Reply to Atlas with the governance decision, `EXPECTANCY_SEARCH_RESULTS.md`, and this evaluation; invite Atlas to contribute inside the program (P2B richness measure and the P1D/P0B execution-layer work are the natural fits for the menu's best ideas).
- Adopt item 1 above into the prereg checklist as a standing amendment (one paragraph in the governance doc's binding checklist; needs your sign-off).
- Re-affirm the holdout boundary in writing wherever RM-F1 circulates: **no test window may touch 2025+ data; the holdout is single-use and Carlos signs its spend.**
- Standing items remain: EXP-800 Tradier halt-and-drain; the menu's own §4 note ("live halt already recommended in reparam §4") independently concurs.
