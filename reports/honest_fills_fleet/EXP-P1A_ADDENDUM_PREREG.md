# EXP-P1A ADDENDUM PRE-REGISTRATION — A3/A4 re-run on completed QQQ data

**Date:** 2026-07-12 · **Author:** cc1 · **Sign-off:** APPROVED — Maximus, 2026-07-12 ("run the QQQ backfill and the A3/A4 addendum re-run"). Committed BEFORE the backfill completes and BEFORE any re-run.
**Parent prereg:** `EXP-P1A_PREREG.md` @ `c2356b7` · **Occasion:** `EXP-P1A_RESULTS.md` @ `7cd8d83` — A3/A4 graded *insufficient sample* due to a cache data gap (QQQ option bars collapse from 255k/yr to 38k/yr after 2022; entries stop 2023-02).

## What this addendum authorizes — and nothing else

1. **Data repair:** backfill QQQ option daily bars 2023-01-01 → 2024-12-31 from Polygon (existing key, $0), per the EXP-3570 protocol: DB backup → probe cross-check (existing rows must match live Polygon byte-for-byte) → contract listing (expired included) in a per-year strike band → `INSERT OR IGNORE` aggs (existing rows never modified) → integrity counts + random spot-check of pre-existing rows.
2. **Re-run of A3 and A4 only**, byte-identical to the parent prereg: same runner (`p1a.py`), same config, same window (2020-01-02 → 2024-12-31), same marketable-only fill model, same pass/fail criteria (total > 0 · expectancy > $0 · MaxDD ≥ −20 % · worst year ≥ −10 % · ≥ 40 trades · fallbacks ≤ 20 %). No new variants, no parameter changes, no A1/A2/A5/A6 re-runs.

## Disclosures (why this is legitimate and what it costs us)

- This is a **second look at the same in-sample window** occasioned by a data repair. 2020–2024 is already classified in-sample dev; the single-use 2025+ holdout is not read by the backfill (bars fetched stop at 2024-12-31) or the re-run, and stays unmined.
- Selection risk is bounded but nonzero: A3/A4 were chosen for re-run because they looked good on partial data. The mitigation is that the re-run adds only *unseen* data (2023–24) under unchanged criteria — the new period can only confirm or refute; it cannot be tuned to. A degraded result closes QQQ verticals with everything else, per the parent prereg.
- A re-run pass still authorizes nothing by itself: holdout candidacy requires Carlos's signed spend; live claims require P0B fill calibration; the ≥ 40-trade sample is still small.

## Outcome recording

Results go to `EXP-P1A_ADDENDUM_RESULTS.md` with the standard machine-readable block, including backfill integrity evidence (row deltas, probe matches, spot-check result) so the data repair itself is auditable.
