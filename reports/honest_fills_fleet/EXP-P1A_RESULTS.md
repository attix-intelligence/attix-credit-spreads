# EXP-P1A RESULTS — zero passers under the prereg; QQQ verticals inconclusive-positive, blocked by a data gap

**Date:** 2026-07-12 · **Author:** cc1 · **Prereg:** `EXP-P1A_PREREG.md` @ `c2356b7` (signed off and committed before any run; unchanged since)
**Runner:** `experiments/honest-fills-fleet/p1a.py A1..A6` · marketable fills · 2020-01-02 → 2024-12-31 only · raw: `results/p1a_A*.json` (local, gitignored)

## Verdict (per the pre-registered criteria — no re-scoring, no exceptions)

**No variant passes.** But the six results split into three distinct findings, and flattening them into one "fail" would be less than honest:

1. **XLI is closed on the merits.** A1 (vertical): −13.1 %, negative in 4 of 5 years, and the credit floor + honest fills let only **20 entries through in 260 weeks** — triggering the pre-registered void clause (floor unfillable > 80 % of weeks; 858 floor rejects). A2 (iron condor): −14.8 %, **12.5 % win rate on 8 trades**, same void clause (468 floor rejects). The ledger's 46 %/27.5 % min-edge warnings were prophetic: XLI premium is too thin to clear our friction, and what's left after the floor doesn't fill. No parameter escalation, per prereg.
2. **QQQ verticals are positive on every gate except sample size — and the sample shortfall is a *data* artifact.** A3 (2 %-OTM): +5.77 %, expectancy **+$268/trade**, 86.4 % win rate, MaxDD −6.3 %, worst year −3.6 %. A4 (5 %-OTM): +6.28 %, **+$279/trade**, MaxDD −3.1 %, worst year −1.9 %. Both fail only the ≥ 40-trade gate (22/23 trades) — and diagnosis shows why: **the cache's QQQ option coverage collapses after 2022** (255k bars in 2021 → 61k in 2023 → 38k in 2024); entries stop 2023-02 with 2,418 marketable attempts unfilled against missing/illiquid marks. This is an `options_cache.db` backfill gap, not a strategy result. Per the prereg's own language these are graded **"insufficient sample — not a pass"**, explicitly distinct from "fail on merits."
3. **Two harness/attribution notes, disclosed:** A5 (QQQ IC) produced only 3 trades partly because the engine's iron-condor finder retains internal RSI/IV-rank entry conditions that the harness did not neutralize — **A5 is graded VOID (harness fidelity), not a strategy verdict.** A6 ran byte-identical to A3: the credit floor never binds on QQQ (credits sit far above $35.20) — clean attribution: the floor's only effect in this experiment was on XLI, where it correctly starved un-viable entries.

## Results table

| # | Variant | Trades | Total | Exp/trade | WR | MaxDD | Worst yr | Fallbacks | Grade |
|---|---|---|---|---|---|---|---|---|---|
| A1 | XLI vert 2 %-OTM | 20 | −13.1 % | −$86 | 60.0 % | −14.2 % | −5.9 | 0 | **FAIL + VOID** (floor unfillable) |
| A2 | XLI IC | 8 | −14.8 % | −$587 | 12.5 % | −15.1 % | −6.6 | 0 | **FAIL + VOID** (floor unfillable) |
| A3 | QQQ vert 2 %-OTM | 22 | **+5.8 %** | **+$268** | 86.4 % | −6.3 % | −3.6 | 0 | **INSUFFICIENT SAMPLE** (data gap) |
| A4 | QQQ vert 5 %-OTM | 23 | **+6.3 %** | **+$279** | 87.0 % | −3.1 % | −1.9 | 0 | **INSUFFICIENT SAMPLE** (data gap) |
| A5 | QQQ IC | 3 | +0.1 % | +$42 | 33.3 % | −1.0 % | −0.3 | 0 | **VOID** (harness: engine IC gates not neutralized) |
| A6 | A3 sans floor | 22 | +5.8 % | +$268 | 86.4 % | −6.3 % | −3.6 | 0 | = A3 (floor no-op on QQQ) |

Entries by year (A3): 2020×7, 2021×8, 2022×6, 2023×1, 2024×0 — the 2023–24 zero is the cache gap, coincident with QQQ bar counts dropping ~80 %.

## What happens next (recommendation — requires Maximus sign-off, nothing runs without it)

1. **Backfill QQQ options 2023-01 → 2024-12** with the existing Polygon key ($0, EXP-3570 backfill protocol: DB backup, probe cross-check, integrity counts). Optionally XLI 2024 too (42.5 % of its 2024 bars are single-print — though XLI is closed on merits regardless).
2. **Prereg addendum, not a silent re-run:** re-execute A3/A4 only, byte-identical config and criteria, on the completed 2020–2024 window — signed by Maximus *before* the re-run, explicitly disclosed as a second look at in-sample dev data occasioned by a data repair (the window is already classified in-sample; the single-use holdout is untouched and stays untouched).
3. If the completed-data re-run clears all gates including ≥ 40 trades, A3/A4 enter the holdout-candidate list (Carlos signs any holdout spend). If it degrades the result, that is the answer and QQQ verticals close with everything else.

## Caveats

- Daily-bars fill realism: `naive_fallbacks` = 0 across all runs (every entry was tested against real bar data), but QQQ/XLI marketable fills on daily bars are day-limit approximations; P0B live probes remain the calibration path before any live claim.
- The positive QQQ numbers are 2020–2022-weighted (the data-dense years). A window that under-represents 2023–24 chop is not a complete picture — one more reason the backfill re-run is required rather than optional.
- 22-trade samples cannot distinguish +$268/trade of edge from luck; nothing in this report is evidence of deployable edge. It is evidence the idea *survived its first honest test* and deserves its completed dataset.

## Machine-readable results

```json
{"experiment": "EXP-P1A", "prereg_commit": "c2356b7", "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable",
 "passers": [],
 "grades": {"A1": "fail_void_floor_unfillable", "A2": "fail_void_floor_unfillable", "A3": "insufficient_sample_data_gap", "A4": "insufficient_sample_data_gap", "A5": "void_harness_ic_gates", "A6": "duplicate_of_A3_floor_noop"},
 "rows": [
  {"v": "A1", "und": "XLI", "trades": 20, "total": -13.14, "exp": -86.16, "wr": 60.0, "max_dd": -14.23, "worst_year": -5.94, "floor_rejects": 858},
  {"v": "A2", "und": "XLI", "trades": 8, "total": -14.83, "exp": -586.98, "wr": 12.5, "max_dd": -15.13, "worst_year": -6.55, "floor_rejects": 468},
  {"v": "A3", "und": "QQQ", "trades": 22, "total": 5.77, "exp": 268.48, "wr": 86.36, "max_dd": -6.27, "worst_year": -3.55, "entries_by_year": {"2020": 7, "2021": 8, "2022": 6, "2023": 1, "2024": 0}},
  {"v": "A4", "und": "QQQ", "trades": 23, "total": 6.28, "exp": 278.65, "wr": 86.96, "max_dd": -3.05, "worst_year": -1.89},
  {"v": "A5", "und": "QQQ", "trades": 3, "total": 0.11, "exp": 41.69, "wr": 33.33, "max_dd": -0.96, "worst_year": -0.33},
  {"v": "A6", "und": "QQQ", "trades": 22, "total": 5.77, "exp": 268.48, "wr": 86.36, "max_dd": -6.27, "worst_year": -3.55}
 ],
 "data_gap": {"qqq_bars_by_year": {"2020": 200753, "2021": 255020, "2022": 194592, "2023": 61446, "2024": 38471}, "xli_2024_flat_bar_pct": 42.5},
 "recommendation": "backfill QQQ 2023-2024 ($0, existing key) -> Maximus-signed addendum -> byte-identical A3/A4 re-run; holdout untouched"}
```
