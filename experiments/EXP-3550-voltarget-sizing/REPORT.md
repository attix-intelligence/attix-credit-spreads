# EXP-3550 — Continuous Vol-Target Sizing

**Date:** 2026-07-03 · **Status:** completed · **Window:** 2020-01-02 → 2026-04-01
**Engine:** real `backtest/backtester.py`, offline `data/options_cache.db` (real Polygon marks), real VIX from the EXP-3510 backfill, Rule Zero, no live/scanner calls.
**Base strategy:** identical to EXP-3540 — live VRP stream params (0.20Δ short put, $5 width, ~30 DTE, bull_put, vix_max_entry 40, hold-to-expiry), compounding sizing off current NAV, max_positions 1 per ticker. No DD tiers, no event gates (EXP-3540 showed gates are a no-op).

## Hypothesis (from EXP-3540)

Continuous vol-targeted per-stream sizing reconciles test MaxDD ≤ 10 % with CAGR ≥ 70 % of the live-like baseline across BOTH regimes, where EXP-3540's discrete DD tiers failed rank stability (train regime rewarded protection, test regime punished it).

**Result: REFUTED.** 0 / 6 configs pass the ship gate, and every vol-target config is dominated by EXP-3540's discrete-tier winner on Calmar in *both* periods.

## Sizing rule

`eff_risk_pct(t) = clamp( 21.5 % × σ_target / σ(t−1), lo, hi )` — per-trade max-loss/NAV at entry.
σ = the engine's causal realized-vol series (20-day ATR / close × √252, previous trading day, clipped [10 %, 100 %]); 21.5 % = live-like base, so a cell sizes exactly like live when σ = σ_target. Implemented through the engine's `_current_seasonal_mult` sizing hook; per-day σ and eff-risk audit trail stored in each result JSON (`sizing_daily`).

Grid: σ_target ∈ {8 %, 12 %, 16 %} × bounds ∈ {`foff` = safety-only [1 %, 43 %], `fon` = [5 %, 21.5 %] never-exceed-live} = 6 configs × SPY/XLF/XLI = 18 cells. Selection/validation protocol identical to EXP-3540: winner on TRAIN 2020-01→2023-12 portfolio Calmar (equal-weight 3-ticker book), TEST 2024-01→2026-04 untouched. Ship gate: test MaxDD ≤ 10 % AND test CAGR ≥ 70 % of live-like baseline (EXP-3540 `s215_doff_eoff`, reused not re-run) AND rank-stable = top-3-of-6 Calmar both periods.

## Results (3-ticker portfolio)

| cell | train CAGR | train MaxDD | train Calmar | test CAGR | test MaxDD | test Calmar | mean eff-risk (SPY) | gate |
|---|---|---|---|---|---|---|---|---|
| **vt08_fon** ← winner | 3.4 % | −7.0 % | 0.49 | 5.3 % | −9.7 % | 0.54 | 9.3 % | D✓ C✗ R✗ |
| vt08_foff | 3.3 % | −7.1 % | 0.46 | 5.3 % | −9.7 % | 0.55 | 9.2 % | D✓ C✗ R✓ |
| vt12_foff | 5.0 % | −10.9 % | 0.45 | 4.9 % | −14.1 % | 0.35 | 13.7 % | ✗ |
| vt12_fon | 4.9 % | −10.8 % | 0.45 | 8.2 % | −13.6 % | 0.60 | 13.7 % | ✗ |
| vt16_foff | 6.6 % | −14.7 % | 0.45 | 8.8 % | −15.3 % | 0.57 | 18.1 % | ✗ |
| vt16_fon | 6.4 % | −14.2 % | 0.45 | 8.1 % | −15.3 % | 0.53 | 17.4 % | ✗ |
| baseline s215_doff_eoff (flat 21.5 %) | 9.2 % | −17.5 % | 0.53 | 14.2 % | −9.8 % | 1.44 | 21.5 % | — |
| EXP-3540 winner s100_d479_eoff | 5.3 % | −4.9 % | **1.07** | 5.3 % | −4.3 % | **1.23** | 10 % flat | — |

(D = test MaxDD ≤ 10 %; C = test CAGR ≥ 9.9 % (70 % × 14.2 %); R = top-3-of-6 both periods. Spike windows, per-ticker metrics, equity curves and daily sizing audit: `results/*.json`, `analysis.json`.)

## Ship gate: **NO config passes** (0 / 6)

- Winner `vt08_fon` passes DD (−9.7 %) but reaches only 5.3 % test CAGR vs the 9.9 % required — the 8 % target runs mean eff-risk ~9 % and can't recover the carry.
- `vt08_foff` is rank-stable (train #2 / test #3) and passes DD, but fails the same CAGR leg.
- vt12/vt16 fail the DD leg outright: test MaxDD −13.6 %…−15.3 % — **worse than the unprotected baseline's −9.8 %**.
- Combined 24-config universe (18 EXP-3540 cells + 6 vol-target): the rank-stable top-5 set is **still empty**, and no vol-target config even enters the top-5 of either period. EXP-3540's `s100_d479_eoff` (flat 10 % + 4/7/9 tiers) dominates every vol-target cell on Calmar in both train (1.07 vs ≤ 0.49) and test (1.23 vs ≤ 0.60).

## Why vol-targeting fails for this book

1. **Trailing vol is reactive, entry sizing is sticky.** Positions are ~30 DTE hold-to-expiry; the crash always hits positions sized during the preceding calm. ATR20 only de-sizes *after* the damage — SPY standalone MaxDD improves modestly (−50 % → −28 % at vt08) but never below the tiers.
2. **Vol-targeting sizes UP exactly when short-put tail risk accumulates.** In the benign test period σ runs low, eff-risk pins its cap (21.5 % fon / up to 34 % foff at vt16), and the Apr-2025 tariff window then hits a fully-sized book: vt16/vt12 test DD ends *worse* than flat 21.5 %. Trailing realized vol does not price short-vol crash risk — the June-2026 lesson again.
3. **Post-crash it under-sizes the recovery**, when premium selling pays best — that's where the CAGR gap vs flat sizing comes from (vt08 full-window CAGR 4.1 % vs 5.2 % for flat 10 %, at double the MaxDD: −9.7 % vs −4.9 %).
4. **Portfolio effect:** suppressing the profitable XLF/XLI legs (they run low σ) raises SPY's effective weight in the equal-weight book, so portfolio DD degrades even where per-ticker SPY DD improves.

## Conclusions

- Hypothesis refuted: continuous trailing-vol sizing is strictly worse than flat-low sizing (s100) and worse still than flat-low + tight discrete tiers (EXP-3540 winner) for this hold-to-expiry premium book, in both regimes.
- The EXP-3540 recommendation stands: **10 % flat risk + tight 4/7/9 flatten tiers** remains the best protection config tested; its full gate failure is the structural regime-split rank instability, not performance.
- If this axis is pursued further, the signal must be *anticipatory*, not trailing — e.g. IV/VIX-term-structure-conditioned sizing at entry, or per-trade max-loss scaled to option-implied (not realized) vol. Trailing-vol variants (longer lookbacks, EWMA) would only slow the reaction further and are not worth cells.

## Files

- `run_cell.py` — cell runner (sizing rule + hook documented in docstring)
- `queue.txt` / `run_grid.sh` — 18-cell queue and driver
- `results/{TICKER}_{cell}.json` — per-cell metrics, equity curve, daily σ/eff-risk audit trail
- `analyze.py` / `analysis.json` — portfolio aggregation, gate evaluation, combined-universe ranks
