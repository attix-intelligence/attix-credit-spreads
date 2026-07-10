# EXP-800-BT — Honest Fill Model Re-run (FIX #3, `fill_model=marketable`)

**Date:** 2026-07-10 · **Author:** cc5
**Code:** main @ post-`11f140c` (FIX #3 merge: `backtest.fill_model` flag, honest marketable-limit entry fills)
**Runner:** `experiments/EXP-800-BT-safe-kelly/run.py {variant} {fill_model}` · window SPY 2020-01-02 → 2026-04-02, real marks (`data/options_cache.db`), real VIX/VIX3M (post-8f1bc8c SQLite indices fallback), offline — no broker/live/deploy configs touched.
**Results files:** `experiments/EXP-800-BT-safe-kelly/results/SPY_{variant}.json` (naive) and `SPY_{variant}_marketable.json` (gitignored, as before).

## Fill models

- **naive** (legacy): every accepted signal fills instantly at the scan bar's close spread mark minus slippage.
- **marketable** (FIX #3): entry limit = decision-time open spread mark − slippage; fills only if the market traded at/through the limit by bar close, else fill-or-cancel that bar (per-slot fresh limits = live FIX #2 reprice-ladder analog; pre-9:30 slots place no order).

**Reproduction check:** all three naive re-runs are identical to the recorded Jul-3 baselines (`reports/EXP800_breaker_honest_backtest.md`: haltonly −49.23% / Sharpe −0.84 / MaxDD −49.69%; flatten −45.23%; notiers −94.87%) — FIX #3 did not perturb the legacy path.

## Side-by-side results

### haltonly — tiers ON, breaker as actually deployed (halt-only, finite, post-deadlock-fix)

| Metric | naive | marketable | Δ |
|---|---|---|---|
| Trades | 1,231 | 487 | −60.4% |
| Total return | −49.23% | −32.82% | +16.4pp (smaller loss) |
| CAGR | −10.28% | −6.17% | |
| Win rate | 70.27% | 64.68% | −5.6pp |
| Sharpe | −0.84 | −1.30 | worse |
| Max DD | −49.69% | −32.92% | shallower (fewer positions) |
| Tier fires (1/2/3) | 3/1/1 | 1/4/2 | |

### notiers — tiers OFF (unprotected Kelly 9/7/4 baseline)

| Metric | naive | marketable | Δ |
|---|---|---|---|
| Trades | 1,240 | 498 | −59.8% |
| Total return | −94.87% | −79.87% | +15.0pp (smaller loss) |
| CAGR | −37.83% | −22.63% | |
| Win rate | 70.16% | 64.26% | −5.9pp |
| Sharpe | −0.69 | −1.19 | worse |
| Max DD | −94.84% | −80.27% | |

### flatten — tiers ON, tier-3 flatten as documented (reference variant)

| Metric | naive | marketable | Δ |
|---|---|---|---|
| Trades | 828 | 385 | −53.5% |
| Total return | −45.23% | −27.35% | +17.9pp (smaller loss) |
| Win rate | 66.91% | 63.38% | −3.5pp |
| Sharpe | −0.96 | −1.18 | worse |
| Max DD | −45.81% | −27.46% | |

## Unfillable naive entries

- **Trade-count basis (headline):** 53.5–60.4% of the naive fill stream never happens under honest fills — haltonly 1,231→487 (**60.4% unfillable**), notiers 1,240→498 (**59.8%**), flatten 828→385 (**53.5%**). (Approximate attribution: path dependence via sizing/breaker state slightly reshuffles which signals arise, but the entry signal stream is near-identical day-to-day.)
- **Raw rejected-attempt counters** (per scan-slot fill-or-cancel rejections across all repricing slots, so many rejections can belong to one signal-day): haltonly 76,088; notiers 77,492; flatten 57,914. `fill_model_naive_fallbacks = 0` in all runs — every entry was evaluated against real bar data, none booked via the daily-close fallback.
- Per-year losses shrink roughly proportionally in every year including 2020 and 2022; no year flips positive under either fill model (best: 2023 haltonly naive +2.53%, marketable −0.92%).

## Verdict

Honest fills make EXP-800-BT lose **less in total** (roughly 40% of naive entries simply never fill, so less negative-edge volume gets executed) but confirm the edge itself is **worse per trade**: win rate drops ~6pp and Sharpe deteriorates (−0.84 → −1.30 as-deployed) once entries must actually be marketable. The naive fill model was overstating both fill availability and per-trade quality, but it was not the source of the negative result — EXP-800's champion-signal core loses money under every fill model and every breaker variant on real 2020–2026 marks. This adds a third independent strike against the strategy family currently holding Tradier live authority (after the LUCK ruling and the twin-divergence finding) and further supports halting/replacing the EXP-800 Tradier deployment.
