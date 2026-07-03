# EXP-3510 — VIX/Indices Backfill + Regime-Fidelity A/B on the Canonical V8A Replay

**Date:** 2026-07-03 · **Owner:** charles · **Status:** COMPLETE
**Lineage:** P0 prerequisite from `research/NEXT_BACKTESTS.md`. Baseline methodology = EXP-3310 (`reports/EXP-3310_collision_guard_rebacktest.md`).
**Rule Zero:** real vendor data only. Backfill = Yahoo Finance daily bars (the same source and schema as `scripts/bootstrap_indices_history.py`, which populated the pre-2023 slab). No interpolation, no synthetic values.

---

## TL;DR

1. **The canonical V8A replay had NO real VIX at all — 1508 of 1508 trading days ran on the `vix=20 / iv_rank=25` default.** EXP-3310's caveat §5 ("~2023-2025 fall back to defaults") **understated** the problem: with no Polygon indices key, the hybrid loader raises *before returning the pre-2023 SQLite slice*, so `_build_iv_rank_series` swallowed the exception and discarded 2020-2022 too (`backtest/market_history.py:_load_indices_hybrid` + `backtest/backtester.py:1220`).
2. After backfilling real VIX/VIX3M/SPX (2023-02-14 → 2026-07-01, 848/844/847 rows) and serving indices entirely from SQLite, **fallback days = 0/1508** and the replay sees the real VIX range **11.9 – 82.7**.
3. **With real VIX the honest V8A replay gets WORSE, not better:** +4.94% → **−8.91%** total (6 years), Sharpe 0.12 → **−0.06**, MaxDD −24.16% → **−31.78%**. The real-data, real-VIX V8A is break-even-to-negative with a −32% drawdown — fully consistent with the live-paper record (Sharpe −1.20, DD −21.9%) and nothing like the compass-cube Sharpe 6.16.
4. **Bonus (June 2026 finally quantified):** the backfill shows the "June crash" had **VIX max 22.22** (2026-06-10) and SPX max drawdown **−4.13%** (May-29 → Jun-10, first leg on Jun-5 = NFP day). There was **no vol spike**. VIX-threshold protections (entry-block 35, exit-all 45) could never have fired; the −21.9%/−31.1% paper DDs came from leverage on a routine dip.

## What was run

| Item | Value |
|---|---|
| Step 1 | `backfill_indices_2023plus.py` — Yahoo `^VIX`/`^VIX3M`/`^GSPC` → `data/historical_indices.sqlite` (backup: `data/historical_indices.sqlite.bak-exp3510`); `INSERT OR IGNORE`, idempotent |
| Step 2 | `run_replay.py {fallback,realvix}` — byte-identical to `scripts/exp3310_collision_rebacktest.py` (config `configs/paper_expv8a.yaml`, SPY 2020-01-02→2025-12-31, offline `data/options_cache.db`, leg-collision guard ON) plus VIX-fidelity instrumentation |
| Arm difference | `realvix` monkeypatches `backtest.market_history._POLYGON_INDICES_START → 2027-01-01` so indices are served entirely from the backfilled SQLite (no index network calls). `fallback` = HEAD behavior unchanged |
| Determinism check | `fallback` reproduces EXP-3310 NEW exactly: 1167 trades, +4.94%, Sharpe 0.12, MaxDD −24.16% |

## Results — fallback (vix=20 everywhere) vs realvix

| Metric | fallback (≡ EXP-3310 NEW) | realvix | Δ |
|---|---:|---:|---:|
| Fallback days (of 1508) | **1508** | **0** | −1508 |
| VIX seen (min/mean/max) | 20.0 / 20.0 / 20.0 | 11.9 / 21.0 / 82.7 | real series |
| Total trades | 1,167 | 1,198 | +31 |
| Total return (6yr) | **+4.94%** | **−8.91%** | **−13.85 pp** |
| Sharpe | 0.12 | −0.06 | −0.18 |
| Max drawdown | −24.16% | **−31.78%** | −7.62 pp deeper |
| Win rate | 71.6% | 70.1% | −1.5 pp |
| Ending capital | $104,943 | $91,089 | −$13,854 |
| Bull put / bear call / IC | 509 / 0 / 658 | 455 / 53 / 690 | bear-calls appear |
| Regime days bull/neutral/bear | 733 / 803 / 0 | 951 / 501 / 84 | bear regime appears |
| VIX3M series (vix_structure signal) | 0 dates (abstained) | 1,656 dates (active) | — |
| IV-rank series (sizing) | 0 dates (flat 25) | 1,656 dates (real 0–100) | — |

**Why worse with real VIX:** real IV-rank sizing scales positions UP in high-vol regimes (iv_rank 25-default had kept sizing at the small 2%-base tier all along), the vix_structure signal now flips regimes (84 bear days → 53 bear-call trades, several of which lose in whipsaws), and `vix_max_entry: 40` blocks only the extreme days. The fallback run was accidentally *conservative*. Either way, both arms are catastrophically far from the compass-cube claim (net Sharpe 6.16, DD 7.1%).

## Implications

- **Every VIX-conditioned backtest run through `backtest/backtester.py` in this environment before today was invalid** — not "degraded after 2023" but VIX-blind for the full window. Any historical result that claimed a VIX gate/ladder helped or hurt must be re-run (this includes the EXP-3310 A/B itself, though its *delta* conclusion — the guard removes fictitious trades — still holds since both its arms were equally VIX-blind).
- **The corrected canonical baseline for V8A is: −8.9% / Sharpe −0.06 / MaxDD −31.8% (2020-2025, real Polygon marks, real VIX).** This becomes the reference for EXP-3520/3540/3550.
- **June 2026 was not a tail event.** Max VIX 22.2, max SPX drawdown −4.1%. Strategy robustness work should target "routine 4% dip under leverage", not "VIX-80 crash protection". Equity-drawdown-triggered de-risking (EXP-800-style tiers, EXP-3560 arm B) is the mechanism class that can fire in such regimes; VIX-threshold exits (35/45) cannot.

## Pass/fail vs pre-registered gate

- PASS: fallback-day count = **0** for the corrected run (gate was <1% of days); delta table published (above).
- Residual degradation: none found — VIX3M also fully covered (1,656 dates). June-2026 VIX/SPX now offline through 2026-07-01 for future replays (EXP-3570 options-bars backfill still outstanding).

## Artifacts

- `results/backfill_report.json` — rows fetched/inserted per index, table ranges
- `results/replay_fallback.json`, `results/replay_realvix.json` — metrics + full trade logs + VIX-fidelity blocks
- `results/run_fallback.log`, `results/run_realvix.log` — run logs
- DB backup: `data/historical_indices.sqlite.bak-exp3510`

**Reproduce:**
```bash
.venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/backfill_indices_2023plus.py   # idempotent
.venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/run_replay.py fallback
.venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/run_replay.py realvix
```
