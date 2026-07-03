# EXP-800 Honest Breaker Backtest (Fix B — backtest-only)

**Date:** 2026-07-03
**Directive:** Carlos — do NOT touch live code; make the backtest honestly model
what the deployed breaker actually does (halt new entries at -12% DD, never
flatten), then report truthful MaxDD/Sharpe/CAGR vs the old flatten-assumption
numbers.

**Live code touched: none.** (An earlier Fix-A flatten implementation in the
live scanner was fully reverted before this work; `git diff` on
`scripts/`, `execution/`, `strategy/` is empty.)

## Background

The EXP-800 backtest twin (`experiments/EXP-800-BT-safe-kelly/run.py`) has a
`flatten` variant — tier 3 (DD ≤ -12% off the rolling HWM) closes all open
positions — which is what `configs/paper_exp800.yaml` documents and what the
strategy's risk profile was assumed to be. The deployed scanner
(`scripts/exp800_safe_kelly_scanner.py`) has **no flatten code**: tier 3 only
blocks *new* entries while open positions keep bleeding mark-to-market. June
2026 paper drawdown reached ~-31% against an assumed ~-12% breaker cap.

The twin's existing `haltonly` variant was also not an honest model of today's
live path: it reproduced the *pre-fix* deployed state machine with the
unconditional `cb_tier >= 3` entry block (the tier-3 deadlock — 1,536 of 1,571
trading days blocked, only 25 trades ever). The deadlock fix that is live today
(`_tier3_entry_blocked` / `_kelly_fraction`, regression-tested in
`tests/test_exp800_tier3_deadlock.py`) makes the halt finite and self-clearing.

## What the deployed breaker actually does (modeled semantics)

Off the rolling high-water mark (never reset), evaluated once per scan day:

| Condition | Action |
|---|---|
| DD ≤ -8% (tier 1) | 0.5× Kelly fraction |
| DD ≤ -10% (tier 2) | floor sizing (2%) |
| DD ≤ -12% (tier 3) | **halt new entries only** for 30 scan slots (one consumed per blocked day); open positions stay on and bleed/recover MTM |
| Halt exhausted, DD still ≤ -12% | entries resume at the 2% floor (post-deadlock-fix behavior) |
| DD recovers above -7% (from tier ≥ 2) | tier resets to 0, full Kelly restored |

No flatten exists anywhere in the live path.

## Change made (backtest only)

`experiments/EXP-800-BT-safe-kelly/run.py` — the tier-3 sizing branch in
`SafeKellyOverlay._wrapped_manage` previously gave the finite-halt/floor-resume
behavior only to the `flatten` variant; `haltonly` kept the pre-fix
unconditional block. The `flatten_enabled` condition was removed from the
post-halt floor-resume branch so `haltonly` now models the *current* deployed
scanner. Variant docstring updated.

Verification:
- `flatten` variant re-run after the edit is **bit-identical** to the prior run
  (metrics, full equity curve, and breaker events all compare equal) — the edit
  changes only `haltonly`.
- The pre-fix deadlock run is preserved at
  `experiments/EXP-800-BT-safe-kelly/results/SPY_haltonly_prefix_deadlock.json`.
- `tests/test_exp800_tier3_deadlock.py` (6 tests) still passes; no test imports
  the experiment script.

## Results — SPY, 2020-01-02 → 2026-04-02, $100k start

Config: `configs/backtest_exp800.json` (Kelly 9/7/4, tiers -8/-10/-12,
floor 2%, halt 30, recovery -7%; real offline Polygon marks, Rule Zero — no
synthetic data).

| Metric | **flatten** (old assumption) | **haltonly** (honest, deployed behavior) | Δ honest vs assumed | haltonly pre-fix deadlock (reference) | notiers (reference) |
|---|---|---|---|---|---|
| CAGR | -9.19% | **-10.28%** | -1.09pp | -3.54% | -37.83% |
| Total return | -45.23% | **-49.23%** | -4.00pp | -20.17% | -94.87% |
| Max drawdown | -45.81% | **-49.69%** | -3.88pp worse | -21.01% | -94.84% |
| Sharpe | -0.96 | **-0.84** | +0.12 | -0.45 | -0.69 |
| Win rate | 66.91% | 70.27% | | 60.0% | 70.16% |
| Trades | 828 | 1,231 | | 25 | 1,240 |
| Ending capital | $54,765 | **$50,768** | -$3,997 | $79,828 | $5,131 |
| Tier-3 fires / flattens | 1 / 19 | 1 / 0 | | 1 / 0 | 0 / 0 |
| Blocked days | 580 | 30 | | 1,536 | 0 |

Honest per-year returns (haltonly): 2020 -26.66%, 2021 -0.13%, 2022 -7.31%,
2023 +2.53%, 2024 -11.70%, 2025 -10.68%, 2026 (to Apr 2) -7.36%.
Q1-2026 monthly: Jan -0.43%, Feb -0.28%, Mar -6.39%.

## Findings

1. **The -12% "cap" does not exist in the deployed system.** With the honest
   entry-halt-only breaker, the single tier-3 breach (2020-02-24, DD already
   -21.0% on the breach *day* — a gap straight through all three tiers) runs to
   a **-49.69% max drawdown**. Open positions bleed straight through the
   threshold; the halt only stops adding new ones. This is consistent with the
   June 2026 live paper experience (-31% with the breaker "active").
2. **The flatten assumption was itself no -12% cap either.** Even the
   documented flatten variant shows -45.81% MaxDD over this window: each
   flatten *realizes* the loss near the low, the HWM never resets, and
   floor-sized re-entries grind further (19 flattens). The "backtest cap
   ~-12%" figure did not survive this twin's window/marks in either variant.
3. **Honest vs assumed delta:** MaxDD -49.69% vs -45.81% (3.9pp worse), CAGR
   -10.28% vs -9.19%, ending capital $50.8k vs $54.8k. Sharpe is nominally
   *less bad* for haltonly (-0.84 vs -0.96) because unflattened positions
   sometimes recover MTM — but the tail (MaxDD) is strictly worse, which is
   what a circuit breaker exists to control.
4. **The pre-fix deadlock numbers (-21% MaxDD, 25 trades) were an artifact**,
   not risk control: the strategy simply stopped trading forever in Feb 2020.
   Any apparent safety in that old haltonly run is the deadlock, not the
   breaker.

## Caveats

- Window ends 2026-04-02 (extent of offline marks); June 2026 live bleed is
  not inside the backtest window.
- The EXP-3570 live-months replay has already flagged fidelity gaps between
  this twin and the live account (backtest -8.3% vs live +39.5% over the
  replayed months). Absolute levels here carry that caveat; the *relative*
  flatten-vs-haltonly comparison shares marks, signals, and sizing, so the
  breaker-semantics delta itself is apples-to-apples.
- `haltonly` halt slots decrement one per blocked trading day (live decrements
  one per scan invocation; EXP-800 scans once per day, SPY only — equivalent).

## Files changed

- `experiments/EXP-800-BT-safe-kelly/run.py` — tier-3 branch: finite-halt /
  floor-resume now applies to `haltonly` (matches deployed scanner);
  docstring updated. **Only file with code changes.**
- `reports/EXP800_breaker_honest_backtest.md` — this report.
- Results (gitignored, on disk):
  `experiments/EXP-800-BT-safe-kelly/results/SPY_haltonly.json` (honest re-run),
  `SPY_haltonly_prefix_deadlock.json` (preserved pre-fix reference),
  `SPY_flatten.json` (re-run, bit-identical to prior).

## Reproduce

```bash
.venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py haltonly   # honest deployed behavior
.venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py flatten    # documented/assumed behavior
```
