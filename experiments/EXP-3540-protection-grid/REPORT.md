# EXP-3540 — DD-Tier / Event-Gate / Sizing Protection Grid

**Date:** 2026-07-03 · **Status:** completed · **Window:** 2020-01-02 → 2026-04-01
**Engine:** real `backtest/backtester.py`, offline `data/options_cache.db` (real Polygon marks), real VIX from the EXP-3510 backfill (`data/historical_indices.sqlite`), Rule Zero, no live/scanner calls.
**Base strategy:** live VRP stream params (0.20Δ short put, $5 width, ~30 DTE, bull_put, vix_max_entry 40, hold-to-expiry per EXP-3520), compounding flat-risk sizing off current NAV, max_positions 1 per ticker.

## Grid

57 cells = 3 tickers (SPY, XLF, XLI) × [ 2 sizings × 3 DD-tier settings × 3 event gates ] + 1 demoted VIX-exit reference cell per ticker.

- **S** sizing (flat % of current equity per trade): `s215` = 21.5 % (live-like), `s100` = 10 %
- **D** equity-DD tiers with TRUE flatten: `doff` = none; `d81012` = deployed EXP-800 (halve @−8 %, floor @−10 %, flatten+halt-30td @−12 %); `d479` = tight (halve @−4 %, floor @−7 %, flatten @−9 %)
- **E** entry gate blocking the trading day before events: `eoff`, `enfp` (NFP), `enf` (NFP+FOMC)
- **V** reference: `v30` = vix_close_all 30 on the s215_doff_eoff base

**Protocol (fixed a priori):** portfolio = equal-weight sum of the 3 per-ticker equity curves. Winner = best portfolio Calmar on TRAIN 2020-01→2023-12. TEST 2024-01→2026-04 untouched until final validation. Ship gate (registry): test MaxDD ≤ 10 % **and** test CAGR ≥ 70 % of the same-sizing unprotected baseline **and** rank-stable (top-5 Calmar in both periods).

## Results (3-ticker portfolio)

| cell | train CAGR | train MaxDD | train Calmar | test CAGR | test MaxDD | test Calmar | Aug-24 DD | Apr-25 DD | gate |
|---|---|---|---|---|---|---|---|---|---|
| **s100_d479_eoff** ← winner | **5.3 %** | **−4.9 %** | **1.07** | **5.3 %** | **−4.3 %** | **1.23** | −1.6 % | −4.3 % | D✓ C✓ R✗ |
| s100_d479_enfp | 5.3 % | −4.9 % | 1.07 | 5.3 % | −4.3 % | 1.22 | −1.6 % | −4.3 % | D✓ C✓ R✗ |
| s100_d479_enf | 5.2 % | −4.9 % | 1.05 | 5.2 % | −4.3 % | 1.21 | −1.6 % | −4.3 % | D✓ C✓ R✗ |
| s215_d81012_eoff | 9.3 % | −9.0 % | 1.03 | 7.5 % | −10.0 % | 0.75 | −2.9 % | −10.0 % | ✗ |
| s215_d81012_enfp | 9.3 % | −9.0 % | 1.03 | 7.5 % | −10.0 % | 0.75 | −2.9 % | −10.0 % | ✗ |
| s215_d479_eoff | 9.3 % | −9.0 % | 1.03 | 8.1 % | −7.3 % | 1.12 | −2.9 % | −7.3 % | D✓ C✗ R✗ |
| s215_d479_enfp | 9.3 % | −9.0 % | 1.03 | 8.1 % | −7.3 % | 1.12 | −2.9 % | −7.3 % | D✓ C✗ R✗ |
| s215_d81012_enf | 9.1 % | −9.0 % | 1.00 | 7.5 % | −10.0 % | 0.75 | −2.9 % | −10.0 % | ✗ |
| s215_d479_enf | 9.1 % | −9.0 % | 1.00 | 8.1 % | −7.3 % | 1.12 | −2.9 % | −7.3 % | D✓ C✗ R✗ |
| s100_d81012_eoff | 3.6 % | −5.4 % | 0.66 | 5.8 % | −4.5 % | 1.30 | −1.3 % | −4.5 % | D✓ C✓ R✗ |
| s100_d81012_enfp | 3.6 % | −5.4 % | 0.66 | 5.8 % | −4.5 % | 1.29 | −1.3 % | −4.5 % | D✓ C✓ R✗ |
| s100_d81012_enf | 3.5 % | −5.4 % | 0.65 | 5.8 % | −4.5 % | 1.28 | −1.3 % | −4.5 % | D✓ C✓ R✗ |
| s100_doff_eoff (s100 baseline) | 4.7 % | −8.4 % | 0.55 | 6.1 % | −9.7 % | 0.62 | −2.3 % | −6.4 % | D✓ C✓ R✗ |
| s100_doff_enfp | 4.7 % | −8.4 % | 0.55 | 6.0 % | −9.7 % | 0.62 | −2.3 % | −6.4 % | D✓ C✓ R✗ |
| s100_doff_enf | 4.6 % | −8.4 % | 0.54 | 6.0 % | −9.8 % | 0.61 | −2.3 % | −6.4 % | D✓ C✓ R✗ |
| s215_doff_eoff (live-like baseline) | 9.2 % | −17.5 % | 0.53 | 14.2 % | −9.8 % | 1.44 | −2.8 % | −9.8 % | D✓ C✓ R✗ |
| s215_doff_enfp | 9.2 % | −17.5 % | 0.53 | 14.0 % | −9.8 % | 1.43 | −2.8 % | −9.8 % | D✓ C✓ R✗ |
| s215_doff_enf | 9.0 % | −17.6 % | 0.51 | 14.0 % | −9.8 % | 1.43 | −2.8 % | −9.8 % | D✓ C✓ R✗ |
| s215_doff_eoff_v30 (reference) | −12.5 % | −42.7 % | −0.29 | ~0 % (dormant) | 0 % | — | — | — | ref |

(D = test MaxDD ≤ 10 %, C = test CAGR ≥ 70 % of same-sizing baseline, R = top-5 Calmar both periods. Full per-cell metrics, equity curves, breaker logs: `results/*.json`, `analysis.json`.)

## Winner: `s100_d479_eoff` — 10 % flat risk + tight 4/7/9 tiers, no event gate

Chosen on train (Calmar 1.07, #1 of 18). Untouched-test validation held up almost exactly: CAGR 5.3 % → 5.3 %, MaxDD −4.9 % → −4.3 %, Calmar improved to 1.23.

vs baselines (full window 2020-01→2026-04):

| | CAGR | MaxDD | Calmar | end/start |
|---|---|---|---|---|
| winner s100_d479_eoff | 5.3 % | **−4.9 %** | 1.07 | 1.38× |
| s100_doff_eoff (same sizing, no protection) | 5.2 % | −9.7 % | 0.53 | 1.37× |
| s215_doff_eoff (live-like, no protection) | 11.0 % | −17.5 % | 0.63 | 1.92× |

At 10 % sizing the tight tiers **halve MaxDD (−9.7 % → −4.9 %) at zero CAGR cost** — the flattens (SPY: 2020-03-02, 3× in 2022, 2025-04-04) consistently cut losers early and the 30-day halts skipped mostly-bad regimes. Against the live-like config, the winner gives up half the CAGR for 3.6× less drawdown.

## Ship gate: **NO cell passes** (0 / 18)

The winner passes the DD leg (−4.3 % ≤ 10 %) and the CAGR leg (5.3 % ≥ 70 % of 6.1 %), but fails rank stability — and so does everything else: **train top-5 and test top-5 are disjoint sets.**

- Train top-5: s100_d479_{eoff,enfp,enf}, s215_d81012_{eoff,enfp} — protection-heavy.
- Test top-5: s215_doff_{eoff,enfp,enf}, s100_d81012_{eoff,enfp} — protection-light.

Cause is regime, not noise: train contains COVID and the 2022 bear (protection pays); test 2024-01→2026-04 is a benign grind-up whose worst events (Aug-2024 VIX spike, Apr-2025 tariff window) never hurt the unprotected book more than −9.8 %, so protection only costs carry there (s215_d479 test CAGR 8.1 % vs 14.2 % unprotected = 57 %, failing the 70 % leg). The June-2026 episode that motivated this grid is **outside the data window** (options bars end 2026-04-02), so the test period never stresses the tiers the way live did.

## Other findings

- **Sizing dominates everything.** Halving flat risk 21.5 % → 10 % cuts full-window MaxDD −17.5 % → −9.7 % on its own — more than either tier scheme adds at s215. This confirms EXP-3520: June was leverage, not exits.
- **Event gates are a no-op.** NFP/FOMC gating changed CAGR by ≤ 0.2 pp and MaxDD by ~0 in every pairing. With ~30 DTE hold-to-expiry positions, blocking one entry day barely changes exposure; June-2026-style NFP damage (open-position MTM, not entry timing) can't be fixed by an entry gate.
- **d81012 (deployed EXP-800 tiers) at s215 is the worst of both:** test MaxDD exactly −10.0 % (at gate boundary) with CAGR down to 7.5 % — the −8 %/−12 % thresholds are too loose to prevent deep DDs but tight enough to cost carry.
- **VIX close-all 30 (reference) is catastrophic:** −41 % per ticker, portfolio full-window CAGR −8.2 %, MaxDD −42.7 %; it force-realizes near-max losses at every vol spike then goes dormant (6–15 trades/ticker). Confirms the demotion of the VIX-exit axis and EXP-3520's anti-exit finding.
- Caveat: portfolio results lean on XLF/XLI (+126 %/+163 % unprotected) masking SPY (−18 %, −50 % standalone DD). Per-ticker JSONs carry the detail.

## Recommendation

Do not ship any grid cell as "validated" — the gate's rank-stability leg fails structurally (regime-split train/test). The actionable, gate-adjacent takeaway: **cut per-stream flat risk toward 10 % and add the tight 4/7/9 flatten tiers** (winner config) if the objective is capital preservation; it never exceeded −5 % portfolio DD in any window including both train crashes, at the cost of running ~half the live-like CAGR. If CAGR ≥ 70 %-of-baseline is binding, no tier scheme tested reconciles it with DD ≤ 10 % across both regimes; a vol-targeted sizing axis (continuous, not tiered) is the natural EXP-3550 candidate.

## Files

- `run_cell.py` — cell runner (tier semantics documented in its docstring)
- `queue.txt` / `remaining.txt` / `run_remaining.sh` — grid queue and resume driver
- `results/{TICKER}_{cell}.json` — 57 per-cell summaries + equity curves + breaker logs
- `analyze.py` / `analysis.json` — portfolio aggregation, ranks, gate evaluation
