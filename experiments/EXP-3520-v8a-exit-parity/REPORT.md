# EXP-3520 — As-Deployed V8A Exit-Parity A/B (exits-off vs exits-on)

**Date:** 2026-07-03 · **Owner:** charles · **Status:** COMPLETE
**Lineage:** P0 from `research/NEXT_BACKTESTS.md`. Depends on EXP-3510 (real VIX served offline from the backfilled `data/historical_indices.sqlite`).
**Rule Zero:** real Polygon option marks (`data/options_cache.db`, offline), real Yahoo VIX. No synthetic data.

---

## TL;DR — hypothesis REJECTED, and that is the useful result

1. **The missing exit layer does NOT explain the June live failure.** Pre-registered gate: "mechanism confirmed if MaxDD(exits-off) ≥ 2× MaxDD(exits-on) in ≥3 of 5 stress windows." Actual: **0 of 5**. In 5 of 6 windows the as-deployed arm (no exits) had *shallower* drawdowns.
2. **PR-H-style exits actively hurt this strategy in backtest.** Equal-weight 3-stream portfolio, 2020-01 → 2026-04: exits-on **−4.26%, Sharpe −0.68, MaxDD −5.04%** vs exits-off **+4.25%, Sharpe +0.68, MaxDD −1.42%**. The 2.0× stop converts transient MTM dips of high-win-rate 0.20Δ spreads into realized losses (74 stop-outs across tickers), and the 50% PT caps winners while churning 2-2.6× more trades (more slippage/commission round-trips).
3. **The VIX-crisis exit is nearly inert:** `vix_close_all=45` fired 3 times in 6.25 years (COVID + 2025-04). Combined with EXP-3510's finding that June-2026 VIX peaked at **22.2**, VIX-threshold exits are the wrong tool for the observed failure mode.
4. **What actually explains June: leverage, not exits.** Backtest positions averaged **~1.3% max-loss/NAV per stream** (IV-rank-scaled sizing); live V8A-Alpaca ran **~21.5%/stream** (0.86× aggregate; `configs/paper_expv8a_ibkr.yaml:199` documents the observed 0.86×) and IBKR 3× ran ~75%/stream. At live sizing, ONE near-max-loss MTM excursion ≈ −21.5% NAV — matching the observed −21.9% June daily-close DD almost exactly. June (SPX −4.1%, first leg on NFP day 2026-06-05) marked the 0.20Δ short puts to near max loss at the trough; the book recovered as SPX bounced, hence V8A-Alpaca's June month of only −10.6% despite the −21.9% intramonth DD.

## What was run

- Engine: `backtest/backtester.py` (leg-collision guard ON), offline `data/options_cache.db`, real VIX via EXP-3510 backfill (`_POLYGON_INDICES_START` patched to 2027-01-01 → sqlite-only indices).
- Strategy = the **actual live VRP stream params** (`compass/live/vrp_streams.py:143-150`), not the dead champion YAML block: bull-put only, delta-selected 0.20Δ short, $5 width, target 30 DTE in [25,50], `vix_max_entry=40`, no trend/momentum/regime gating, no min-credit floor (live has only the PR-#95 credit>0 check), `max_positions=1` per ticker ≈ one spread per stream.
- Arms (only the exit layer differs; entries and sizing identical):
  - **exits_on** = PR-H as designed (`configs/paper_expv8a.yaml:291-297`): PT 50% of credit, SL 2.0× credit, `vix_close_all=45`. (PR-H's 7-DTE roll is not reproducible — the engine has no DTE-roll exit; positions run to expiry instead. This makes exits_on *slightly kinder* than true PR-H.)
  - **exits_off** = as deployed 2026-05-29 → June (monitor `enabled: false` in both live configs): hold to expiry; PT/SL unreachable; `vix_close_all=0`.
- Tickers SPY / XLF / XLI (QQQ excluded: options bars end 2025-12-19), window 2020-01-02 → 2026-04-01 (bars end 2026-04-02; **no June-2026 options data exists locally** — June itself is reasoned about via the sizing arithmetic above, EXP-3570 remains the direct replay).

## Results

| Ticker | Arm | Trades | Return | Sharpe | MaxDD | Exit mix |
|---|---|---:|---:|---:|---:|---|
| SPY | exits_on | 204 | −8.18% | −0.58 | −10.17% | PT 153 · SL 35 · VIX 2 · exp 14 |
| SPY | exits_off | 78 | +1.13% | +0.10 | −3.58% | exp-profit 69 · exp-loss 6 · no-data 3 |
| XLF | exits_on | 84 | +0.29% | +0.09 | −1.29% | PT 52 · SL 16 · exp 16 |
| XLF | exits_off | 51 | +5.13% | +1.08 | −0.78% | exp-profit 49 · exp-loss 2 |
| XLI | exits_on | 95 | −4.79% | −0.71 | −5.05% | PT 50 · SL 23 · VIX 1 · exp 21 |
| XLI | exits_off | 60 | +6.28% | +0.96 | −1.23% | exp-profit 59 · exp-loss 1 |
| **Portfolio (eq-wt)** | **exits_on** | — | **−4.26%** | **−0.68** | **−5.04%** | — |
| **Portfolio (eq-wt)** | **exits_off** | — | **+4.25%** | **+0.68** | **−1.42%** | — |

Stress-window portfolio drawdowns (windows chosen on real VIX; `q1_2026_dip` reported but not gate-counted):

| Window | VIX max | DD exits_on | DD exits_off | off/on ratio |
|---|---:|---:|---:|---:|
| covid_2020 (Feb–Apr 20) | 82.7 | −1.73% | −1.02% | 0.59 |
| bear_2022H1 | 36.5 | −1.69% | −0.70% | 0.41 |
| bear_2022H2 | 33.6 | −0.86% | −1.06% | 1.23 |
| aug_2024 | 38.6 | −0.74% | −0.50% | 0.67 |
| apr_2025 | 52.3 | −1.83% | −1.13% | 0.62 |
| q1_2026_dip | 31.0 | −0.83% | −0.60% | 0.72 |

**Gate: 0/5 windows with ratio ≥ 2× → mechanism NOT CONFIRMED.**

## Interpretation & caveats

- **Why exits hurt here:** 0.20Δ/$5/30-DTE spreads win ~90%+ at expiry (69/78 SPY exits-off expired profitable). A 2.0× credit stop sits well inside normal MTM noise for 30-DTE spreads, so it harvests losses that would usually mean-revert; PT 50% then truncates the winners that pay for them. This mirrors the EXP-3310 observation (71% win rate, near-zero Sharpe) — the strategy's problem is thin edge, not unmanaged tails.
- **Absolute DD levels are NOT live-comparable** (deliberately): the engine's IV-rank-scaled sizing held ~1.3% max-loss/NAV per stream vs live's ~21.5% (Alpaca) / ~75% (IBKR 3×). The A/B ratio is sizing-invariant (identical sizing in both arms); the live-scale implication is the ×16 / ×57 exposure multiplier, which is exactly what turns a routine dip into a −20%/−30% book DD.
- Other approximations (identical across arms): no 7-day re-entry cooldown, no LW risk-parity/vol-target sizing, no VIX-ladder entry multiplier, daily scan cadence vs live 5-min cycles.
- exits_on is flattered by the missing 7-DTE roll; true PR-H would have churned more, likely worse.

## Consequences for the program (feeds EXP-3530/3540/3550/3560)

1. **Re-arming V8A by "just enabling PR-H" is not supported by evidence** — in backtest it makes both return and DD worse. The June postmortem should shift from "missing exits" to **"max-loss/NAV was 0.86–3× against a strategy whose losing state is a routine −4% dip."** The binding fix is the sizing/vol-target (0.42 → materially lower) and/or per-stream max-loss caps, not exit rules.
2. **VIX-threshold protections are inert in June-like regimes** (VIX ≤ 22.2 while the book drew down 20%+). EXP-3540's grid should be re-scoped toward **equity-drawdown-triggered de-risking** (EXP-800-style tiers with true flatten — EXP-3560 arm B) and **event gates** (June's first leg was NFP day; EXP-3311's gate is live-proven adjacent), demoting the VIX-exit axis.
3. The stop-loss finding also matters for EXP-3550's variant (c) (MTM stop overlay on EXP-800): expect it to hurt; test but don't presume.

## Artifacts

- `run_arms.py` — reproducible runner (`run_arms.py <SPY|XLF|XLI> <exits_on|exits_off> [start end]`)
- `analyze.py` — portfolio + stress-window analysis, writes `results/analysis.json`
- `results/{TICKER}_{arm}.json` — metrics, exit mix, full trade log, daily MTM equity curve
- `results/run_*.log` — engine logs
