# EXP-P1A ADDENDUM RESULTS — A3 and A4 PASS on the completed dataset

**Date:** 2026-07-12 · **Author:** cc1
**Prereg chain:** parent `EXP-P1A_PREREG.md` @ `c2356b7` → addendum `EXP-P1A_ADDENDUM_PREREG.md` @ `fa30012` (both committed before their runs; unchanged since). Runner byte-identical (`p1a.py A3|A4`), same window (2020-01-02 → 2024-12-31), marketable fills only, same gates.

## Backfill audit (data repair that occasioned the re-run)

- Protocol: backup `options_cache.db.bak-p1a` → probe cross-check **3/3 exact matches** vs live Polygon before first write → puts-only listing in per-year bands (63,943 contracts) → `INSERT OR IGNORE` aggs → integrity checks.
- **Gap closed:** QQQ bars 2023: 61,446 → **398,635**; 2024: 38,471 → **362,121** — now consistent with 2020–22 density (195–255k/yr).
- **Pre-existing data untouched:** 500/500 randomly spot-checked pre-existing rows byte-identical to the backup.
- Deltas: `option_daily` +1,697,883 rows, `option_contracts` +165,236. Attribution: ~682k bars from this QQQ repair (two legs: 94,938 throttled + 587,243 full-rate); ~834k SLV bars are the sibling session's concurrent PROG0 backfill (`SLV` now 833,522 bars); remainder = SLV/QQQ contract listing rows. Nothing past 2024-12-31 was fetched; the holdout is untouched.
- Ops note for the record: two restarts occurred (lock collision with the sibling writer → busy-timeout added; then a rate restore + puts-only re-scope). All writes were `INSERT OR IGNORE`; the resume journal prevented duplicate fetching.

## Results (completed data) vs the partial-data run

| Gate (prereg) | A3 — QQQ vert 2 %-OTM | A4 — QQQ vert 5 %-OTM |
|---|---|---|
| Total return > 0 | **+6.64 %** ✓ (was +5.77 partial) | **+10.07 %** ✓ (was +6.28) |
| Expectancy > $0 net | **+$131.54/trade** ✓ (was +$268 on 22 trades) | **+$195.42/trade** ✓ (was +$279 on 23) |
| MaxDD ≥ −20 % | −7.8 % ✓ | −3.05 % ✓ |
| Worst year ≥ −10 % | −3.55 (2022) ✓ | −1.89 (2021) ✓ |
| ≥ 40 trades | **53** ✓ | **53** ✓ |
| Fallbacks ≤ 20 % | 0 ✓ | 0 ✓ |
| **Verdict** | **PASS** | **PASS** |

Per-year (A3): 2020 +4.65 · 2021 +2.56 · 2022 −3.55 · 2023 +1.98 · 2024 +1.01
Per-year (A4): 2020 +5.49 · 2021 −1.89 · 2022 **+1.80** · 2023 +2.79 · 2024 +1.64 — positive in the bear year.

**The unseen data confirmed rather than refuted.** The 2023–24 additions (invisible when A3/A4 were selected for re-run) contributed +1.0 to +2.8 %/yr each year. Per-trade expectancy compressed (as it should when chop years enter the sample) but stayed decisively positive. Win rates 84.9 %/90.6 %; floor never bound; every entry tested against real bar data (`naive_fallbacks` = 0).

## What this is — and is not

These are the **first strategies in the program's history to pass a pre-registered honest-fills gate.** The profile is exactly what the program was hunting: modest, survivable premium harvest — ≈ +1.3–2.0 %/yr at the deliberately conservative test sizing (5 %/trade, ≤ 3 positions), worst year −3.6 %/−1.9 %, MaxDD under 8 %. A4 (further OTM, richer-than-friction credits only by construction of the ledger classes) dominates A3 on every risk metric.

It is **not** a launch authorization, and the honest caveat list is short but real: (1) 53 trades is still a modest sample; (2) daily-bar day-limit fill semantics — P0B live probes must calibrate before any live claim; (3) the addendum's disclosed selection risk (A3/A4 were re-run because they looked good on partial data) is mitigated, not eliminated, by the fact that only unseen data was added under unchanged criteria; (4) 2020–2024 is in-sample dev by classification, though QQQ was never touched by the mined SPY search and A3/A4's configs were pre-registered before any QQQ run existed.

## Next gates (per governance — nothing below happens without the named sign-off)

1. **Holdout candidacy:** A3/A4 are now the program's first entries on the holdout-candidate list. The 2025–2026Q1 holdout is single-use and spent only on **Carlos's signed decision** — recommendation: spend it on A4 (dominant variant), with A3 read-only alongside if the ruling permits one spend covering both pre-registered siblings.
2. **P0B fill probes** (already approved in principle): run before or alongside any holdout spend — QQQ 1-lot probes should be added to the probe schedule to calibrate exactly this fill model.
3. If holdout passes: G2 forward-paper fidelity (fresh account, ≥ 2 NFP prints), G3 breaker drill, G4 micro-live — the original pipeline, unchanged.

## Machine-readable results

```json
{"experiment": "EXP-P1A-addendum", "prereg_chain": ["c2356b7", "fa30012"], "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable",
 "backfill_audit": {"probe_matches": "3/3", "qqq_bars_2023": [61446, 398635], "qqq_bars_2024": [38471, 362121], "spot_check_prior_rows": "500/500 identical", "option_daily_delta": 1697883, "qqq_backfill_bars": 682181, "sibling_slv_bars": 833522, "holdout_touched": false},
 "passers": ["A3", "A4"],
 "rows": [
  {"v": "A3", "und": "QQQ", "class": "vert_wide_2pctOTM_30dte", "trades": 53, "total": 6.64, "exp": 131.54, "wr": 84.91, "max_dd": -7.8, "worst_year": -3.55, "per_year": {"2020": 4.65, "2021": 2.56, "2022": -3.55, "2023": 1.98, "2024": 1.01}, "verdict": "PASS"},
  {"v": "A4", "und": "QQQ", "class": "vert_wide_5pctOTM_30dte", "trades": 53, "total": 10.07, "exp": 195.42, "wr": 90.57, "max_dd": -3.05, "worst_year": -1.89, "per_year": {"2020": 5.49, "2021": -1.89, "2022": 1.8, "2023": 2.79, "2024": 1.64}, "verdict": "PASS"}
 ],
 "recommendation": "A4 primary holdout candidate (A3 sibling); P0B QQQ probes before/alongside; holdout spend requires Carlos signature"}
```
