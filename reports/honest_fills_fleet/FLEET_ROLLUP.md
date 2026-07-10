# Honest-Fills Fleet Roll-up (FIX #3) — all paper-deployed strategies, naive vs marketable

**Date:** 2026-07-10 · **Author:** cc1 (roll-up across cc1/cc2/cc4/cc5 fleet runs)
**Code:** main @ post-`11f140c` (FIX #3 `backtest.fill_model`) · Window SPY 2020-01-02 → 2026-04-02 (EXP-V8A: → 2025-12-19, QQQ marks limit), real marks (`data/options_cache.db`), real VIX/VIX3M, offline.
**Sources:** `reports/EXP-800-BT-honest-fills-rerun.md` + `reports/honest_fills_fleet/EXP-{1220,400,401,3303B,3309,3311,503,V8A}.md` (machine-readable JSON blocks; per-experiment fidelity notes are in each file and NOT repeated here).

---

## Headline

**Nine strategies assessed. Zero show positive edge under either fill model. Not one.**

Every engine twin of the paper-deployed fleet loses money on 2020–2026 real marks, under both the legacy instant-fill model and the FIX #3 honest marketable-limit model. **Five of nine ruin the account outright** (total return ≤ −100 % on at least one fill model). Honest fills change loss *magnitudes* everywhere but flip **no sign anywhere**: the fleet's negative expectancy is a property of the strategies, not of the fill model that flattered them.

**Rev 2 (same day):** the original roll-up called EXP-1220's −5.9 % "best in fleet / near-break-even." The fidelity-gap re-test (`EXP-1220-fidelity-retest.md`, mirrored in `EXP-1220.md` Rev 2) showed that number was an artifact of two **dead-config shims** — `scan_days` (Monday-only) and `drawdown_cb_pct` are silently ignored by the deployed scanner (zero code references; broker record shows daily entries). The **faithful** EXP-1220 twin (daily entries, no phantom breaker): naive **−105.1 % (ruin)**, marketable **−91.4 % with every calendar year negative** (expectancy −$129/trade at an 80.7 % win rate). EXP-1220 joins the ruin list and is **retired as a launch candidate** per the pre-registered cc1 kill criterion. The fleet now has no near-break-even member.

## Fleet table — canonical variant per experiment

Sorted by marketable total return. "Twin" = fidelity status from each report (none is fully faithful; see per-experiment files).

| Experiment (variant) | Twin | Model | Trades | Total | CAGR | WR | Sharpe | MaxDD | Unfillable |
|---|---|---|---|---|---|---|---|---|---|
| **EXP-1220** (yaml-literal, incl. 2 dead-config shims — superseded) | partial | naive | 99 | −13.9 % | −2.4 % | 82.8 % | −0.24 | −17.5 % | — |
| | | mktbl | 164 | −5.9 % | −1.0 % | 84.2 % | −0.05 | −16.1 % | 98.2 % slot¹ |
| **EXP-1220 (faithful re-test)** ☠ | partial (live-audited) | naive | 622 | **−105.1 % ☠** | ruin | 80.6 % | n/m² | −105.2 % | — |
| | | **mktbl** | 589 | **−91.4 %** | −32.4 % | 80.7 % | n/m² | −98.7 % | 98.6 % slot¹ |
| **EXP-V8A** (4-stream MVP portfolio) | **no full twin** (proxy) | naive | 337 | −9.5 % | −1.7 % | 62.3 % | −0.44 | −13.0 % | — |
| | | **mktbl** | 241 | **−22.0 %** | −4.1 % | 55.6 % | −1.11 | −23.5 % | **28.5 %** |
| **EXP-800-BT** (haltonly, as deployed) | partial (Kelly port) | naive | 1,231 | −49.2 % | −10.3 % | 70.3 % | −0.84 | −49.7 % | — |
| | | **mktbl** | 487 | **−32.8 %** | −6.2 % | 64.7 % | −1.30 | −32.9 % | **60.4 %** trades |
| **EXP-400** (champion) | partial | naive | 28 | −61.0 % | −14.0 % | 53.6 % | −0.68 | −61.8 % | — |
| | | **mktbl** | 83 | **−74.5 %** | −19.7 % | 63.9 % | −0.48 | −80.7 % | 99.3 % slot¹ |
| **EXP-401** | **NO FAITHFUL TWIN** (≡ EXP-400 core proxy) | naive | 28 | −61.0 % | −14.0 % | 53.6 % | −0.68 | −61.8 % | — |
| | | **mktbl** | 83 | **−74.5 %** | −19.7 % | 63.9 % | −0.48 | −80.7 % | 99.3 % slot¹ |
| **EXP-503** (core, nocb) | **no faithful twin** (ML overlay unsupported) | naive | 476 | −101.6 % ☠ | ruin | 68.1 % | n/m² | −101.6 % | — |
| | | **mktbl** | 365 | **−102.0 % ☠** | ruin | 65.5 % | n/m² | −102.0 % | **23.3 %** |
| **EXP-3309** (entry-window port) | partial | naive | 399 | −102.7 % ☠ | ruin | 68.7 % | −0.30 | −102.2 % | — |
| | | **mktbl** | 354 | **−101.0 % ☠** | ruin | 65.0 % | −0.57 | −100.9 % | 89.0 % slot¹ |
| **EXP-3311** (NFP-gate port) | partial | naive | 156 | −119.2 % ☠ | ruin | 67.3 % | n/m² | −130.4 % | — |
| | | **mktbl** | 78 | **−109.7 % ☠** | ruin | 60.3 % | n/m² | −106.8 % | **50.0 %** |
| **EXP-3303B** (regime-gate port) | partial (gate = structural no-op) | naive | 170 | −158.4 % ☠ | ruin | 64.7 % | n/m² | −139.3 % | — |
| | | **mktbl** | 183 | **−100.9 % ☠** | ruin | 65.6 % | −0.50 | −102.7 % | 99.3 % slot¹ |

¹ *Slot basis* = per-scan-slot fill-or-cancel rejections ÷ (rejections + fills) across ~14 repricing slots/day — an upper bound; many rejections belong to one signal-day. Where a controlled estimate exists (no breaker-latch confound), the honest per-entry unfillable rate is **~23–50 %** (EXP-503 nocb 23.3 %, EXP-V8A 28.5 %, EXP-3311 50.0 %, EXP-800 trade-count 53–60 %). ² Sharpe not meaningful — equity crosses zero.

## Cross-fleet findings

1. **The fill model was flattering everything, but it was never the problem.** Roughly a quarter to a half of naive entries never actually fill (¹ above). Removing them shrinks losses where sizing was protected (EXP-800 −49→−33; the three ☠ champion-variants converge to ~−100 % instead of overshooting past it) and **worsens** results where sizing was unprotected flat (EXP-400 −61→−74.5; EXP-V8A portfolio −9.5→−22.0): honest fills spare you some negative-EV trades, or keep your account alive longer to place more of them. In no case does the sign flip. Per-trade quality is uniformly *worse* under marketable (win rates drop ~3–7 pp fleet-wide except path-confounded rows).
2. **Five account-ruins** — the champion 17 %-flat family (EXP-3303B/3309/3311/503-core) **plus EXP-1220 at 9.35 % once its twin was made faithful**; EXP-400/401 only avoid ≤ −100 % because the −40 % breaker freezes them in 2020. The 2026 paper quarter's −15 %…+45 % results for these same configs were regime beta on a rally, full stop.
3. **The differentiators don't differentiate.** EXP-3303B's regime gate is a proven structural no-op (0 fires in 41k evaluations — sibling finding); EXP-3311's NFP gate, which dodged the one live killer trade, does not rescue a 17 %-sized core over six years (−110 % marketable); EXP-401's straddle overlay and EXP-503's ML overlay have no engine support **and never traded live either**. EXP-1220's sizing/stop discipline remains visible in the live broker record (losers cut at −$40…−$260), but the faithful re-test shows it only slows the bleed of a negative-EV entry stream (−91 % over six years) — a risk process is necessary, not sufficient.
4. **Twin debt is fleet-wide.** Zero fully-faithful twins. Three explicit no-twin verdicts (EXP-401, EXP-503, EXP-V8A full portfolio); six partial twins with documented gaps, the largest being the live compass VIX-percentile regime proxy (the EXP-3570 divergence) which no engine run replicates. Registry `backtest_expectations` for 3303B/3309/3311 trace to unrelated v8a portfolio studies — provenance-invalid (sibling finding).
5. **Dead configuration is a fleet-wide ops hazard (Rev 2 finding).** The deployed scanner silently ignores YAML keys operators believed were active — `scan_days`, `drawdown_cb_pct`, `technical.use_trend_filter` at minimum. Protections that exist only in YAML protect nothing, and twins built from YAML inherit phantom safety. A **config-to-code parity audit** of every deployed key is now a standing prerequisite for any twin claim or launch case.
6. **Consequence for the go-live program:** the pre-registered edge gate ("positive expectancy net of costs on the honest twin") is **not met by any strategy in the program** — the last standing near-break-even (EXP-1220) fell to ruin-grade once its twin was made faithful, and the model holding real-money authority on Tradier (EXP-800: −33 % under honest fills) is at its fourth independent strike. The program's constraint is no longer measurement honesty — FIX #1–4 delivered that — it is that **the measured edge at deployed parameters is ≤ 0 everywhere**. Next work must change the strategies (entries, structure, or premium-selection), not the instruments that measure them.

## Machine-readable roll-up

```json
{
  "rollup": "honest_fills_fleet",
  "date": "2026-07-10",
  "code": "main@post-11f140c",
  "window_default": ["2020-01-02", "2026-04-02"],
  "experiments_assessed": 9,
  "fully_faithful_twins": 0,
  "no_faithful_twin": ["EXP-401", "EXP-503", "EXP-V8A"],
  "account_ruins_any_model": ["EXP-1220", "EXP-3303B", "EXP-3309", "EXP-3311", "EXP-503"],
  "positive_edge_any_model": [],
  "honest_unfillable_pct_range": [23.3, 60.4],
  "rows": [
    {"exp": "EXP-1220", "variant": "yaml-literal (SUPERSEDED — dead-config shims)", "naive": {"trades": 99, "total_return": -13.87, "sharpe": -0.24, "max_dd": -17.52, "win_rate": 82.83}, "marketable": {"trades": 164, "total_return": -5.94, "sharpe": -0.05, "max_dd": -16.06, "win_rate": 84.15, "pct_unfillable_slot": 98.15}},
    {"exp": "EXP-1220", "variant": "faithful re-test (canonical; retired per cc1 kill criterion)", "naive": {"trades": 622, "total_return": -105.13, "sharpe": null, "max_dd": -105.15, "win_rate": 80.55}, "marketable": {"trades": 589, "total_return": -91.37, "sharpe": null, "max_dd": -98.72, "win_rate": 80.65, "pct_unfillable_slot": 98.6}},
    {"exp": "EXP-V8A", "variant": "4-stream MVP portfolio proxy", "window": ["2020-01-02", "2025-12-19"], "naive": {"trades": 337, "total_return": -9.5, "sharpe": -0.44, "max_dd": -12.97, "win_rate": 62.32}, "marketable": {"trades": 241, "total_return": -22.01, "sharpe": -1.11, "max_dd": -23.49, "win_rate": 55.6, "pct_unfillable": 28.5}},
    {"exp": "EXP-800-BT", "variant": "haltonly (as deployed)", "naive": {"trades": 1231, "total_return": -49.23, "sharpe": -0.84, "max_dd": -49.69, "win_rate": 70.27}, "marketable": {"trades": 487, "total_return": -32.82, "sharpe": -1.3, "max_dd": -32.92, "win_rate": 64.68, "pct_unfillable_trades": 60.4}},
    {"exp": "EXP-400", "variant": "default", "naive": {"trades": 28, "total_return": -60.97, "sharpe": -0.68, "max_dd": -61.77, "win_rate": 53.57}, "marketable": {"trades": 83, "total_return": -74.53, "sharpe": -0.48, "max_dd": -80.67, "win_rate": 63.86, "pct_unfillable_slot": 99.26}},
    {"exp": "EXP-401", "variant": "NO_FAITHFUL_TWIN (champion-core proxy = EXP-400)", "naive": {"trades": 28, "total_return": -60.97, "sharpe": -0.68, "max_dd": -61.77, "win_rate": 53.57}, "marketable": {"trades": 83, "total_return": -74.53, "sharpe": -0.48, "max_dd": -80.67, "win_rate": 63.86, "pct_unfillable_slot": 99.26}},
    {"exp": "EXP-503", "variant": "core-only proxy, nocb", "naive": {"trades": 476, "total_return": -101.63, "sharpe": null, "max_dd": -101.62, "win_rate": 68.07}, "marketable": {"trades": 365, "total_return": -101.99, "sharpe": null, "max_dd": -101.98, "win_rate": 65.48, "pct_unfillable": 23.3}},
    {"exp": "EXP-3309", "variant": "entry-window port", "naive": {"trades": 399, "total_return": -102.73, "sharpe": -0.3, "max_dd": -102.16, "win_rate": 68.67}, "marketable": {"trades": 354, "total_return": -101.02, "sharpe": -0.57, "max_dd": -100.93, "win_rate": 64.97, "pct_unfillable_slot": 89.0}},
    {"exp": "EXP-3311", "variant": "NFP-gate port", "naive": {"trades": 156, "total_return": -119.21, "sharpe": null, "max_dd": -130.4, "win_rate": 67.31}, "marketable": {"trades": 78, "total_return": -109.73, "sharpe": null, "max_dd": -106.8, "win_rate": 60.26, "pct_unfillable": 50.0}},
    {"exp": "EXP-3303B", "variant": "regime-gate port (gate = no-op)", "naive": {"trades": 170, "total_return": -158.42, "sharpe": null, "max_dd": -139.33, "win_rate": 64.71}, "marketable": {"trades": 183, "total_return": -100.94, "sharpe": -0.5, "max_dd": -102.7, "win_rate": 65.57, "pct_unfillable_slot": 99.3}}
  ]
}
```

*Sharpe set to `null` in rows where equity crosses zero (not meaningful). Slot-basis vs controlled unfillable estimates are distinguished by key name.*
