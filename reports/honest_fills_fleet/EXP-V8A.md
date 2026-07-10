# EXP-V8A — Honest Fill Model Re-run (FIX #3, `fill_model=marketable`)

**Date:** 2026-07-10 · **Author:** cc4 (fleet job, parallel with cc1/cc2)
**Code:** main @ post-`11f140c` (FIX #3 merge) · **Runners:** `experiments/EXP-V8A-BT-honest-fills/run_stream.py {stream} {fill}` + `aggregate.py`
**Window:** 2020-01-02 → 2025-12-19 (all streams; QQQ option marks in `data/options_cache.db` end 2025-12-19), real marks, real VIX/VIX3M (SQLite indices), offline — no broker/live/deploy changes.
**Results files:** `experiments/EXP-V8A-BT-honest-fills/results/{stream}_{fill}.json`, `portfolio_{fill}.json` (not committed, reproducible).

## ⚠️ EXP-V8A has NO faithful full-portfolio backtest twin — this is a per-stream run + documented aggregation

A full-portfolio honest-fill run is **infeasible**, for four independent reasons:

1. **The FIX #3 `fill_model` flag exists only in `backtest/backtester.py`** (the options credit-spread engine). The headline v8a figures (Sharpe 6.39 / CAGR 118 % / MaxDD 5.1 %) came from compass-level portfolio backtests over *stream return series* — there is no options-level fill to re-model in that machinery, so those numbers cannot be honesty-checked with this tool at all.
2. **The live allocator is not replicable offline:** Ledoit-Wolf risk-parity weights + 12 % vol target + dollar-notional sizing consume live covariance estimates; `registry.json` has `backtest_config: null` for EXP-V8A.
3. **4 of the 8 designed streams are outside the credit-spread engine entirely** (gld_cal / slv_cal are ETF-vs-futures basis trades; cross_vol; v5_hedge) — and were never deployed anyway (MVP = 4 credit-spread streams).
4. **A live-window replay is impossible for QQQ** (live since 2026-05-26; QQQ marks end 2025-12-19) — and EXP-3510/3520/3540 already established the deployed scanner diverged from the canonical config (per-stream oversizing), so even a perfect engine run would not reproduce the paper account.

What IS run here, per the task's fallback: the **4 live MVP credit-spread streams**, each ported from the live signal source (`compass/exp2690_signal_generators.py`) into the real engine on real marks, naive AND marketable, then aggregated with fixed weights.

### Stream fidelity (what was ported, what was approximated)

| Stream | Ticker | Rules ported (live generator) |
|---|---|---|
| exp1220 | SPY | 30Δ short put, 28 DTE, $5 width, Monday entries, VIX>40 block, VIX>VIX3M term-inversion block, VoV z>2 block / 1<z≤2 half-size (EXP-1970 panel) |
| qqq_cs | QQQ | 25Δ, 30 DTE, $5, Monday, VIX>40 block |
| xlf_cs | XLF | 20Δ, 30 DTE, $5, Monday, VIX>40 block |
| xli_cs | XLI | 20Δ, 30 DTE, $5, Monday, VIX>40 block |

Exits per the documented `vrp_position_monitor` spec (`paper_expv8a.yaml`): PT 50 % of credit, stop 2× credit, close at ≤7 DTE, crisis close-all at VIX>45. One open position per stream (`stream_gates.max_open_per_stream: 1`).

Approximations (identical across fill models, so the naive-vs-marketable delta is fills-only):
- **Sizing:** flat 5 % max-loss per trade on $100k per stream — NOT the live vol-target allocator (see above). Level-dependent metrics (return/DD) are therefore indicative, not live-predictive.
- **Aggregation:** fixed weights, daily-rebalanced — EXP-2600 equal-risk baseline (`PORTFOLIO_WEIGHTS`) renormalized over the 4 live streams: exp1220 0.3705, xlf_cs 0.2872, xli_cs 0.2251, qqq_cs 0.1172.
- **Gates use prior-session index closes** (the live 9:25 ET generator only has completed bars); engine's legacy trend-MA gate neutralized (live streams have no trend filter); no credit floor (streams specify none); delta-based *strike selection* uses the engine's BS-approx deltas — selection only, all *pricing* is real cache marks (Rule Zero).
- **Note on live monitor state:** `vrp_position_monitor` shipped `enabled: false` (operator-flip cutover); this run models the documented spec, not whatever exit behavior the paper account actually had.
- **Chain-density caveat:** XLF/XLI cache chains are sparse (9k/17k contracts vs SPY 198k) — entry opportunities are fewer than live weekly cadence would produce; 5–9 roll-DTE closes per sector stream booked at carried marks (no same-day quote). `fill_model_naive_fallbacks = 0` in all 8 runs — every marketable entry was evaluated against real bar data.

## Side-by-side results

### Aggregated 4-stream portfolio (fixed weights, daily rebalanced)

| Metric | naive | marketable | Δ |
|---|---|---|---|
| Trades (pooled) | 337 | 241 | **−28.5 %** |
| Total return | −9.50 % | −22.01 % | −12.5 pp (worse) |
| CAGR | −1.66 % | −4.08 % | |
| Win rate (pooled) | 62.32 % | 55.60 % | −6.7 pp |
| Sharpe | −0.44 | −1.11 | worse |
| Max DD | −12.97 % | −23.49 % | deeper |
| Raw per-slot fill rejections | 0 | 13,517 | |

### Per stream

| Stream | naive: trades / total / Sharpe / MaxDD / WR | marketable: trades / total / Sharpe / MaxDD / WR |
|---|---|---|
| exp1220 (SPY) | 172 / −14.03 % / −0.24 / −24.15 % / 69.8 % | 128 / **−39.87 %** / −0.85 / −43.70 % / 63.3 % |
| qqq_cs | 79 / −4.42 % / −0.15 / −9.01 % / 60.8 % | 43 / −17.79 % / −0.98 / −18.51 % / 48.8 % |
| xlf_cs | 41 / −8.60 % / −1.04 / −9.59 % / 39.0 % | 30 / −6.16 % / −0.90 / −7.05 % / 30.0 % |
| xli_cs | 45 / −7.92 % / −0.67 / −8.17 % / 57.8 % | 40 / −10.78 % / −1.02 / −11.09 % / 57.5 % |

(Win rate = trades with net P&L > 0 after commissions; ≤7-DTE roll closes with small negative P&L count as losses, which is why sector-stream win rates look low despite PT-dominated exits.)

## Machine-readable results

```json
{
  "experiment": "EXP-V8A",
  "faithful_twin": false,
  "twin_gap": "No full-portfolio twin possible: fill_model exists only in the credit-spread engine while the Sharpe-6.39 figures come from compass-level stream-return backtests; live Ledoit-Wolf vol-target allocator has no offline twin (registry backtest_config=null); gld_cal/slv_cal/cross_vol/v5_hedge are outside the engine; QQQ marks end 2025-12-19 so the live window cannot be replayed. Results below = 4 live MVP credit-spread streams through the real engine, flat 5%/trade sizing, fixed-weight daily-rebalanced aggregation (exp1220 .3705 / xlf_cs .2872 / xli_cs .2251 / qqq_cs .1172).",
  "method": "per-stream engine runs + fixed-weight aggregation (see fidelity section)",
  "window": ["2020-01-02", "2025-12-19"],
  "portfolio": {
    "naive":      {"trades": 337, "total_return": -9.50,  "cagr": -1.66, "win_rate": 62.32, "sharpe": -0.44, "max_dd": -12.97, "pct_unfillable": 0.0},
    "marketable": {"trades": 241, "total_return": -22.01, "cagr": -4.08, "win_rate": 55.60, "sharpe": -1.11, "max_dd": -23.49, "pct_unfillable": 28.5,
                   "raw_slot_rejections": 13517, "naive_fallbacks": 0}
  },
  "per_stream": {
    "exp1220": {"naive":      {"trades": 172, "total_return": -14.03, "cagr": -2.50, "win_rate": 69.77, "sharpe": -0.24, "max_dd": -24.15},
                 "marketable": {"trades": 128, "total_return": -39.87, "cagr": -8.18, "win_rate": 63.28, "sharpe": -0.85, "max_dd": -43.70, "pct_unfillable": 25.6, "raw_slot_rejections": 8213}},
    "qqq_cs":  {"naive":      {"trades": 79,  "total_return": -4.42,  "cagr": -0.76, "win_rate": 60.76, "sharpe": -0.15, "max_dd": -9.01},
                 "marketable": {"trades": 43,  "total_return": -17.79, "cagr": -3.23, "win_rate": 48.84, "sharpe": -0.98, "max_dd": -18.51, "pct_unfillable": 45.6, "raw_slot_rejections": 3432}},
    "xlf_cs":  {"naive":      {"trades": 41,  "total_return": -8.60,  "cagr": -1.50, "win_rate": 39.02, "sharpe": -1.04, "max_dd": -9.59},
                 "marketable": {"trades": 30,  "total_return": -6.16,  "cagr": -1.06, "win_rate": 30.00, "sharpe": -0.90, "max_dd": -7.05,  "pct_unfillable": 26.8, "raw_slot_rejections": 1014}},
    "xli_cs":  {"naive":      {"trades": 45,  "total_return": -7.92,  "cagr": -1.37, "win_rate": 57.78, "sharpe": -0.67, "max_dd": -8.17},
                 "marketable": {"trades": 40,  "total_return": -10.78, "cagr": -1.89, "win_rate": 57.50, "sharpe": -1.02, "max_dd": -11.09, "pct_unfillable": 11.1, "raw_slot_rejections": 858}}
  }
}
```

## Verdict

1. **All four live VRP credit-spread streams lose money on real marks under BOTH fill models**, and honest fills make three of four *worse* (exp1220: −14 % → −40 %). Unlike EXP-800-BT — where unfillable entries reduced negative-edge volume and shrank the loss — here the marketable limit (open-mark − slippage) systematically books *thinner credits* on the fills that do happen, and 28.5 % of naive fills never happen at all. The naive model was flattering both fill availability AND per-trade economics.
2. **The Sharpe-6.39 / CAGR-118 % v8a story is untouchable by this tool — and that is the finding.** Those numbers live in a different simulation layer (stream-return portfolio math) with no options-level fill model to audit. Nothing connects them to executable trades: the closest executable expression of the 4 deployed streams is negative for six straight years before the live allocator is even considered.
3. **Consistency with the live record:** EXP-V8A Alpaca paper is −14.9 % broker-verified; IBKR filled 4/24 orders (17 %) — a live confirmation that marketability is a first-order effect, in line with the 28.5–45.6 % per-stream unfillable shares measured here (QQQ worst).
4. This adds an independent engine-level strike against restarting EXP-V8A (currently halted, `vrp_engine.dry_run: true` since 24b4eff): the streams' executable edge is negative on real marks, the honest-fill haircut is large, and no component of the +6.39-Sharpe claim survives contact with the options-level engine. Any V8A revival should start by backtesting the streams *in this engine* to a positive result before portfolio math is allowed to multiply anything.
