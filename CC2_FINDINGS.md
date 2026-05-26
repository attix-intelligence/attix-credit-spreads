# CC2 FINDINGS — Backtest vs Live Environment Match

**Audit window:** 2026-05-24
**Auditor:** CC2 (skeptical, assume-fail posture)
**Target:** Verify EXP-3311 / EXP-3309 / EXP-3303b / EXP-3312 replicate backtest behavior in paper deploy.
**Verdict:** **🔴 NO-GO for Monday open without remediation.** Three of the four target experiments diverge materially from the backtest design that produced their headline metrics; one (EXP-3303b) has a regime gate that is **mathematically dead** in production.

---

## TL;DR — Critical Mismatches

| Experiment | Live wired? | Headline metric source | Divergence severity |
|---|---|---|---|
| **EXP-3311** | NFP filter active (`main.py:290-305`) | 4-stream portfolio + vol-target backtest | 🔴 Universe + filter scope + T-day handling |
| **EXP-3309** | Window filter active (`main.py:307-319`) | 8-stream LW vol-target backtest, literature cost coefficients | 🔴 Universe + sizing; 🟠 cost model unverified |
| **EXP-3303b** | Wired (`main.py:472-482`) but **gate never triggers** | Composite-stress threshold on VIX/VIX3M/VVIX/SKEW | 🔴 **Gate is dead** — label/threshold mismatch |
| **EXP-3312** | **Not deployed** | n/a — no `configs/paper_exp3312*.yaml` exists | 🔴 Not deployable as-is |

---

## CRITICAL Findings (block deployment)

### C-1. EXP-3303b regime gate is mathematically dead

**Live wiring:** `main.py:472-482` calls `shared.regime_gate.should_gate_for_regime(regime=…, ticker=…, config=…)` per-ticker. Gate is enabled in `configs/paper_exp3303b.yaml:116-123` with `gated_regimes: [transition, high_stress]` and `sensitive_tickers: [SPY, QQQ]`.

**Bug:** The regime detector that produces the `regime` argument is `compass/regime.py:349 ComboRegimeDetector`, which by construction emits only labels from `{'bull', 'bear', 'neutral'}` (compass/regime.py:399, plus the VIX>40 hard-bear at line 461). It **never** emits `'transition'` or `'high_stress'`.

```
regime ∈ {bull, bear, neutral}        ← ComboRegimeDetector output
gated_regimes = {transition, high_stress}  ← gate config
intersection = ∅                       ← gate never triggers
```

**Result:** EXP-3303b live runs the same logic as the champion paper baseline. The Sharpe 6.334 / CAGR 247.9% / Max DD 10.455% in the config header are **unachievable** because the underlying mechanism (composite-stress threshold gate on term_spread_z + vvix_z + skew_z, see `compass/exp3303_regime_transition_dd.py:131-163`) is **not** ported into live. The label-based shim is a placeholder.

**Evidence trail:**
- Backtest gate: continuous `composite_stress` from VIX/VIX3M/VVIX/SKEW with threshold `theta` (`compass/exp3303_regime_transition_dd.py:131-163`).
- Live gate: categorical label match against `regime in {transition, high_stress}` (`shared/regime_gate.py:75-84`).
- The composite-stress live calculator was committed (`8c1da70`) and immediately **reverted** (`a95f90a`). A re-attempt exists unmerged on `feature/composite-stress-gate` (commit `18ce230`) but is opt-in via `composite_stress_gate.enabled` (default OFF) and is not on `main`.

**Remediation options:**
- Merge `feature/composite-stress-gate` and enable `composite_stress_gate.enabled: true` in `configs/paper_exp3303b.yaml`, OR
- Mark EXP-3303b as `pending_dependency` and exclude from Monday deploy, OR
- Re-classify the experiment as "champion-equivalent" and update headline-metric expectations to champion's (Sharpe ~3-4, not 6.334).

---

### C-2. EXP-3312 is not deployed — no live config

**Audit brief expectation:** "Verify EXP-3312 has BOTH NFP filter AND pre-close execution active."

**Reality:** `configs/paper_exp3312*.yaml` does not exist. The registry has no `EXP-3312` entry. The backtest exists at `compass/exp3312_combined_event_exec.py` and expects Sharpe ≈ 6.05 / Max DD < 6.0% / CAGR ≈ 115%, but those numbers are only available by combining EXP-3311 + EXP-3309 effects, which requires a combined config.

**Remediation:** Either create `configs/paper_exp3312.yaml` (merge of 3309 + 3311), register it, and deploy it; or drop EXP-3312 from the Monday scope.

---

### C-3. EXP-3311 NFP gate covers only T-1 — backtest covers T-1 AND T

**Backtest semantics** (`compass/exp3311_event_gate.py:181-209`, `DEFAULT_WINDOW = (-1, 0)`):

```python
for off in range(lo, hi + 1):  # range(-1, 1) = [-1, 0]
    probe = target + timedelta(days=-off)
    # off=-1 → probe = target+1 (event tomorrow)
    # off=0  → probe = target   (event today)
```
→ Blackout fires when event is **tomorrow** OR **today**.

**Live semantics** (`shared/entry_gate.py:83-90`):
```python
tomorrow = today + timedelta(days=1)
if tomorrow in set(dates):
    return True, …
```
→ Blackout fires **only** when event is tomorrow. Live entries are **not** blocked on NFP day itself.

**Impact:** On an NFP Friday (e.g. 2026-06-05, 2026-07-02, 2026-08-07…), live enters new positions while the backtest does not. NFP Fridays are exactly the days the Hu-2014 / Kacperczyk-Pagnotta-2024 effective-spread widening applies.

**Remediation:** In `shared/entry_gate.py:83-90`, also check `if today in set(dates): return True, …`.

---

### C-4. EXP-3311 backtest blacks out 4 event types; live blacks out only NFP

**Backtest** (`compass/exp3311_event_gate.py:83`):
```python
EVENT_TYPES = ("fomc", "cpi", "nfp", "opex")
```
The `EventCalendar` aggregates FOMC + CPI + NFP + OpEx and is what produced the 4.984 Sharpe / 84.8% CAGR / 5.89% Max DD figures (`compass/reports/exp3311_event_gate.html:41-50`). Per-event sub-analysis is reported but the headline cell is the union.

**Live** (`configs/event_blacklist.json`):
```json
{ "nfp_dates": [7 dates through 2026-12-04] }
```
No FOMC, CPI, or OpEx coverage.

**Impact:** Live is exposed to FOMC announcement days, CPI release days, and monthly OpEx Fridays — all three categories of vol events that the backtest blackouts protected against. The actual Sharpe lift available with NFP-only is reported in `exp3311_event_gate.json` per-event cells (typically 25–40% of the full benefit, but the report shows it's the *combined* gate that earns the headline number).

**Remediation:**
- Either extend `configs/event_blacklist.json` to include `fomc_dates`, `cpi_dates`, `opex_dates` and extend `shared.entry_gate` to filter against all four, OR
- Restate expected live metrics to the NFP-only ablation cell (look up the "nfp only" row in `compass/reports/exp3311_event_gate.json`).

---

### C-5. Backtest universe ≠ Live universe (EXP-3311 / 3309 / 3303b all)

| Experiment | Backtest streams | Live tickers | Backtest sizing | Live sizing |
|---|---|---|---|---|
| EXP-3311 | xlf_cs + xli_cs + qqq_cs + exp1220 (4-stream v8a + VIX-ladder) | SPY only | LW vol-target via VIX ladder | flat 8.5% per trade, max 25 contracts |
| EXP-3309 | 8-stream v8a LW @ target_vol=0.18 | SPY only | LW risk-parity, 0.18 vol target | flat 8.5% per trade, max 25 contracts |
| EXP-3303b | qqq_cs + exp1220 + ... (multi-stream w/ composite-stress gate) | SPY only | LW risk-parity | flat 8.5% per trade, max 25 contracts |

The headline metrics in each paper config header (`paper_exp3311.yaml:9`, `paper_exp3309.yaml:9`, `paper_exp3303b.yaml:9`) are 4-/8-stream pooled-OOS portfolio statistics with VIX-ladder vol targeting. **They cannot be reproduced by a single-ticker SPY scanner with flat sizing.** Treating them as the live performance bar will trigger false drawdown alerts and false success claims.

**Remediation:** Update the "Expected" lines in each paper YAML header to either:
- "Single-stream ablation cell" metrics (need to be backed out from the JSON reports), or
- An explicit "treat as champion-baseline with added gate" disclaimer with realistic Sharpe in the 3–4 range.

---

## HIGH Findings (fix before Monday)

### H-1. NFP entry gate fails OPEN

`shared/entry_gate.py:42-51` — if `configs/event_blacklist.json` is missing or unparseable, the loader returns `[]` and logs `WARNING`. Downstream `should_skip_entry_for_nfp` then returns `(False, "")` — **trades are allowed**. This is fail-open. A misconfigured deploy, a corrupted file, or a path mismatch silently disables the filter while the experiment label still claims NFP protection.

**Remediation:** If `nfp_filter: true` in config but the file is missing/unparseable, raise (or hard-skip all entries) rather than fail open. Alternatively: require the loader to return at least 1 future-dated entry; otherwise treat it as a deploy bug.

### H-2. Execution-window TZ fallback is dangerous

`shared/execution_window.py:21-24, 58-62` — if `zoneinfo` import fails, the code falls back to **naive** `datetime.now()`, which uses the server's local time. On Railway (UTC), `15:30 UTC = 11:30 ET`, so the 15:30-16:00 ET window would silently align to 11:30-12:00 UTC instead. EXP-3309 would either gate every scan (never trade) or gate the wrong slot.

**Remediation:**
- Verify `zoneinfo` and `tzdata` are present in the deploy image (`python -c "from zoneinfo import ZoneInfo; ZoneInfo('America/New_York')"`).
- Replace the naive fallback with a `RuntimeError` or hard-skip — silent local-time substitution is worse than failing loudly.

### H-3. EXP-3309 has at most one entry opportunity per day

`shared/scheduler.py:49-55` schedule has slots at 9:15, 9:45, 10:00, 10:30, …, 15:00, **15:30**. The execution window is half-open `[15:30, 16:00)`. Only the **15:30 slot** is inside the window. If that slot fails (Polygon timeout, position monitor lock, watchdog restart in flight), EXP-3309 makes **zero trades that day**.

**Remediation:** Either (a) add 15:45 and 15:55 scheduler slots so EXP-3309 has retry chances, or (b) accept the single-slot brittleness explicitly and add a Telegram alert if the 15:30 EXP-3309 scan fails.

### H-4. Audit brief assumes `experiments/calendars/nfp_dates.csv` — does not exist

There is no `experiments/calendars/` directory at all. The only NFP source is `configs/event_blacklist.json` with **7 dates** (2026-06-05 through 2026-12-04). The file's own metadata: `"_verified": "2026-05-21 (instruction-file dates per Carlos approval; BLS WebFetch returned 403)"` — meaning the dates were taken from an internal source, not verified against BLS at refresh time. Next BLS quarterly re-verify is on a cron that may not be running.

**Remediation:**
- Verify the BLS empsit schedule cron is registered and last ran cleanly.
- Add a startup self-check: log a WARNING if `nfp_dates` has fewer than N future entries (e.g., N=3 trailing months).
- Extend the file with at least 2027-Q1 dates before they become operational.

### H-5. EXP-3309 cost model is literature-derived, not measured

Both `compass/exp3309_liquidity_weighted_entry.py:65` and `paper_exp3309.yaml:13` explicitly disclose: "per-window timing factors (spread×, slippage×, fill_rate) are documented coefficients from intraday liquidity literature, NOT measured from a minute-bar IronVault tape."

**Impact:** The 343 bps/yr cost saving and the Sharpe 5.879 / CAGR 265.7% headline are theoretical. Live fills through Alpaca have an unknown empirical spread/slippage delta vs midday baseline.

**Remediation:** Already flagged in the config — treat the first month as empirical validation, monitor measured fill mid vs midday baseline, and re-verify Sharpe lift before scaling capital.

---

## MEDIUM Findings

### M-1. EXP-3303b uses HARD SKIP, instruction file specified 50% size multiplier

Documented in `paper_exp3303b.yaml:11-21`. Carlos-approved deviation. Functional impact: when the gate fires it removes 100% of exposure instead of 50%. This is more conservative than the spec but changes the realized Sharpe meaningfully.

(Moot until C-1 is resolved — the gate doesn't fire at all today.)

### M-2. Position sizing identical across all three experiments — no vol target in live

`risk` block is the same byte-for-byte across `paper_exp3309.yaml`, `paper_exp3311.yaml`, `paper_exp3303b.yaml`:
- `max_risk_per_trade: 8.5`
- `sizing_mode: flat`
- `compound: false`
- `max_contracts: 25`
- `max_positions: 10`
- No `vol_target` / `target_vol` field anywhere.

The audit brief asks: *"Are vol targets identical (0.12 in both)?"* — **no live vol target is configured anywhere**. Backtests run vol targets of 0.18 (EXP-3309/EXP-2600) and ~0.12 in other ladders. The live deploy is **flat-risk per trade**, period.

This is consistent across the three experiments (so not a per-experiment divergence) but is a fundamental backtest/live divergence.

### M-3. composite-stress-gate branch is unmerged

`feature/composite-stress-gate` (commit `18ce230`) adds `shared/composite_stress_gate.py`, `compass/live_composite_stress.py`, 24 tests, and wires the gate in `main.py` after the label-based gate. **Opt-in**, default OFF. If this is the planned remediation for C-1, it must be merged AND the YAML must set `risk.composite_stress_gate.enabled: true` AND the relevant `theta`, `tickers`, and capital-rebalance params.

### M-4. Backtester references in YAMLs hardcode unverified slippage/commission

All three paper configs (`backtest:` block):
- `commission_per_contract: 0.65`
- `slippage: 0.05`
- `exit_slippage: 0.10`

These are the same numbers across all three regardless of underlying — fine for SPY but worth confirming they match the actual Alpaca paper fill behavior. Alpaca paper does not model option bid-ask spreads accurately; live fills will diverge from these assumptions.

---

## LOW Findings

### L-1. Three configs use `data/options_cache` but `provider: polygon`

Polygon is the data provider; the local cache is informational only. Verify the cache is being warmed by the scheduler (should be automatic via `shared.data_cache`).

### L-2. No GO/NO-GO smoke test for filters

No script that, given a date, prints "EXP-3311 would gate today: yes/no, reason …". Recommend adding a one-liner per experiment for the pre-flight checklist.

---

## Verification Checklist (Pre-Monday)

Run these before market open:

```bash
# 1. NFP blacklist freshness
python3 -c "import json; d=json.load(open('configs/event_blacklist.json'))['nfp_dates']; \
  from datetime import date; future=[x for x in d if x > date.today().isoformat()]; \
  print('Future NFP dates:', len(future), future[:3]); assert len(future) >= 3"

# 2. Verify entry gate fires on the day before next NFP
python3 -c "from datetime import date, timedelta; from shared.entry_gate import should_skip_entry_for_nfp; \
  d = date(2026, 6, 4); print('Day-before-NFP gate test:', should_skip_entry_for_nfp(today=d))"

# 3. Verify execution window resolves to ET
python3 -c "from zoneinfo import ZoneInfo; from datetime import datetime; \
  print('Now in ET:', datetime.now(ZoneInfo('America/New_York')))"

# 4. Verify EXP-3303b regime gate config but NOTE — see C-1, this is a no-op
python3 -c "from shared.regime_gate import should_gate_for_regime; \
  print('SPY+transition →', should_gate_for_regime('transition', 'SPY', config={'risk':{'regime_gate':{'enabled':True,'gated_regimes':['transition','high_stress'],'sensitive_tickers':['SPY']}})); \
  print('SPY+bear →',       should_gate_for_regime('bear', 'SPY', config={'risk':{'regime_gate':{'enabled':True,'gated_regimes':['transition','high_stress'],'sensitive_tickers':['SPY']}}))"
# Expected output: (True, …) and (False, '') — the second confirms the gate never fires
# under the live ComboRegimeDetector, which emits 'bear' not 'transition'.

# 5. Confirm EXP-3312 has NO live config
ls configs/paper_exp3312*.yaml 2>&1   # must say "No such file"
```

---

## GO / NO-GO Recommendation

**🔴 NO-GO for Monday 2026-05-26 market open in current configuration**, for these reasons (in priority order):

1. **EXP-3303b ships a dead gate** (C-1). Either merge `feature/composite-stress-gate` with `composite_stress_gate.enabled: true` before Monday, OR pull EXP-3303b from the Monday deploy and re-classify as champion-baseline.
2. **EXP-3312 is undeployed** (C-2). Either ship `configs/paper_exp3312.yaml` or drop from scope.
3. **EXP-3311 NFP gate misses event-day** (C-3) — easy 2-line fix in `shared/entry_gate.py`. Block until fixed.
4. **Headline metrics in YAML headers are misleading** (C-5). Update or drop them; they will cause false alarms or false success when paper trading data accumulates.

**Conditional GO** is possible if:
- C-3 is fixed (entry_gate also checks `today in dates`).
- EXP-3303b is either fixed (composite-stress merged + enabled) or pulled.
- EXP-3312 is dropped from Monday scope.
- YAML "Expected" headers are corrected or disclaimed.
- C-4 (event-type scope mismatch) is accepted as a known divergence with documented expected-Sharpe restatement.

The H-1 (fail-open NFP gate) and H-2 (naive TZ fallback) issues should be fixed in the same window. They're 3-line changes each.

---

## Notes for Other Sessions

- **CC1 (execution path):** EXP-3309 makes at most ONE entry attempt per day at 15:30 ET. Order-routing failures at 15:30 = zero entries. Confirm Alpaca retry logic for the 15:30 slot specifically.
- **CC3 (data pipeline):** EXP-3303b composite-stress gate (if/when merged) needs VVIX and SKEW from Polygon. Verify these tickers are in the data pipeline; they were Yahoo-only in the backtest fetch (`compass/exp3303_regime_transition_dd.py:115`).
- **CC5 (risk mgmt):** No live vol target — all three experiments use `sizing_mode: flat, max_risk_per_trade: 8.5`. This is identical across experiments, so no per-experiment risk-bound divergence, but the *absence* of a vol target means the experiments compound differently than their backtests.

---

**Audit complete: 2026-05-24**
