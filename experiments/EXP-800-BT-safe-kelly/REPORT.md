# EXP-800-BT — Standalone Backtest Twin of EXP-800 "Safe Kelly 4/7/9"

**Date:** 2026-07-03 · **Author:** kayley · **Status:** COMPLETED
**Clears:** sentinel GRANDFATHERED debt — `EXP-800.backtest_config` was null; now `configs/backtest_exp800.json`.
**Runner:** `experiments/EXP-800-BT-safe-kelly/run.py` · **Results:** `results/SPY_{flatten,haltonly,notiers}.json`

## Verdict

**EXP-800 has a negative edge on real option marks over 2020-01-02 → 2026-04-02, in every breaker interpretation.** The EXP-400 champion signal core (DTE 15, OTM 2%, width $12, PT 55%, SL 1.25×) produces a profit factor of 0.54–0.72 on 828–1,240 real-mark trades; the Safe Kelly layer only determines how fast the losses compound. Separately, the backtest exposes a **deadlock bug in the deployed tier-3 logic**: after a crash realizes losses past −12% while the book is flat, the scanner blocks entries forever (98% of the window in the as-deployed variant).

| | flatten (as documented) | haltonly (as deployed) | notiers (no breakers) |
|---|---|---|---|
| Total return | **−45.2%** | **−20.2%** (then dead) | **−94.9%** |
| CAGR | −9.2% | −3.5% | −37.8% |
| Sharpe (daily, ann.) | −0.96 | −0.45 | −0.69 |
| MaxDD (daily close) | **−45.8%** | −21.0% | **−94.8%** |
| Win rate | 66.9% | 60.0% | 70.2% |
| Trades | 828 | 25 | 1,240 |
| Profit factor | 0.54 | 0.23 | 0.72 |
| Avg win / avg loss | $93 / −$348 | $408 / −$2,606 | $271 / −$883 |
| Breaker fires (T1/T2/T3) | 3 / 1 / 1 | 3 / 1 / 1 | — |
| Tier-3 flattens | 19 | 0 (no flatten live) | — |
| Entry-blocked days | 580 | **1,536 of 1,571** | 0 |
| Ending capital ($100k start) | $54,765 | $79,828 | $5,131 |

Per-year returns (%):

| Variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026→Apr |
|---|---|---|---|---|---|---|---|
| flatten | −24.2 | −3.4 | −12.4 | −0.3 | −8.1 | −1.3 | −5.6 |
| haltonly | −20.2 | 0 | 0 | 0 | 0 | 0 | 0 |
| notiers | −57.1 | −4.7 | −45.8 | +9.8 | −35.0 | −41.5 | −43.6 |

## Method

- **Engine:** `backtest/backtester.py` (real engine), offline real Polygon marks from `data/options_cache.db` (SPY daily marks → 2026-04-02, intraday → 2026-02-24 with daily-close fallback). Rule Zero: no synthetic data.
- **VIX:** real VIX/VIX3M from `data/historical_indices.sqlite` via the post-8f1bc8c loader (loud SQLite fallback; **no `_POLYGON_INDICES_START` monkeypatch**). The combo regime and the VIX-40 entry gate saw real vol the whole window — this backtest would have been invalid before that fix.
- **Signals:** EXP-400 champion exactly — target DTE 15 (window 15–25), static 2% OTM strikes, $12 width, PT 55% of credit, SL 1.25× credit, min credit 5% of width, VIX>40 entry block.
- **Regime → direction:** engine `iron_condor.neutral_regime_only` mode = EXP-800's mapping (bull→bull_put, neutral→iron_condor, bear→bear_call) with the canonical `ComboRegimeDetector` (MA80 ±0.5% band, RSI 50/45, VIX/VIX3M 0.95/1.05, bear-unanimous, 3-day cooldown).
- **Safe Kelly layer:** state machine ported verbatim from `scripts/exp800_safe_kelly_scanner.py` (`KellyStateDB.update_equity` + `_kelly_fraction` + the unconditional tier≥3 entry block): 9/7/4% of current MTM equity by regime, compounding; HWM never resets; T1 −8% halve, T2 −10% floor 2%, T3 −12% halt 30 scan-days, recovery above −7%. Caps 30 contracts / 17% per trade (never bound — max 8 contracts used).
- **Sizing base fidelity:** engine flat sizing risks % of cash capital; live risks % of Alpaca MTM equity — the overlay rescales daily so sizing is off MTM equity like live. Iron condors are re-sized to the live scanner's single-wing/put-credit formula (a live oversizing quirk vs the engine's two-wing convention).
- Full deviation ledger (momentum filter never applied live, VIX-structure percentile proxy live vs real ratio here, weekday-vs-Friday expirations, per-key stacking cap 4 ≈ `max_same_expiration`): `configs/backtest_exp800.json → fidelity_notes`.

## Breaker behavior (the interesting part)

- **2020-02-24:** the COVID gap gapped equity from DD −7.7% straight past all three tiers to **−21.0% in one day** — every open spread stopped out at 1.25× the same day. Tiers 1/2 never got to de-risk; a −8/−10/−12 ladder is too slow for a gap regime.
- **As deployed (`haltonly`): permanent deadlock.** With losses *realized* and the book flat, DD is frozen at −21%, tier stays 3, and the scanner's `cb_tier >= 3` check blocks entries unconditionally — the 30-trade halt counter is decorative (`_kelly_fraction`'s halt check is unreachable-relevant). EXP-800 never traded again for the remaining **1,536 trading days**. The live account has not hit this only because live DD (June 2026 −31.1%) was *unrealized* — open positions kept marking and recovered.
- **As documented (`flatten`):** with EXP-3540 anti-thrash semantics (post-halt floor-sizing resume, re-flatten only on a ≥1pp new DD low), the system trades on — but because HWM never resets, it spends **98% of the window at tier 3** trading the 2% floor, bleeding to −45%. 19 flattens fired.
- Time at tier (both breaker variants): tier 0 ≈ 33 days, tier 1 ≈ 2 days, tier 3 ≈ 1,536 days. The tier ladder as designed is effectively a one-way trap door.

## Sanity anchor vs live paper (honest flags)

1. **The +21.2% (Apr) / +3.4% (May) / +11.3% (Jun) 2026 Alpaca paper months are OUTSIDE the data window** (options marks end 2026-04-02; live paper started 2026-03-28). There is no real overlap to calibrate against — ~4 trading days.
2. Q1-2026 in-backtest: flatten −0.4 / −0.3 / −4.9% (Jan/Feb/Mar); notiers −2.5 / −1.7 / **−39.3%**. The March-2026 notiers collapse is the same signature as the live June-2026 −31% DD: concentrated MTM loss at full 9% sizing with stacked positions.
3. **A fresh paper account is not the backtest steady state.** Live accounts bootstrap a fresh HWM at $100k and trade full 9/7/4 Kelly; the backtest is tier-3-pinned at the 2% floor from Feb 2020 onward. The live account's strong start (equity $114,897 two weeks in) is consistent with fresh-HWM full-Kelly variance, not evidence of edge — the unprotected twin (`notiers`) shows what full-Kelly does over a full cycle: −94.9%.
4. **MaxDD flag (per spec):** backtest MaxDD is NOT milder than the live −31.1% June DD — it is worse (−45.8% documented / −94.8% unprotected). The `haltonly` −21.0% looks milder only because that variant stops trading in Feb 2020. Note the inverse of the anticipated flag: live tier-3 "flatten" not being implemented means live can (and did) blow through −12% to −31% with positions open, which the flatten-modeled variant cannot.
5. Registry `backtest_baseline` for EXP-800 (win 78%, avg_pnl +$525) traces to EXP-400's pre-real-data backtest; on real marks the same core wins only 67–70% with a 0.27–0.31 payoff ratio → negative expectancy (~−$53/trade at floor sizing).

## Recommendation

- **Do not scale EXP-800 live capital on the strength of the 3 paper months.** The real-mark twin says the signal core loses across 2020–2026; Apr–Jun 2026 live is consistent with variance.
- **Fix the tier-3 deadlock in `exp800_safe_kelly_scanner.py`** regardless of any strategy decision: after the halt counter is exhausted, either re-anchor HWM or fall back to tier-2 floor sizing — today a realized −12% while flat bricks the strategy silently.
- The −8/−10/−12 ladder cannot de-risk through a gap; if EXP-800 stays live, EXP-3540's tighter 4/7/9 tiers (fired *before* the gap in that grid) are the tested alternative.
- Extend `data/options_cache.db` SPY marks past 2026-04-02 to backtest the actual live months (Apr–Jun 2026) before the next capital decision.

## Reproduce

```
.venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py flatten
.venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py haltonly
.venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py notiers
```
(Needs POLYGON_API_KEY for SPY daily bars only — auto-loaded from `.env.expv8a`; options marks and VIX are fully offline. Never touches Tradier/Alpaca.)
