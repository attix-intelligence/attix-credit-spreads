# EXP-P1F — TLT Rate-Vol Premium — RESULTS

**Date:** 2026-07-12 · **Author:** cc2 · **Prereg:** `reports/profitability_program/EXP-P1F_PREREG.md` (committed `710498a`, BEFORE any run)
**Runner:** `experiments/honest-fills-fleet/run_p1f.py` · window TLT 2020-01-02 → 2024-12-31 (hard cap — no data past 2024-12-31 read), **marketable fills only**, real marks (`options_cache.db`), offline.
**Results files:** `experiments/honest-fills-fleet/results/p1f_V*.json` (gitignored per repo convention).
**Friction ledger:** `research/FRICTION_LEDGER.md` cited per program rule; call-side DOA extension in the prereg (only 30-DTE-wide-2%OTM clears on the call side; variants were scoped accordingly before the run).

## Bottom line

**Zero variants pass. Not one reaches the ≥ 40 closed-trades gate — the failure mode is fill starvation, not negative edge.** Under honest marketable fills on TLT's daily-bar marks, 99.0–99.5% of per-slot entry attempts never fill; five years of Monday entries produce only 2–25 closed trades per variant. Within those starved samples every variant is (meaninglessly) positive, all gates except trade count clear, and 2022 — the rates bear this experiment existed to stress — stays within −2% everywhere. The honest verdict is **"cannot demonstrate the premium is harvestable at our venue/fill model — insufficient sample"**, which is exactly what P0A's warning that TLT spreads are wide predicted, and which only EXP-P0B's live TLT probes can now resolve.

## Scored results (all six pre-registered variants, marketable fills)

| Gate | V1 put-30 | V2 call-30 | V3 strangle-30 | V4 put-15 | V5 trend-30 | V6 put-30-rich |
|---|---|---|---|---|---|---|
| Closed trades (≥ 40) | **12 ✗** | **13 ✗** | **25 ✗** | **9 ✗** | **8 ✗** | **2 ✗** |
| Total return (> 0) | +0.11% ✓ | +0.13% ✓ | +0.24% ✓ | +1.62% ✓ | +2.47% ✓ | +1.32% ✓ |
| Expectancy/trade (> $0) | +$27.89 ✓ | +$28.75 ✓ | +$28.34 ✓ | +$198.35 ✓ | +$327.59 ✓ | +$678.83 ✓ |
| MaxDD (≥ −20%) | −4.39% ✓ | −3.47% ✓ | −5.77% ✓ | −3.20% ✓ | −1.20% ✓ | −2.39% ✓ |
| Worst year incl. 2022 (≥ −15%) | −1.26% ✓ | −1.41% ✓ | −0.76% ✓ | −1.95% ✓ | 0.00% ✓ | 0.00% ✓ |
| `naive_fallbacks` (≤ 20%) | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ |
| Win rate | 83.3% | 84.6% | 84.0% | 88.9% | 100% | 100% |
| Unfilled slot attempts | 1,482 | 1,170 | 2,648 | 1,326 | 1,326 | 1,482 |
| **PASS?** | **NO — insufficient sample** | **NO** | **NO** | **NO** | **NO** | **NO** |

2022 detail (the pre-registered stress test): V1 −0.33%, V2 0.00% (zero call-side fills in 2022 — fill scarcity even in the year that should favor call spreads), V3 −0.33%, V4 −1.95%, V5 0.00%, V6 +1.32%. The single worst trade in the whole experiment was a −$1,922 stop-out (V1, Jul-2023); trade mechanics were coherent throughout (credits 12–29% of the $4 width, PT wins $300–770, 2× stops ≈ −$1.9k).

## Interpretation — read this before quoting any number above

1. **The positive expectancies are not evidence of edge.** 2–25 trades over five years is far below any statistical floor; the prereg's own multiple-comparisons section (~0.3 spurious passers expected across 6 variants) applies with more force to sub-samples this small. The ≥ 40-trade gate exists precisely so these numbers cannot be promoted. Nothing here re-enters any pipeline.
2. **The binding constraint is the fill model on daily bars.** TLT has no intraday bars, so FIX #3 marketable degrades to a static day-limit priced at the day-open spread mark: it fills only when the day's traded range crosses the limit. On TLT's wide, thinly-traded chains this happens on ~5% of entry-attempt days (vs ~40–50% for SPY in the fleet runs). This is either (a) truth — TLT verticals at our size/venue rarely fill at acceptable credit, i.e. the P0A wide-spread warning realized; or (b) partly an artifact of approximating a two-leg spread's traded range from daily leg OHLC. **P0B live TLT probes are the only instrument that can distinguish (a) from (b)** — the prereg pre-committed this dependency, and the finding sharpens the case for adding 1-lot TLT spreads to the P0B probe schedule.
3. **Pre-registered kill criteria: NOT triggered.** "Both directions negative → family closed" — both directions are positive; the family is not closed on edge grounds. "Fallback share > 20% on all variants" — fallbacks were 0. The formal outcome is the third branch: **no pass, no kill — sample-starved; parked pending P0B.**
4. **What survives as signal, faintly:** the only structural read consistent across variants is that when fills DID occur, premium collection behaved as the bond-VRP hypothesis predicts (84–100% PT-exit rates, small stops, 2022 contained). That is compatible with the hypothesis and equally compatible with luck at n≤25. V5's 8-for-8 with zero drawdown in the gated variant is the kind of number that has fooled this program before — it is 8 trades.
5. **Correlation note (pre-stated in prereg):** V1/V4/V6 share the put side and V3 contains V1+V2 — the six results are ~2–3 independent observations, not 6.

## Recommended next step (program-consistent, no new authority claimed)

Park EXP-P1F. Add TLT 1-lot vertical probes to the EXP-P0B schedule (needs only Carlos's existing probe-commission approval to cover a second underlier). If P0B shows real TLT fills materially better than the day-limit model, a re-run under this same prereg (no variant changes — the prereg stays valid) with a calibrated fill haircut is the cheapest possible second look. If P0B confirms the model, TLT verticals are closed by capacity, not by edge, and the program moves on.

## Machine-readable results

```json
{
  "experiment": "EXP-P1F",
  "prereg": "reports/profitability_program/EXP-P1F_PREREG.md",
  "prereg_commit": "710498a",
  "runner": "experiments/honest-fills-fleet/run_p1f.py",
  "underlier": "TLT",
  "window": ["2020-01-02", "2024-12-31"],
  "fill_model": "marketable_only",
  "holdout_touched": false,
  "outcome": "no_pass_no_kill_sample_starved",
  "pass_count": 0,
  "binding_gate": "min_40_closed_trades",
  "pct_unfillable_basis": "per_scan_slot_foc_rejections/(rejections+filled)",
  "variants": {
    "V1_put30":      {"trades": 12, "total_return": 0.11, "cagr": 0.02, "win_rate": 83.33, "sharpe": 0.02, "max_dd": -4.39, "worst_year": -1.26, "expectancy_per_trade": 27.89, "pct_unfillable": 99.2, "naive_fallback_share": 0.0, "pass": false},
    "V2_call30":     {"trades": 13, "total_return": 0.13, "cagr": 0.03, "win_rate": 84.62, "sharpe": 0.02, "max_dd": -3.47, "worst_year": -1.41, "expectancy_per_trade": 28.75, "pct_unfillable": 98.9, "naive_fallback_share": 0.0, "pass": false},
    "V3_strangle30": {"trades": 25, "total_return": 0.24, "cagr": 0.05, "win_rate": 84.0,  "sharpe": 0.03, "max_dd": -5.77, "worst_year": -0.76, "expectancy_per_trade": 28.34, "pct_unfillable": 99.1, "naive_fallback_share": 0.0, "pass": false},
    "V4_put15":      {"trades": 9,  "total_return": 1.62, "cagr": 0.32, "win_rate": 88.89, "sharpe": 0.22, "max_dd": -3.2,  "worst_year": -1.95, "expectancy_per_trade": 198.35, "pct_unfillable": 99.3, "naive_fallback_share": 0.0, "pass": false},
    "V5_trend30":    {"trades": 8,  "total_return": 2.47, "cagr": 0.49, "win_rate": 100.0, "sharpe": 0.4,  "max_dd": -1.2,  "worst_year": 0.0,   "expectancy_per_trade": 327.59, "pct_unfillable": 99.4, "naive_fallback_share": 0.0, "pass": false},
    "V6_put30rich":  {"trades": 2,  "total_return": 1.32, "cagr": 0.26, "win_rate": 100.0, "sharpe": 0.18, "max_dd": -2.39, "worst_year": 0.0,   "expectancy_per_trade": 678.83, "pct_unfillable": 99.9, "naive_fallback_share": 0.0, "pass": false}
  },
  "kill_criteria": {"both_directions_negative": false, "fallback_share_gt_20pct_all": false, "triggered": "none"},
  "recommendation": "park pending P0B TLT fill probes; prereg remains valid for a calibrated re-run; no pipeline promotion"
}
```
