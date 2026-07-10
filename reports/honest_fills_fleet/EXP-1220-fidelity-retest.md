# EXP-1220 Fidelity-Gap Re-test — RETIRED (dead-config discovery + faithful-twin ruin)

**Date:** 2026-07-10 · **Author:** cc1
**Trigger:** cc1 proposal Rev 2 step 2 — "close the two twin-fidelity gaps that could plausibly flip EXP-1220's sign, then re-test once; if still ≤ 0, retire."
**Runner:** `experiments/honest-fills-fleet/run.py exp1220_faithful {naive|marketable}` · SPY 2020-01-02 → 2026-04-02, real marks, offline, FIX #3 fill models.
**Supersedes:** the side-by-side results in `EXP-1220.md` (its Rev 2 header carries the same verdict); rollup headline updated in `FLEET_ROLLUP.md`.
**Delivery note:** headline communicated to Carlos by Maximus via the gateway — this file is the written record.

---

## Verdict

**EXP-1220 is retired as a launch candidate.** The faithful twin of its deployed behavior loses **−105.1 % (ruin) under naive fills and −91.4 % under honest marketable fills, with every calendar year negative** and an expectancy of **−$129/trade at an 80.7 % win rate**. The pre-registered kill criterion ("still ≤ 0 after the fidelity gaps close → retired, not resized, not re-argued") fires unambiguously.

## Finding 1 — the fidelity gaps were not gaps in the twin; they were dead configuration in production

The re-test plan assumed the engine twin was missing two live protections. A line-by-line audit of the deployed scan path (`strategies/credit_spread.py`, `main.py`, `shared/`, `compass/`) found the opposite: the *twin* had been honoring YAML keys that the *live scanner silently ignores*:

| `paper_exp1220.yaml` key | Believed live behavior | Actual live behavior | Evidence |
|---|---|---|---|
| `risk.scan_days: [0]` | Monday-only entries | **Dead config — entries every weekday** | zero code references; broker record shows Tue–Fri entries all quarter |
| `risk.drawdown_cb_pct: 10` | −10 % drawdown breaker | **Dead config — no per-experiment breaker exists** | zero references outside the backtester |
| `technical.use_trend_filter` (MA 20/50) | Trend-gated entries | **Dead config — never implemented** | zero references in scan path |
| `strategy.manage_dte: 5` | Close < 5 DTE | **Live** (closes at DTE ≤ 5) | `strategies/credit_spread.py:301` |
| `strategy.vix_max_entry: 35` | VIX entry gate | **Live** (hard block, rule 7.5) | `compass/risk_gate.py:264` |

The original honest-fills run shimmed the first two keys into the twin because the YAML declared them. That made the twin faithful to the *config file* and unfaithful to the *deployed system* — and those two phantom protections (5× less entry exposure; entry-halt after early losses) manufactured the −5.9 % "near-break-even" that briefly made EXP-1220 look like the fleet's best.

## Finding 2 — the faithful twin: ruin under both fill models

Faithful spec: daily entries, no per-experiment breaker, live `manage_dte ≤ 5` semantics (off-by-one in the earlier shim fixed), `vix_max_entry 35` kept, everything else unchanged (DTE 21–45/target 30, 5 % OTM, 5-wide, min-credit 6 %, PT 50 %, SL 2.0×, 9.35 % flat non-compounding, ≤ 20 contracts / 5 positions / 3 per expiration, combo regime ma_slow 50, ICs off).

| Metric | faithful naive | faithful marketable |
|---|---|---|
| Trades | 622 | 589 |
| Total return | **−105.1 % (ruin)** | **−91.4 %** |
| Max DD | −105.2 % | −98.7 % |
| Win rate | 80.6 % | 80.7 % |
| Expectancy/trade | −$143 (win +$487 ×501 / loss −$2,752 ×121) | −$129 (win +$436 ×475 / loss −$2,486 ×114) |
| Per-year | +9.1 / +13.6 / −78.0 / −32.1 / −127.7 / dead | −12.7 / −0.7 / −70.8 / −8.2 / −1.2 / −18.5 / −50.6 (2026Q1) |
| Unfilled slot attempts | 0 | 41,862 |

```json
{"experiment": "EXP-1220", "variant": "faithful_retest", "runner": "experiments/honest-fills-fleet/run.py exp1220_faithful", "window": ["2020-01-02", "2026-04-02"],
 "naive": {"trades": 622, "total_return": -105.13, "cagr": -100.0, "win_rate": 80.55, "sharpe": null, "max_dd": -105.15, "pct_unfillable": 0.0},
 "marketable": {"trades": 589, "total_return": -91.37, "cagr": -32.44, "win_rate": 80.65, "sharpe": null, "max_dd": -98.72, "pct_unfillable": 98.6, "pct_unfillable_basis": "slot_attempts", "unfilled_entries": 41862},
 "sharpe_note": "equity approaches/crosses zero; not meaningful",
 "dead_config_keys": ["risk.scan_days", "risk.drawdown_cb_pct", "technical.use_trend_filter"],
 "live_keys_confirmed": ["strategy.manage_dte", "strategy.vix_max_entry"],
 "verdict": "RETIRED — pre-registered kill criterion fired (cc1 proposal Rev 3)"}
```

Interpretation: EXP-1220's live risk discipline (losers cut at −$40…−$260 on the broker record) is real, but it only slows the bleed of a negative-expectancy entry stream. Its clean +6.2 % live quarter was a short, favorable-regime sample of a process that loses in every year of the six-year faithful replay. A risk process is necessary, not sufficient.

## Finding 3 — dead configuration is a fleet-wide operational hazard

Operators believed a weekly cadence, a −10 % breaker, and a trend filter were protecting EXP-1220. **None was implemented.** This is the EXP-3570 backtest-vs-live divergence class, now proven at the individual-key level, and it cuts both ways: phantom protections flatter twins, and *believed* protections that don't exist expose live capital. Two consequences:

1. **Config-to-code parity audit** of every key in every deployed YAML is now a standing prerequisite for any twin claim, launch case, or risk statement (added to `FLEET_ROLLUP.md` cross-fleet finding #5).
2. The dead keys double as the first entries of the bounded expectancy search's variant menu (cc1 proposal Rev 3): weekly cadence, a real trend filter, and a real drawdown breaker are *plausible mechanisms that were never actually tested* — the phantom-flattered −5.9 % run is weak evidence they might matter, now to be tested deliberately, one-shot, against the holdout.

## Updated rollup headline (mirrored in FLEET_ROLLUP.md)

> **Nine strategies assessed. Zero show positive edge under either fill model. Five of nine ruin the account outright — including EXP-1220, the last near-break-even candidate, once its twin was made faithful to deployed behavior. The fleet has no surviving launch candidate; the edge gate is unmet program-wide; next work must change the strategies, not the measurement.**

Consequences already recorded elsewhere: EXP-1220 retired (cc1 proposal Rev 3, launch withdrawn); EXP-800 Tradier halt-and-drain reinforced (fourth strike); bounded pre-registered expectancy search is the only path back to a launch pipeline; "no launch in 2026" remains an acceptable outcome.
