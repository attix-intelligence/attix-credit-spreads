# Bounded Expectancy Search — RESULTS: 0 of 12 variants pass. Holdout not run.

**Date:** 2026-07-10 · **Author:** cc1
**Pre-registration:** `EXPECTANCY_SEARCH_PREREG.md` (commit `b3cb9c4`, committed before any run — variants and criteria unchanged since)
**Runner:** `experiments/honest-fills-fleet/search.py {V0..V12} search` · marketable fills only · SPY 2020-01-02 → 2024-12-31, real marks, offline. Raw results: `experiments/honest-fills-fleet/results/search_V*_search.json` (local, per repo `*.json` gitignore).

## Verdict

**No variant meets the pre-registered search-window criteria** (total return > 0 AND expectancy > $0 AND MaxDD ≥ −20 % AND worst year ≥ −15 % AND ≥ 40 trades). Per the pre-registration: **the holdout (2025–2026Q1) is not run for any variant and remains unmined**; the search stops; and the documented program conclusion activates:

> **This strategy family — SPY put credit spreads at survivable sizing — cannot clear retail frictions on 2020–2024 real marks under honest fills, with any of the twelve pre-registered causal mechanisms applied singly or in the two strongest combinations.** Any further search requires a fresh pre-registration with *new mechanisms* (not parameter jitter on these), per the anti-fishing rule.

## Results table (search window, marketable fills; pass requires ALL five criteria)

| Variant | Mechanism | Trades | Total | Exp/trade | WR | MaxDD | Worst yr | Verdict |
|---|---|---|---|---|---|---|---|---|
| V0 (control) | faithful EXP-1220 base | 450 | −77.2 % | −$146 | 80.2 % | −87.7 % | −70.8 (2022) | — |
| **V1** | weekly cadence (Mon only) | 127 | **−3.2 %** | **+$0.42** | 83.5 % | **−16.0 %** | −5.2 (2022) | **FAIL** (total ≤ 0) |
| V2 | 200d-MA trend gate | 306 | −55.0 % | −$154 | 81.1 % | −61.6 % | −39.0 (2022) | FAIL |
| V3 | real month-anchored breaker | 407 | −68.2 % | −$150 | 78.6 % | −70.6 % | −51.5 (2022) | FAIL |
| V4 | Δ0.15 strike selection | 249 | −103.2 % ☠ | −$388 | 72.3 % | −104.5 % | −108.9 (2022) | FAIL |
| V5 | Δ0.10 strike selection | 353 | −96.3 % | −$247 | 73.9 % | −102.5 % | −68.9 (2024) | FAIL |
| V6 | credit floor 6 %→10 % | 263 | −10.8 % | −$15 | 84.8 % | −51.2 % | −34.2 (2022) | FAIL |
| V7 | tight stop (SL 1.0×) | 277 | −101.4 % ☠ | −$340 | 63.9 % | −101.4 % | −103.7 (2022) | FAIL |
| V8 | wide exit (PT 65 / SL 1.5×) | 423 | −89.5 % | −$186 | 71.9 % | −91.6 % | −75.5 (2022) | FAIL |
| V9 | NFP gate (T-1/T0) | 419 | −70.7 % | −$143 | 80.2 % | −80.5 % | −63.1 (2022) | FAIL |
| V10 | contango gate (VIX<VIX3M) | 443 | −68.8 % | −$129 | 80.6 % | −79.1 % | −62.6 (2022) | FAIL |
| V11 | trend + Δ0.15 | 293 | −106.1 % ☠ | −$336 | 74.1 % | −105.8 % | −189.9 (2024) | FAIL |
| V12 | trend + breaker + NFP ("the config the YAML pretended to be") | 286 | −37.4 % | −$113 | 81.5 % | −40.7 % | −18.8 (2022) | FAIL |

## What the search taught (attribution, not selection)

1. **Cadence dominates every risk mechanism.** V1 (weekly entries) removed 94 % of the loss (−77 % → −3.2 %) and is the only variant with positive per-trade expectancy (+$0.42, i.e., zero). Daily entry stacking — 5 concurrent overlapping spreads, each new one sold into whatever the last one already priced — is the single largest destroyer of P&L in the family. It still **fails the gate** and the one-shot rule forbids promoting an "almost": near-zero on 127 trades is exactly the coin-flip result the gate exists to reject.
2. **Premium selectivity is the second signal.** V6 (credit floor 10 %) was positive in 4 of 5 years (+2.4/+10.0/−34.2/+7.1/+12.6) — the only variant with a mostly-positive year profile — and 2022 still destroyed it. Selling only rich premium helps; it does not survive a bear year at daily cadence.
3. **Every "protection" bounds losses; none creates expectancy.** Trend gate, breaker, NFP gate, contango gate each shaved 10–40 pp off the control's loss and left expectancy deeply negative. V12 (all three at once) still lost −37 %. This closes the question the dead-config discovery opened: even if the YAML's phantom protections had been real, EXP-1220 would have lost — just more slowly.
4. **Delta-targeted strikes and tighter stops actively hurt** (V4/V5/V7/V11 are the worst results, three of them ruins): at 5-wide widths, constant-delta sells closer to the money than 5 % OTM in calm tape, and a 1.0× stop converts noise into realized losses at 36 % loss frequency. The family's instinctive "improvements" are anti-improvements under honest fills.
5. **2022 is the un-survivable year** for every long-biased variant (worst year in 10 of 13 rows). No mechanism tested converts a short-put book into something that tolerates a grinding bear market; it can only lose less.

## Program consequence (per pre-registration and cc1 proposal Rev 3)

- The launch pipeline has **zero candidates**; the holdout is preserved unmined for any future, freshly pre-registered search.
- A future search, if Carlos wants one, should start from what attribution (not selection) suggests: **weekly cadence + rich-premium selectivity as the base**, plus a genuinely new mechanism for bear-year survival (e.g., structural hedge, regime-conditional shutdown with a *tested* signal, or a different premium structure entirely). That is a new pre-registration with new mechanisms — explicitly not a promotion of V1/V6, whose numbers above are already selection-tainted by having been seen.
- The standing recommendations are unchanged: EXP-800 Tradier halt-and-drain; config-to-code parity audit; no launch in 2026 remains an acceptable outcome.

## Machine-readable results

```json
{"search": "bounded_expectancy_v1", "prereg_commit": "b3cb9c4", "window": ["2020-01-02", "2024-12-31"], "fill_model": "marketable",
 "passers": [], "holdout_run": false,
 "criteria": {"total_return_gt": 0, "expectancy_gt": 0, "max_dd_gte": -20, "worst_year_gte": -15, "min_trades": 40},
 "rows": [
  {"v": "V0", "mech": "control", "trades": 450, "total": -77.24, "exp": -145.81, "wr": 80.22, "max_dd": -87.69, "worst_year": -70.77},
  {"v": "V1", "mech": "weekly_cadence", "trades": 127, "total": -3.22, "exp": 0.42, "wr": 83.46, "max_dd": -16.03, "worst_year": -5.23, "fail": ["total_return"]},
  {"v": "V2", "mech": "trend_gate_ma200", "trades": 306, "total": -54.97, "exp": -153.84, "wr": 81.05, "max_dd": -61.64, "worst_year": -39.04},
  {"v": "V3", "mech": "month_anchored_breaker", "trades": 407, "total": -68.19, "exp": -149.8, "wr": 78.62, "max_dd": -70.62, "worst_year": -51.53},
  {"v": "V4", "mech": "delta_0.15", "trades": 249, "total": -103.19, "exp": -388.47, "wr": 72.29, "max_dd": -104.51, "worst_year": -108.88},
  {"v": "V5", "mech": "delta_0.10", "trades": 353, "total": -96.34, "exp": -247.23, "wr": 73.94, "max_dd": -102.45, "worst_year": -68.93},
  {"v": "V6", "mech": "credit_floor_10pct", "trades": 263, "total": -10.76, "exp": -14.91, "wr": 84.79, "max_dd": -51.23, "worst_year": -34.18},
  {"v": "V7", "mech": "stop_1.0x", "trades": 277, "total": -101.4, "exp": -340.19, "wr": 63.9, "max_dd": -101.4, "worst_year": -103.69},
  {"v": "V8", "mech": "pt65_sl1.5", "trades": 423, "total": -89.48, "exp": -185.7, "wr": 71.87, "max_dd": -91.6, "worst_year": -75.5},
  {"v": "V9", "mech": "nfp_gate", "trades": 419, "total": -70.67, "exp": -142.83, "wr": 80.19, "max_dd": -80.53, "worst_year": -63.08},
  {"v": "V10", "mech": "contango_gate", "trades": 443, "total": -68.81, "exp": -129.48, "wr": 80.59, "max_dd": -79.11, "worst_year": -62.55},
  {"v": "V11", "mech": "trend_plus_delta15", "trades": 293, "total": -106.08, "exp": -336.19, "wr": 74.06, "max_dd": -105.81, "worst_year": -189.87},
  {"v": "V12", "mech": "trend_breaker_nfp", "trades": 286, "total": -37.41, "exp": -112.54, "wr": 81.47, "max_dd": -40.71, "worst_year": -18.77}
 ]}
```
