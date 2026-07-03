# EXP-3570 — Live-Months Replay: Apr–Jun 2026 Backfill + EXP-800/V8A Twin

**Date:** 2026-07-03 · **Status:** completed
**Question:** does the real-mark backtest reproduce the EXP-800 live paper months (Apr +21.2 %, May +3.4 %, Jun +11.3 %)?

## PASS/FAIL

**FAIL — the production-engine twin of the deployed EXP-800 scanner does NOT reproduce the live paper track: backtest −8.3 % over 2026-04-01→2026-07-03 vs live +39.5 % compounded. The live quarter's returns are not explained by the strategy rules as implemented in the engine twin, now with fully real marks.**

## Step 1 — Backfill (Polygon, Rule Zero)

- DB backed up to `data/options_cache.db.bak-exp3570` before any write.
- Probe cross-check: existing DB marks vs live Polygon aggs — exact match (e.g. `O:SPY260327C00633000` 2026-03-25/26/27 closes 24.5 / 16.22 / 0.84 identical).
- Listed 4,710 Jul/Aug-2026 SPY contracts via `v3/reference/options/contracts` (expiries ≤ 2026-08-21, needed for 15–25 DTE EXP-800 and 25–50 DTE V8A June entries); 4,488 in the strike band 500–950 inserted as new `option_contracts` rows (`as_of_date` 2026-07-03).
- Fetched daily aggs for 10,964 contracts (expiries 2026-04-03…2026-08-21, band-filtered) over 2026-04-01→2026-07-02 at ~4.5 req/s with 429/Retry-After handling: **118,411 new `option_daily` rows** (`INSERT OR IGNORE`, `open_interest` NULL per standard-tier convention).
- Integrity: row deltas exactly +118,411 bars / +4,488 contracts vs backup; 500-random-row spot-check of pre-existing rows — all byte-identical; 21 June trading days covered, 1.4–2.6 k bars/day in-window. 2026-07-03 is the observed July-4th NYSE holiday — last trading day is 2026-07-02.
- Indices: `historical_indices.sqlite` extended 2026-07-01 → 2026-07-02 via the EXP-3510 Yahoo method (backup `historical_indices.sqlite.bak-exp3570`; a Yahoo-published ^VIX 2026-07-03 print also landed — harmless, past the last equity trading day).

## Step 2 — EXP-800 live-months twin (EXP-800-BT harness, fixed prod engine)

Window 2026-04-01→2026-07-03, fresh $100k and fresh HWM (mirrors the live paper account restart at end-March), `configs/backtest_exp800.json` semantics unchanged (G21-parity config), real VIX via the post-8f1bc8c production path, offline real marks.

| Month | live paper | haltonly (as-deployed twin) | flatten | notiers (no breakers) |
|---|---|---|---|---|
| 2026-04 | **+21.2 %** | **−10.26 %** | −10.26 % | −3.42 % |
| 2026-05 | **+3.4 %** | +0.29 % | +0.29 % | +3.96 % |
| 2026-06 | **+11.3 %** | +0.49 % | +0.49 % | +3.54 % |
| Jul 1–2 | — | −0.06 % | −0.06 % | −0.14 % |
| **Window total** | **≈ +39.5 %** | **−8.30 %** | −8.30 % | +7.32 % |

haltonly detail: 34 trades, win rate 82.4 %, Sharpe −3.08, MaxDD −11.59 %; tier fires 1×T1 / 3×T2 / 0×T3 (flatten ≡ haltonly — tier 3 never reached); exits: 25 profit_target, 3 stop_loss, 1 expiration_loss, 2 expiration_no_data, 3 expiration_profit.

**Where the divergence comes from (trade-level):** the engine's combo regime read early April as neutral/bear — it opened 1 bear-call (2026-04-01, stopped out −$2.2k) and 3 iron condors (Apr 2/6/7, −$4.7k/−$4.3k/−$3.5k) that the April rally blew through, a ~−10 % April; the tier-1/2 breakers then floored sizing (2 % floor) so May/June recovery was ~flat. The live scanner in the same month was +21.2 % — on the same underlying move, the live regime/direction calls (live compass state) and scanner-side sizing must have been long-biased and full-size. Known fidelity gaps documented in `configs/backtest_exp800.json` and the EXP-800-BT report (live Friday-only expiry selection vs engine nearest-weekday; live IC one-wing sizing quirk ~2× oversize — which would have made live *worse*, not better) cannot bridge a +31 pp month. Live trade-level diffing is impossible locally (paper DBs live on Railway), so this comparison is month-return-level by necessity.
**Consistent with EXP-800-BT:** the 2020→2026-04 twin was already deeply negative in all variants; this experiment adds that even the celebrated live quarter, replayed on its own real marks with a fresh HWM, is negative through the engine twin. The live paper track (+21/+3/+11) reads as live-state regime luck (and scanner-vs-engine behavioral differences), not as reproducible strategy edge.

## Step 3 — V8A June counterfactual

Canonical V8A (`configs/paper_expv8a.yaml`, SPY, leg-collision guard ON, engine caps configured risk 33.1 %→25 %) on 2026-06-01→2026-07-03, fresh $100k: **+1.61 %, MaxDD −0.16 %**, 7 trades (4 profit_target, 3 expiration_no_data — positions expiring past 2026-07-02 carry last marks). June 2026 on real marks was benign for the canonical SPY config — VIX stayed 16–22, and the NFP-day dip (2026-06-05, SPX −4.1 % leg) did not breach the 0.20Δ put strikes. The live V8A June disaster (−31 % DD) was a 4-stream, ~21.5 % max-loss/NAV-per-stream book across SPY/XLF/XLI/XLE — the SPY-only canonical replay cannot reproduce the book, but it confirms the *instrument and month* were survivable at engine sizing conventions: the damage was sizing/aggregation, consistent with EXP-3510/3520/3540.

## Caveats

- Month-return-level comparison only (live trade logs are on Railway, not in the checkout).
- `expiration_no_data` exits (2 EXP-800, 3 V8A) use carried marks — deep-ITM daily bars are sparse on trade-based aggs; same convention as the full-history backtests.
- Jul/Aug-2026 contract listing is as-of 2026-07-03 (active contracts); strikes outside 500–950 were not backfilled (irrelevant to 2 % OTM / 0.20Δ entries at SPY 655–760).

## Files

- `backfill_option_marks.py` / `results/backfill_done.txt` — backfill runner + resume journal
- `run_livewindow.py` / `backtest_exp800_livewindow.json` — EXP-800-BT harness driver on the live window
- `run_v8a_june.py` — V8A June counterfactual
- `results/SPY_{haltonly,flatten,notiers}.json`, `results/v8a_june.json` — full metrics, trades, equity curves

## Conclusion

The clean test fails: with real Apr–Jun 2026 marks in place, the engine twin of the deployed EXP-800 loses 8.3 % over the exact window where the live paper account reported +39.5 %. Confidence in the live paper track as evidence of edge should be LOW; the EXP-800-BT recommendation (do not scale EXP-800 on the strength of Apr–Jun live paper) is strongly reinforced. The V8A June counterfactual independently confirms June 2026 was survivable at canonical sizing — the live losses were a sizing/aggregation artifact, not an unavoidable market event.
