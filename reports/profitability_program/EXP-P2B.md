# EXP-P2B — Event-Premium Harvesting (FOMC/CPI/NFP) — RESULTS

**Date:** 2026-07-13 · **Author:** cc2 · **Prereg:** `EXP-P2B_PREREG.md` (committed before any run; unchanged)
**Runner:** `experiments/wave2/run_p2b.py` (shared multi-leg harness) · 2020-01-02 → 2024-12-31 · marketable only · holdout seal verified · JSONs in `experiments/wave2/results/` (gitignored).

## Bottom line

**Zero passers, and the pre-registered kill criterion FIRED: E1 (gated) and E2 (unconditional) are both decisively negative (−21.2% / −23.3%), so the event-premium family is CLOSED on SPY at this structure — no threshold search, no structure search.** Selling scheduled-event premium via short-DTE iron flies lost money in 4 of 5 years; the trade is short a gap that the market, on this evidence, does not overprice at the ATM fly's odds. Two secondary findings matter for the program: the richness gate was **uninformative in effect** (it admitted 78% of events vs 87% unconditional and produced a nearly identical return path — the pre-stated signal-source claim fails on its own terms), and the realized credits were healthy ($473–564 median vs the $70.40 DOA bar), so this is a genuine negative-edge verdict, not a friction artifact.

## Scored results

| Gate | E1 SPY-gated | E2 SPY-uncond | E3 QQQ-gated | E4 FOMC | E5 CPI | E6 NFP |
|---|---|---|---|---|---|---|
| Total return > 0 | −21.24% ✗ | −23.29% ✗ | −13.95% ✗ | −16.36% ✗ | **+2.80% ✓** | −7.68% ✗ |
| Expectancy > $0 | −$531 ✗ | −$555 ✗ | −$1,744 ✗ | −$1,363 ✗ | +$175 ✓ | −$640 ✗ |
| MaxDD ≥ −20% | −21.8% ✗ | −24.3% ✗ | −14.1% ✓ | −17.1% ✓ | −13.0% ✓ | −9.1% ✓ |
| Worst year ≥ −15% | −14.5% ✓ | −16.6% ✗ | −11.2% ✓ | −11.6% ✓ | −9.8% ✓ | −3.7% ✓ |
| ≥ 40 trades | 40 ✓ | 42 ✓ | 8 ✗ | 12 ✗ | 16 ✗ | 12 ✗ |
| Fallback ≤ 20% | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ | 0 ✓ |
| Median credit ≥ $70.40 (realized DOA) | $521 ✓ | $510 ✓ | $312 ✓ | $564 ✓ | $473 ✓ | $557 ✓ |
| **PASS?** | **NO** | **NO** | **NO** (starved) | **NO** | **NO** (attribution, n=16) | **NO** |

Per-year, E1: 2020 −14.5 · 2021 +0.9 · 2022 +3.1 · 2023 −6.1 · 2024 −5.7. The 2020 COVID regime is the single largest destroyer (flies through March-2020 events), but 2023–24 — calm years that should be the strategy's bread and butter — also bled.

## Attribution reads (pre-registered as such)

- **Richness gate: uninformative.** Events admitted 78% (E1) vs 87% (E2) — inside the pre-stated informative band but with near-zero selectivity in effect; E1's path is E2's path minus a handful of trades. The "measured pre-event richness" signal, at the pre-registered causal form and constant, does not separate good event-sells from bad ones. Per the prereg, the signal-source claim fails independently of P&L.
- **Event-type attribution:** FOMC-only −16.4% (worst; 2022 −11.6% — hiking-cycle decisions gapped through the fly), NFP-only −7.7% (16.7% win rate), CPI-only **+2.8%**, but +15.0% of that came from 2022 alone (inflation-print era, richest credits) on 16 trades — a regime story, not an edge claim. If anything in this family ever merits a fresh look, it is "CPI in high-inflation regimes," which would be a NEW prereg with a NEW mechanism argument, not a continuation of this one.
- **E3 (QQQ): data-starved, not evidence** — only 11.9% of events produced a quotable ATM straddle pair on the cached QQQ chain (missing same-strike C/P close pairs), 8 trades. A QQQ verdict needs denser marks.

## Pre-registered kill assessment

"E1 and E2 both negative → event-premium family closed on SPY at this structure" — **TRIGGERED.** Closed. The realized-credit DOA and event-count kills did not trigger (credits healthy; 147 scheduled events found).

## Machine-readable results

```json
{
  "experiment": "EXP-P2B", "prereg": "reports/profitability_program/EXP-P2B_PREREG.md",
  "runner": "experiments/wave2/run_p2b.py", "harness": "backtest/multileg.py",
  "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable_only", "holdout_touched": false,
  "outcome": "zero_passers_family_killed", "pass_count": 0,
  "kill_triggered": "E1_and_E2_both_negative_SPY_family_closed",
  "richness_gate_informative": false,
  "variants": {
    "E1_SPY_all_gated":  {"trades": 40, "total_return": -21.24, "win_rate": 37.5,  "sharpe": -0.38, "max_dd": -21.78, "worst_year": -14.5,  "expectancy_per_trade": -530.9,  "median_credit": 521.0, "events_admitted_pct": 78.0, "naive_fallback_share": 0.0, "pass": false},
    "E2_SPY_all_uncond": {"trades": 42, "total_return": -23.29, "win_rate": 38.1,  "sharpe": -0.41, "max_dd": -24.3,  "worst_year": -16.56, "expectancy_per_trade": -554.54, "median_credit": 510.0, "events_admitted_pct": 86.8, "naive_fallback_share": 0.0, "pass": false},
    "E3_QQQ_all_gated":  {"trades": 8,  "total_return": -13.95, "win_rate": 25.0,  "sharpe": -0.78, "max_dd": -14.06, "worst_year": -11.23, "expectancy_per_trade": -1744.07, "median_credit": 312.0, "events_admitted_pct": 11.9, "naive_fallback_share": 0.0, "pass": false, "note": "data-starved: QQQ straddle pairs missing on cached chain"},
    "E4_SPY_fomc_gated": {"trades": 12, "total_return": -16.36, "win_rate": 33.33, "sharpe": -0.95, "max_dd": -17.13, "worst_year": -11.57, "expectancy_per_trade": -1363.32, "median_credit": 564.0, "events_admitted_pct": 87.2, "naive_fallback_share": 0.0, "pass": false},
    "E5_SPY_cpi_gated":  {"trades": 16, "total_return": 2.8,    "win_rate": 56.25, "sharpe": 0.11,  "max_dd": -12.99, "worst_year": -9.75,  "expectancy_per_trade": 175.11,  "median_credit": 473.0, "events_admitted_pct": 83.3, "naive_fallback_share": 0.0, "pass": false, "note": "2022-driven (+15.0% that year); attribution read only"},
    "E6_SPY_nfp_gated":  {"trades": 12, "total_return": -7.68,  "win_rate": 16.67, "sharpe": -0.92, "max_dd": -9.13,  "worst_year": -3.65,  "expectancy_per_trade": -639.85, "median_credit": 557.0, "events_admitted_pct": 66.7, "naive_fallback_share": 0.0, "pass": false}
  },
  "corr_vs_A4": null
}
```
