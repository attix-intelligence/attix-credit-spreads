# EXP-P1B — Calendar/Diagonal Term-Structure VRP — RESULTS

**Date:** 2026-07-13 · **Author:** cc2 · **Prereg:** `EXP-P1B_PREREG.md` (committed before any run; unchanged)
**Runner:** `experiments/wave2/run_p1b.py` on the shared multi-leg harness (`backtest/multileg.py`) · 2020-01-02 → 2024-12-31 · marketable fills only · holdout seal verified active · results JSONs in `experiments/wave2/results/` (gitignored).

## Bottom line

**Zero of six variants pass.** Four are outright negative; the QQQ calendar (B3) is positive but produces only 9 trades in five years (sample-starved); and — the run's most important finding — **the pre-registered mark-trust gate caught the daily-cache mark path being untrustworthy for this structure on GLD/TLT**: worst realized losses ran 1.9–3.9× the modeled maximum loss (a calendar's max loss is the debit paid, by construction — losing 4× the debit means the marks, not the market, moved). Calendar P&L is a difference of two moderately illiquid close marks; on GLD/TLT chains that difference gaps in ways no honest fill model can trust. The family verdict is therefore split: **negative where testable (SPY), untrustworthy-data where not (GLD/TLT), and starved on QQQ.**

## Scored results

| Gate | B1 GLD-cal | B2 SPY-cal | B3 QQQ-cal | B4 TLT-cal | B5 GLD-diag | B6 SPY-call-cal |
|---|---|---|---|---|---|---|
| Total return > 0 | −24.40% ✗ | −7.94% ✗ | **+3.62% ✓** | −16.80% ✗ | −7.63% ✗ | −7.96% ✗ |
| Expectancy > $0 | −$1,162 ✗ | −$234 ✗ | +$402 ✓ | −$467 ✗ | −$283 ✗ | −$215 ✗ |
| MaxDD ≥ −20% | −26.9% ✗ | −10.8% ✓ | −1.6% ✓ | −18.0% ✓ | −13.0% ✓ | −9.9% ✓ |
| Worst year ≥ −15% | −13.6% ✓ | −6.5% ✓ | 0.0% ✓ | −11.0% ✓ | −6.1% ✓ | −5.2% ✓ |
| ≥ 40 trades | 21 ✗ | 34 ✗ | **9 ✗** | 36 ✗ | 27 ✗ | 37 ✗ |
| Fallback ≤ 20% / stale ≤ 20% | 0 / 4.0% ✓ | 0 / 2.3% ✓ | 0 / 1.8% ✓ | 0 / 0.9% ✓ | 0 / 3.7% ✓ | 0 / 4.4% ✓ |
| **Mark-trust (loss ≤ 1.5× modeled)** | **3.94 ✗✗** | 1.56 ✗ | 0.40 ✓ | **1.94 ✗** | **3.78 ✗** | 1.08 ✓ |
| **PASS?** | **NO — marks untrustworthy** | **NO** | **NO — insufficient sample** | **NO — marks untrustworthy** | **NO — marks untrustworthy** | **NO** |

Win rates 29–78%; per-year tables in the JSONs. No variant passed, so no correlation-vs-A4 section is triggered (prereg conditions it on passers).

## What the mark-trust gate caught (why this run's negative numbers should not be over-read)

Worst B1 trades: modeled debit **$0.46–0.89/1x** (vs the P0A ledger's GLD-calendar median of $131) sized to the 25-contract cap, then stopped next day at −$2,615…−$4,790 — losses of ~4× a debit that is supposed to bound them. A $0.46 ATM calendar is not a market price; it is two close marks printed out of sync (front and back legs marking at different times/liquidity). The prereg anticipated exactly this failure mode ("calendar risk models are mark-dependent; a breach means the pricing path is untrustworthy, which fails the experiment regardless of P&L"). Consequences:

1. **GLD/TLT calendar results here are a data verdict, not a strategy verdict.** The P0A ledger's premium *distributions* for these classes remain valid (medians over many samples), but trade-level daily-close P&L paths are not trustworthy on these chains.
2. **SPY/QQQ marks behaved** (ratios 1.08/0.40; B2's 1.56 is marginal — one trade slightly through the modeled bound). The clean negative on SPY (B2/B6, 71 trades combined, both sides of the term structure) is therefore a real result: at these exits (PT 30/stop 50/roll at 5 DTE, weekly cadence) the SPY term-structure carry did not clear friction in 2020–24.
3. **Opportunity scarcity is structural:** 21–53 entry attempts in five years (vs ~260 Mondays) — the same-strike-in-both-chains and DTE-window constraints bind hard on cached chains, and ~30–60% of attempts fail the honest day-limit fill test.

## Pre-registered kill assessment

"All six negative → family closed" — **not triggered** (B3 positive). The honest disposition: **SPY calendars closed on merits at these parameters; GLD/TLT calendars closed as untestable on cached daily marks** (re-open only if minute-level or quote data ever exists for them); **QQQ calendar parked** — its 9-trade positive profile (78% wins, PT exits, trivial DD, mark-trust clean) is the only live remnant, and it is far below evidential threshold.

## Machine-readable results

```json
{
  "experiment": "EXP-P1B", "prereg": "reports/profitability_program/EXP-P1B_PREREG.md",
  "runner": "experiments/wave2/run_p1b.py", "harness": "backtest/multileg.py",
  "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable_only", "holdout_touched": false,
  "outcome": "zero_passers", "pass_count": 0,
  "variants": {
    "B1_GLD_cal":      {"trades": 21, "total_return": -24.40, "cagr": -5.45, "win_rate": 28.57, "sharpe": -1.26, "max_dd": -26.88, "worst_year": -13.59, "expectancy_per_trade": -1161.99, "naive_fallback_share": 0.0, "stale_day_share": 4.04, "max_loss_vs_modeled": 3.94, "pass": false, "fail_mode": "mark_trust_breach"},
    "B2_SPY_cal":      {"trades": 34, "total_return": -7.94,  "cagr": -1.64, "win_rate": 44.12, "sharpe": -0.39, "max_dd": -10.84, "worst_year": -6.45,  "expectancy_per_trade": -233.56,  "naive_fallback_share": 0.0, "stale_day_share": 2.32, "max_loss_vs_modeled": 1.56, "pass": false, "fail_mode": "negative_edge"},
    "B3_QQQ_cal":      {"trades": 9,  "total_return": 3.62,   "cagr": 0.72,  "win_rate": 77.78, "sharpe": 0.48,  "max_dd": -1.64,  "worst_year": 0.0,    "expectancy_per_trade": 402.4,    "naive_fallback_share": 0.0, "stale_day_share": 1.75, "max_loss_vs_modeled": 0.40, "pass": false, "fail_mode": "insufficient_sample"},
    "B4_TLT_cal":      {"trades": 36, "total_return": -16.80, "cagr": -3.62, "win_rate": 33.33, "sharpe": -1.10, "max_dd": -17.96, "worst_year": -10.96, "expectancy_per_trade": -466.78,  "naive_fallback_share": 0.0, "stale_day_share": 0.93, "max_loss_vs_modeled": 1.94, "pass": false, "fail_mode": "mark_trust_breach"},
    "B5_GLD_diag":     {"trades": 27, "total_return": -7.63,  "cagr": -1.58, "win_rate": 59.26, "sharpe": -0.37, "max_dd": -12.98, "worst_year": -6.08,  "expectancy_per_trade": -282.65,  "naive_fallback_share": 0.0, "stale_day_share": 3.66, "max_loss_vs_modeled": 3.78, "pass": false, "fail_mode": "mark_trust_breach"},
    "B6_SPY_call_cal": {"trades": 37, "total_return": -7.96,  "cagr": -1.65, "win_rate": 45.95, "sharpe": -0.41, "max_dd": -9.88,  "worst_year": -5.15,  "expectancy_per_trade": -215.09,  "naive_fallback_share": 0.0, "stale_day_share": 4.38, "max_loss_vs_modeled": 1.08, "pass": false, "fail_mode": "negative_edge"}
  },
  "disposition": {"SPY_calendars": "closed_on_merits", "GLD_TLT_calendars": "closed_untestable_on_daily_marks", "QQQ_calendar": "parked_insufficient_sample"},
  "corr_vs_A4": null
}
```
