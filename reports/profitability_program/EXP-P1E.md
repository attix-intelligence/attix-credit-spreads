# EXP-P1E — Skew-Harvest Butterflies (Debit-Reclassified) — RESULTS

**Date:** 2026-07-13 · **Author:** cc2 · **Prereg:** `EXP-P1E_PREREG.md` (committed before any run; unchanged; includes the pre-prereg geometry DOA that reclassified this from credit-BWB to debit-convexity)
**Runner:** `experiments/wave2/run_p1e.py` (shared multi-leg harness) · 2020-01-02 → 2024-12-31 · marketable only · holdout seal verified · JSONs in `experiments/wave2/results/` (gitignored).

## Bottom line

**Zero passers; the all-six-negative kill criterion FIRED — the butterfly family is CLOSED.** Systematically bought put flies lose in every variant (−25.8% to ruin), with win rates of 8–26%: a fly's payoff requires the underlier to finish near the body strike, and harvesting "rich skew" by owning flies weekly does not overcome that pin requirement. Fill rates were healthy (67–84% — the fill-rate kill did NOT trigger) and friction shares were within budget for four of six, so this is a clean negative-edge verdict on real marks, not an execution artifact.

**The one finding worth keeping:** the crash-positive geometry (X2) did exactly what its tail claim promised — **positive in BOTH pre-registered stress windows** (Mar-2020 +7.6%, calendar-2022 +18.8%) while bleeding −35 to −60%/yr in calm years. That is not a return stream; it is the classic convexity-hedge profile, and it belongs (if anywhere) in EXP-P1C's *hedge-mode* track (pre-registered there as: allowed ≥ −3%/yr carry iff 2020 and 2022 each > +10%). X2's calm-year bleed (~10× the P1C budget at this sizing) means even that would need radical de-sizing — recorded here as an observation for the P1C prereg author, not a recommendation.

## Scored results

| Gate | X1 SPY-flat-30 | X2 SPY-crash-30 | X3 SPY-cheap-30 | X4 QQQ-flat-30 | X5 QQQ-crash-30 | X6 SPY-crash-15 |
|---|---|---|---|---|---|---|
| Total return > 0 | −116.8%¹ ✗ | −82.5% ✗ | −25.8% ✗ | −44.1% ✗ | −46.8% ✗ | −116.0%¹ ✗ |
| Expectancy > $0 | −$885 ✗ | −$602 ✗ | −$246 ✗ | −$1,695 ✗ | −$1,874 ✗ | −$800 ✗ |
| MaxDD ≥ −20% | ✗ | ✗ | −25.9% ✗ | ✗ | ✗ | ✗ |
| Worst year ≥ −15% | ✗ | ✗ | −10.8% ✓ | ✗ | ✗ | ✗ |
| ≥ 40 trades | 132 ✓ | 137 ✓ | 105 ✓ | 26 ✗ | 25 ✗ | 145 ✓ |
| Fill rate ≥ 40% | 73.7% ✓ | 68.2% ✓ | 75.5% ✓ | 83.9% ✓ | 67.6% ✓ | 75.5% ✓ |
| Friction ≤ 35% of debit | 29.8% ✓ | 21.1% ✓ | 40.0% ✗ | 37.4% ✗ | 23.3% ✓ | 27.9% ✓ |
| Stress: Mar-2020 / 2022 | 0.0 / **+88.9**² | **+7.6 / +18.8** | 0.0 / −2.5 | −2.5 / −3.9 | −2.2 / −0.1 | 0.0 / −10.6 |
| **PASS?** | **NO** | **NO** | **NO** | **NO** | **NO** | **NO** |

¹ X1/X6 breach −100% (ruin); their post-ruin per-year figures (e.g. +1228% on near-zero equity in 2024) are degenerate — ignore. ² X1's 2022 +88.9% is on already-crushed equity; X2 is the honest stress read.
Win rates 8.0–25.6%. X4/X5 (QQQ) effectively died in 2020 and traded residually thereafter — their trade counts are 2020-dominated.

## Attribution

- **Geometry:** the *cheap* control (X3) lost least (−25.8%) — paying less debit loses less, which is the null hypothesis of skew harvesting, not support for it. The crash geometry converts calm-year bleed into stress-year payoff (X2); the flat geometry just bleeds.
- **DTE:** 15-DTE (X6) ≈ 30-DTE (X2) but faster — shorter flies pin even less often.
- **Underlier:** QQQ flies ruined faster in 2020 (higher vol, wider bodies missed).

## Pre-registered kill assessment

"All six negative → butterfly family closed" — **TRIGGERED.** Also the friction kill fired for X3/X4 individually (>35% of debit). Family closed; no geometry search beyond the three pre-registered.

## Machine-readable results

```json
{
  "experiment": "EXP-P1E", "prereg": "reports/profitability_program/EXP-P1E_PREREG.md",
  "runner": "experiments/wave2/run_p1e.py", "harness": "backtest/multileg.py",
  "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable_only", "holdout_touched": false,
  "outcome": "zero_passers_family_killed", "pass_count": 0,
  "kill_triggered": "all_six_negative",
  "geometry_doa": "all credit-BWB geometries priced at median debit (see prereg); experiment ran debit-reclassified",
  "variants": {
    "X1_SPY_flat_30":  {"trades": 132, "total_return": -116.83, "win_rate": 20.45, "sharpe": -0.43, "max_dd": -120.57, "worst_year": -106.44, "expectancy_per_trade": -885.09,  "fill_rate": 73.7, "pnl_2020_03": 0.0,  "pnl_2022": 88.9,  "friction_share_of_debit": 29.8, "ruin": true,  "pass": false},
    "X2_SPY_crash_30": {"trades": 137, "total_return": -82.49,  "win_rate": 25.55, "sharpe": -0.97, "max_dd": -86.96,  "worst_year": -60.57,  "expectancy_per_trade": -602.15,  "fill_rate": 68.2, "pnl_2020_03": 7.56, "pnl_2022": 18.84, "friction_share_of_debit": 21.1, "ruin": false, "pass": false, "note": "positive in BOTH stress windows — hedge-mode shape, P1C-adjacent"},
    "X3_SPY_cheap_30": {"trades": 105, "total_return": -25.78,  "win_rate": 22.86, "sharpe": -1.86, "max_dd": -25.85,  "worst_year": -10.76,  "expectancy_per_trade": -245.55,  "fill_rate": 75.5, "pnl_2020_03": 0.0,  "pnl_2022": -2.54, "friction_share_of_debit": 40.0, "ruin": false, "pass": false},
    "X4_QQQ_flat_30":  {"trades": 26,  "total_return": -44.08,  "win_rate": 15.38, "sharpe": -1.55, "max_dd": -45.1,   "worst_year": -41.46,  "expectancy_per_trade": -1695.42, "fill_rate": 83.9, "pnl_2020_03": -2.54,"pnl_2022": -3.9,  "friction_share_of_debit": 37.4, "ruin": false, "pass": false},
    "X5_QQQ_crash_30": {"trades": 25,  "total_return": -46.84,  "win_rate": 8.0,   "sharpe": -1.29, "max_dd": -49.89,  "worst_year": -46.85,  "expectancy_per_trade": -1873.55, "fill_rate": 67.6, "pnl_2020_03": -2.19,"pnl_2022": -0.12, "friction_share_of_debit": 23.3, "ruin": false, "pass": false},
    "X6_SPY_crash_15": {"trades": 145, "total_return": -115.98, "win_rate": 23.45, "sharpe": -0.8,  "max_dd": -122.26, "worst_year": -103.16, "expectancy_per_trade": -799.83,  "fill_rate": 75.5, "pnl_2020_03": 0.0,  "pnl_2022": -10.58,"friction_share_of_debit": 27.9, "ruin": true,  "pass": false}
  },
  "corr_vs_A4": null
}
```
