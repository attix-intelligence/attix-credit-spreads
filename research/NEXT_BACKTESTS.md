# NEXT BACKTESTS — after the Tradier decision (EXP-800 live, V8A gated)

**Date:** 2026-07-03 · **Input:** `reports/tradier_strategy_decision_INPUT.html` (2026-07-03 04:34 UTC)
**Scope:** backtest design only. No live accounts touched, no scanners run. Every claim below is grounded in a file in this repo (cited inline).
**New IDs:** highest existing experiment is `EXP-3505` (`experiments/EXP-3505-spx-1to3dte/`); registry.json tops out at EXP-3311. This doc claims **EXP-3510 – EXP-3570**.

---

## 0. What the repo actually says (grounding facts)

These facts drive the prioritization. Verify paths yourself; several contradict the folklore in the decision doc.

**F1 — There are two disjoint "V8A backtests" that disagree by ~50× on Sharpe.**
- The **compass cube** backtests (EXP-2730/EXP-2850: `compass/archive/exp2730_wf_robustness_v8a_net.py`, `compass/exp2850_v8a_with_vix_ladder.py`, results in `compass/reports/exp2730_*.json`, `exp2850_*.json`) produce the headline **net Sharpe 6.16 / 6.39, DD 7.1% / 5.1%**. They run on 8 columns of *pre-computed daily return proxies* (IronVault spread proxies + Yahoo, via `compass/exp2450_sparse_combined_honest.py`), with **no order simulation, no fills, no exits, a flat 890.3 bps/yr cost drag, and a 20× vol-target scale cap** (live is hard-capped at 3× — `compass/live/vrp_risk_parity.py:86`, `docs/V8A_VRP_RECON_RISK_PARITY.md`).
- The **real-engine replay** (EXP-3310, `reports/EXP-3310_collision_guard_rebacktest.md`): `backtest/backtester.py` + `configs/paper_expv8a.yaml` on **real Polygon option marks**, offline, SPY 2020-01-02→2025-12-31 → **Sharpe 0.12, +4.94% total over 6 years, MaxDD −24.2%**.
- Live paper: **Sharpe −1.20** (decision doc). The live number is far closer to the real-engine replay than to the cube. Most of the "live-vs-backtest gap" is **abstraction gap, not regime gap**.

**F2 — Live V8A had no exit mechanism at all during June.**
- `vrp_position_monitor` (PR-H: PT 50%, SL 2×, roll 7 DTE, crisis-exit VIX>45) shipped **`enabled: false` in BOTH live configs** — `configs/paper_expv8a.yaml:292`, `configs/paper_expv8a_ibkr.yaml:259`.
- The scheduler VIX circuit breaker (`scheduler/jobs.py:292-342`, block ≥35 / "EXIT ALL" ≥45) is **alert-only** — it writes JSON and sends Telegram; it closes nothing.
- The live VIX-ladder adapter (`Cc4VixExposure`, `compass/live/vrp_runner.py:81-106`) reads only `entry_gate`/`sizing_multiplier` and **ignores `exit_gate`**.
- Net: every live VIX/regime control gated **new** entries; nothing could de-risk **open** short spreads as vol spiked. This matches the decision doc's own diagnosis ("breakers stop new entries, not MTM losses").

**F3 — The backtest ladder is physically impossible live.**
In EXP-2850 the ladder **multiplies realized daily returns** (`gross × ladder.apply(vix)` — instant de-levering of open exposure). Live it can only scale **new-entry sizing** (`docs/V8A_VRP_RECON_VIX_LADDER.md` §5.2). The DD-5.1% claim leans on semantics that no broker can deliver.

**F4 — Post-Feb-2023 VIX in the offline replay is fiction.**
`data/historical_indices.sqlite` covers **2019-06-03 → 2023-02-13** only; Polygon indices returns 403 here. The canonical V8A replay fell back to **vix≈20 / iv_rank≈25 for ~2023-2025** (EXP-3310 report §5). Every VIX-conditioned filter is effectively untested in the real-data engine after Feb 2023. Offline daily VIX to **2026-04-24** does exist in `deploy/macro-api/data/macro_state.db` (`macro_score.vix`).

**F5 — Data coverage (from `data/options_cache.db`, 978 MB, real Polygon marks):**
- SPY/XLF/XLI/XLE/XLK/SOXX daily option bars: **2020-01-02 → 2026-04-02** (SPY deepest, 4.4M bars). QQQ/GLD/TLT stop **2025-12-19** (QQQ stale since May 2023). Intraday 5-min: → 2026-02-24.
- **Zero May/June/July-2026 bars.** June-2026-expiry contracts exist in `option_contracts` metadata (max expiration 2026-06-30) but have no prices. CBOE archive (`data/cboe_complete/`): SPY/SPX/QQQ 0-30 DTE, 2021-01 → 2025-12. Athena mirror (`reports/athena_inventory.json`) stops 2026-05-26.
- A June-2026 replay therefore **requires a Polygon backfill** (Starter tier, ~5 req/s, contract-listing endpoint broken — enumerate from `option_contracts`; see `reports/data_backfill_status.html`).

**F6 — EXP-800 has no backtest and its breaker doesn't do what its docs say.**
- Registry `EXP-800.backtest_config: null`; sentinel lists it "**GRANDFATHERED — no backtest config. Provide within 30 days**" (`output/sentinel_runtime_monitoring_proposal.html`). Its +136.2%/−13.1% "lineage" is the EXP-305 Safe-Kelly study (`scripts/safe_kelly_backtest.py`, `output/safe_kelly_report.md`) — **ML-Kelly scaling on multi-ticker COMPASS**, a different mechanism from EXP-800's fixed 9/7/4 regime fractions on SPY.
- Deployed breaker = **−8/−10/−12 tiers** (`configs/paper_exp800.yaml:97-104`); the studied "4/7/9" tiers were never deployed (the registry name "Safe Kelly 4/7/9" refers to DD thresholds, NOT the 9/7/4 regime fractions — colliding digits, different axes).
- **Tier-3 "flatten open positions" is documented but NOT implemented** — `scripts/exp800_safe_kelly_scanner.py:697-704` only skips new entries. Hence the −31.1% June MTM drawdown with the breaker "working".
- The June trade-level ground truth (`data/exp800/pilotai_exp800.db`) is **not in this checkout** (lives on Railway); `executor_live.db` is empty. The −31.1% cannot be reconstructed locally.

**F7 — Live VRP params ≠ advertised params.** The decision doc's "delta-band 0.08–0.18, dte 15–25" describes the *retired champion* block that the YAML itself marks dead. The engine actually trades **0.20Δ short (0.15–0.25 window), $5 width, ~30 DTE in [25,50]**, hardcoded in `compass/live/vrp_streams.py:143-150`, with a hardcoded `vix_max_entry=40`.

**F8 — Long-vol hedges already failed here.** EXP-3409 (QQQ straddle hedge on ICs): **−3.7%**, hedge cost $5.8K vs ~zero IC profit (`experiments/EXP-3409-vol-hedge/results/`). Real hedge cost measured at **4.36%/yr** (`REGISTRY.md`). EXP-3503 (VIX-adaptive sizing, done naively): **−107%** (`experiments/EXP-3503-spx-vix-adaptive/results/metrics.json`). New experiments should favor **exit gates and event filters**, not always-on long-vol.

**F9 — EXP-3311 (champion + day-before-NFP entry gate, `configs/paper_exp3311.yaml`, `shared/entry_gate.py`, `configs/event_blacklist.json`) beat EXP-800 in June** (decision doc). NFP dates incl. 2026-06-05 are in the blacklist; FOMC dates exist in `data/fomc/`. Cheap, proven-live-adjacent filter to cross-pollinate.

---

## 1. Prerequisite (do first — everything below depends on it)

### EXP-3510 — VIX/indices backfill + regime-fidelity A/B on the canonical replay
**Priority: P0 (infrastructure validity). Effort: ~0.5 day.**
- **Hypothesis:** with real VIX/VIX3M wired in for 2023-02-14→2026-04, the real-engine V8A replay's trade selection, regime labels, and IV-rank sizing change materially versus the current silent fallback (vix≈20/iv_rank≈25) — and every VIX-conditioned experiment below becomes trustworthy.
- **Data/config:** extend `data/historical_indices.sqlite` from `deploy/macro-api/data/macro_state.db` (VIX daily 2020-01-03→2026-04-24; add VIX3M via one-time Yahoo bootstrap, same method as `MIGRATION_D4_BACKTEST_TASK.md` used pre-2023). Re-run `scripts/exp3310_collision_rebacktest.py` (guard on) unchanged.
- **Pass/fail:** PASS = fallback-days count = 0 for 2020-2025 in the run log, and a published delta table (ΔSharpe, ΔMaxDD, Δtrade-count, Δregime-distribution) vs the EXP-3310 NEW run. There is no "fail" on the delta itself — the deliverable is the corrected baseline. FAIL only if VIX3M cannot be sourced (then document which signals stay degraded).

---

## 2. The experiments (prioritized)

### EXP-3520 — "As-deployed V8A" parity backtest: exits-off vs exits-on
**Priority: P0. Question: why did short-vol blow up in June — and how much of the gap is the missing exit layer? Effort: ~1-2 days.**
- **Hypothesis:** the dominant cause of V8A's live failure was structural, not signal decay: with `vrp_position_monitor` off (F2), open spreads ride MTM losses through vol spikes. Concretely: disabling managed exits in the real-data engine at least **doubles MaxDD** in the five worst historical VIX-spike windows and flips their window Sharpe negative, while exits-on stays within the cube's advertised DD regime.
- **Method (3 arms, controlled A/B like EXP-3310):** `backtest/backtester.py`, offline `data/options_cache.db`, per live-tradeable stream — SPY, XLF, XLI 2020-01→2026-04-02 (QQQ →2025-12-19), using the **actual live engine params from F7** (0.20Δ short, $5 width, ~30 DTE), not the dead champion block:
  - **A (as-designed):** PR-H exits on — PT 50%, SL 2.0×, roll at 7 DTE, crisis-exit VIX>45 (`vrp_position_monitor` params in `configs/paper_expv8a.yaml:291-297`).
  - **B (as-deployed):** all exits off, hold to expiry; entry-side controls only (ladder multiplier + entry block 35 + `vix_max_entry` 40).
  - **C:** B + Alpaca-1x aggregate cap `max_aggregate_max_loss_pct 0.30` (`vrp_risk` block) to isolate what the caps bought.
- **Data needed:** EXP-3510's VIX backfill (crisis-exit and ladder need real VIX post-2023).
- **Pass/fail:** mechanism CONFIRMED if MaxDD(B) ≥ 2× MaxDD(A) and window-Sharpe(B) < 0 in ≥3 of the 5 worst 20-day VIX-spike windows of 2020-2025 (Feb-Mar 2020, Sep 2020, Jan/Jun/Sep-Oct 2022 — pick by realized VIX). Deliverable either way: a **gap-attribution table** (exits, entry gates, caps) that becomes the checklist for V8A's re-arm gates. If B ≈ A, the June failure is signal/regime, not structure — which re-prioritizes EXP-3570.

### EXP-3530 — VIX-ladder semantics honesty test (return-multiplier vs entry-time-only)
**Priority: P1. Question: does EXP-2850's DD 5.1% survive physically-possible ladder semantics? Effort: ~0.5-1 day (≈50-line change to one script).**
- **Hypothesis:** EXP-2850's DD reduction depends on instantly de-levering *open* exposure (F3). Re-run with the multiplier **frozen at each position's entry** (exposure at day *t* = capital-weighted entry-time multipliers of positions still open, holding period ~10-30 days) and MaxDD at least **doubles** (5.1% → >10%), erasing most of the ladder's advertised benefit.
- **Method:** fork `compass/exp2850_v8a_with_vix_ladder.py`; replace `gross × ladder.apply(vix_series)` with a position-lifetime convolution (approximate each stream's holding period from its trade cadence in the EXP-2450 cube; sensitivity-check at 10/20/30-day holds). Same cube, same 890 bps drag, same folds — only the ladder application changes.
- **Data:** existing cube (`compass/exp2450_sparse_combined_honest.py` + `compass/cache/exp2250_qqq_trades.pkl` — present) + Yahoo ^VIX (already how exp2850 sources it).
- **Pass/fail:** if entry-only MaxDD ≤ 8% (the G4 gate, `MASTERPLAN.md:157`) → ladder survives honest semantics; keep it as the primary sizing control. If MaxDD > 12% → G4 was never achievable with entry-side controls alone, V8A's re-arm MUST include an exit-side mechanism (whatever EXP-3540 selects), and the MASTERPLAN paper gates need re-basing.

### EXP-3540 — Crisis-exit / event-gate grid over historical vol spikes (the fix search)
**Priority: P1. Question: which cheap, live-implementable rule would have prevented a June-type blow-up? Effort: ~2-3 days.**
- **Hypothesis:** an **exit-side rule** (force-close at VIX ≥ 35-40 — i.e., actually enabling PR-H with a lower `crisis_vix`) plus an **event gate** (day-before NFP/FOMC entry block, F9) cuts worst-20-day-window MaxDD by ≥ 50% at ≤ 25% full-period CAGR cost — beating long-vol hedges, which already failed here (F8).
- **Method:** real-data engine (as in EXP-3520 arm A), SPY+XLF+XLI 2020-01→2026-04, grid:
  - `crisis_vix` ∈ {30, 35, 40, 45, off} (exit-all open spreads; entry re-allowed per ladder)
  - entry-block VIX ∈ {25, 30, 35}
  - `stop_loss_mult` ∈ {1.25, 2.0}
  - event gate ∈ {off, NFP, NFP+FOMC} (`shared/entry_gate.py` + `configs/event_blacklist.json` + FOMC dates from `data/fomc/`)
  - = 90 cells; score on full-period Calmar AND the 5 spike windows.
- **Guard against overfitting:** winner must be selected on 2020-2023, then validated untouched on 2024-2026-04 via `validation/walk_forward.py` conventions; report the full grid surface (no cherry-picked cell).
- **Pass/fail:** SHIP a cell iff (spike-window MaxDD ≤ 10%) AND (CAGR ≥ 70% of no-filter baseline) AND (rank stability: same cell in top-5 on both halves of the sample). If no cell passes, the honest conclusion is that 0.20Δ short-vol cannot be made June-proof by gating alone → V8A stays gated until the vol-target itself drops.

### EXP-3550 — EXP-800 standalone backtest + drawdown-robustness variants
**Priority: P1. Question: is EXP-800's −31% June DD reproducible/structural, and what config caps it? Also clears the sentinel "GRANDFATHERED — provide within 30 days" debt (F6). Effort: ~2-3 days.**
- **Hypothesis:** as-deployed EXP-800 (9/7/4 regime fractions of *current equity*, −8/−10/−12 entries-only breaker, caps 30 contracts / 17% per trade) produces **25-40% daily-close MTM drawdowns** in historical spike windows — i.e., June was the expected behavior of this config, not bad luck — and at least one variant caps MaxDD ≤ 15% while keeping ≥ 60% of CAGR.
- **Method:** `backtest/backtester.py` with EXP-400 champion signals (params from `configs/paper_exp800.yaml` strategy block: dte 15-25, 2% OTM, $12 width, PT 55%, SL 1.25×, combo regime) + a Kelly-sizing layer ported from the tier state machine in `scripts/exp800_safe_kelly_scanner.py:457-541` (the backtest twin it never had). SPY 2020-01→**2026-04-02** (this window includes live-overlap Q1-2026 — calibrate the model against EXP-800's known Apr +21.2% paper month as a sanity anchor). Variants:
  - **(a)** as-deployed baseline (entries-halt-only breaker);
  - **(b)** Tier-3 **actually flattens** (implement what `paper_exp800.yaml:16` claims);
  - **(c)** (b) + tighter tiers 4/7/9 from the EXP-305 study (`output/safe_kelly_report.md` §4 — studied, never deployed);
  - **(d)** Kelly fraction × VIX-ladder multiplier (`compass/vix_ladder.py`, EXP-2820 breakpoints);
  - **(e)** (b) + NFP gate (F9).
- **Pass/fail:** model VALIDATED if baseline spike-window daily-close DD lands in 20-40% (bracketing June's −31.1%) — if it shows <15%, the backtest is missing the June mechanism and must not be trusted for sizing decisions. SHIP a variant iff MaxDD ≤ 15%, CAGR ≥ 60% of baseline, and monthly win-rate not degraded by >10pp. The winning variant defines the **live Tradier cap review** (decision doc caveat #1) — as a config proposal only, no live change from this experiment.

### EXP-3560 — Cross-pollination two-arm: ladder→Kelly and Kelly-breaker→VRP
**Priority: P2 (after 3540/3550 baselines exist). Effort: ~1-2 days on top of their harnesses.**
- **Arm A (V8A → EXP-800):** already covered as EXP-3550 variants (d)/(e) — promote the better of the two to a named result: *"EXP-800 with V8A's vol-awareness."* Pass: worst-20-day DD reduced ≥ 40% at ≤ 20% CAGR cost vs EXP-3550 baseline.
- **Arm B (EXP-800 → V8A):** VRP streams (EXP-3520 arm-A harness) + EXP-800-style **3-tier portfolio-equity breaker with true flatten** (−8% halve / −10% floor / −12% flatten+halt) as an *alternative* to the VIX-keyed crisis exit — equity-based triggers fire on any regime, not only VIX-labelled ones (June ranking flattered specific mechanisms; decision doc caveat #2).
- **Pass/fail (arm B):** adopt over EXP-3540's winner iff it dominates on Calmar in both sample halves AND keeps spike-window MaxDD ≤ 12% (tier-3 level + slippage allowance). Deliverable: one recommended risk architecture for the eventual V8A re-arm, expressed as a `vrp_position_monitor`/breaker config diff.

### EXP-3570 — June-2026 replay (gated on data backfill)
**Priority: P2 stretch — the only experiment that directly answers "would X have prevented June" on June itself. Effort: ~1 day backfill + ~1 day replay, network required.**
- **Prerequisite (network, explicit and billable):** backfill 2026-05-01→2026-07-03 daily option bars for SPY/XLF/XLI (+QQQ best-effort) into `data/options_cache.db` via Polygon Starter (~5 req/s; enumerate contracts from `option_contracts`, which already holds June-2026 expiries — F5), plus June VIX/VIX3M/SPY via Polygon/Yahoo. Extend, don't mutate: new rows only, same schema.
- **Hypothesis:** (1) replaying **as-deployed** V8A (EXP-3520 arm B config) and EXP-800 (EXP-3550 baseline) through June reproduces the reported paper DDs (−21.9% V8A Alpaca, −31.1% EXP-800) within ±5pp — validating the offline engine as a postmortem tool despite having no local fill ground truth (F6); (2) the EXP-3540 winning cell holds V8A's June MaxDD ≤ 8% (the G4 gate) in counterfactual replay.
- **Pass/fail:** VALIDATED if both replay DDs land within ±5pp of the decision doc's numbers (if not, document the residual as broker/fill effects — that residual is itself the measured "execution gap"). The counterfactual PASS (≤8% DD) is the single strongest piece of evidence to attach to V8A's re-arm proposal; FAIL means even the best historical-fit filter didn't generalize to June, and V8A's 4-clean-weeks gate should stay strictly paper-forward.

---

## 3. Explicitly not proposed
- **Long-vol / straddle hedge overlays** — already tested and net-negative here (EXP-3409 −3.7%; real hedge drag 4.36%/yr; `REGISTRY.md`, F8). Revisit only if EXP-3540 finds no passing cell.
- **More compass-cube variants** — the cube family (Sharpe 6.x) is the abstraction that failed contact with reality (F1). EXP-3530 is the one exception because it tests the cube *against itself* to invalidate a specific claim. All new decision-grade numbers must come from `backtest/backtester.py` on `data/options_cache.db`.
- **Anything touching live account 6YA42569 or paper workers** — out of scope by task definition; every experiment above is offline (EXP-3570's backfill is read-only market data, no orders).

## 4. Suggested order & dependencies
```
EXP-3510 (VIX backfill)          ── unblocks ─┬─ EXP-3520 (exit parity)   ─┐
                                              ├─ EXP-3540 (fix grid)       ├─ EXP-3560 (cross-pollination)
EXP-3530 (ladder honesty, indep.)             └─ EXP-3550 (EXP-800 bt)    ─┘
EXP-3570 (June replay) — after 3520/3540/3550 define the configs to replay; needs network backfill
```
Registry hygiene: register each as `EXP-35xx` (status `registered`) in `experiments/registry.json` before running, per `RUNBOOK_EXPERIMENT_LAUNCH.md`; note the pre-existing ID collision pattern (two different EXP-3310s — `reports/EXP-3310_collision_guard_rebacktest.md` vs `compass/reports/exp3310_term_structure_order_flow.json`) and avoid reusing numbers.
