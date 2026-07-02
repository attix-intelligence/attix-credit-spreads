# EXP-3310 — V8A Re-Backtest with Leg-Collision Guard

**Date:** 2026-07-02
**Fix under test:** commit `2ad75fd` — *fix(backtest): enforce broker per-symbol netting (leg-collision guard)*
**Handoff:** Charles, 2026-06-30 (Option B — enforce broker per-symbol netting)
**Owner:** Maximus

---

## TL;DR

The leg-collision guard was re-backtested against the canonical V8A run (SPY,
2020-01-02 → 2025-12-31). The guard is **working as designed**:

- ✅ **Zero simultaneous leg-collisions** in the new trade log (was **31** pre-fix).
- ✅ **Modest drop in trade count**: 1196 → 1167 (**−29 trades, −2.4 %**) — the impossible trades being removed, not a regression.
- ⚠️ **Total return did *not* drop — it rose**: +2.52 % → +4.94 %. The handoff expected a modest return *drop*; in this data window the eliminated broker-impossible trades were, in aggregate, **net-negative**, so removing them *improved* the result. Still consistent with "the bug being removed, not a regression."
- ✅ **2,573 `position_conflict` skips** logged by the guard over the run.

---

## 1. What was run

| Item | Value |
|---|---|
| Engine | `backtest/backtester.py` → `Backtester.run_backtest` |
| Config (canonical V8A) | `configs/paper_expv8a.yaml` (regime-adaptive champion; source `configs/champion.json`) |
| Ticker | SPY |
| Date range | 2020-01-02 → 2025-12-31 |
| Data mode | **Fully offline** from `data/options_cache.db` (`HistoricalOptionsData(offline_mode=True)`) — real Polygon option marks, **0 network calls, 0 synthetic pricing** (Rule Zero compliant) |
| Starting capital | $100,000 |
| Runner | `scripts/exp3310_collision_rebacktest.py` |
| Verifier | `scripts/exp3310_verify_collisions.py` |

**Old vs New methodology (controlled A/B).** Both runs use the *same code, same
config, same data, same date range*. The only difference is the guard:

- **NEW** = HEAD (`2ad75fd` + observability patch below), guard **active**.
- **OLD** = the guard neutralized via `EXP3310_DISABLE_GUARD=1`, which makes
  `position_leg_collision()` always return `False`. That forces the new
  `if _leg_collision(...)` branch to never be taken, so control falls through to
  the *identical* `elif` that was the pre-fix code path — provably equivalent to
  `2ad75fd^` for the scan loop, with everything else held byte-identical.

This isolates the guard's effect exactly, rather than diffing against an
unrelated historical run.

---

## 2. Results — Old vs New

| Metric | OLD (pre-fix, guard off) | NEW (guard on) | Δ |
|---|---:|---:|---:|
| **Trade count** | 1,196 | 1,167 | **−29 (−2.4 %)** |
| **Total return** | +2.52 % | +4.94 % | **+2.42 pp** |
| **Sharpe** | 0.09 | 0.12 | +0.03 |
| **Max drawdown** | −24.46 % | −24.16 % | +0.30 pp (shallower) |
| Win rate | 71.57 % | 71.64 % | +0.07 pp |
| Total P&L | $5,458.20 | $7,808.30 | +$2,350.10 |
| Ending capital | $102,518.90 | $104,943.10 | +$2,424.20 |
| Bull-put trades | 528 | 509 | −19 |
| Bear-call trades | 0 | 0 | 0 |
| Iron-condor trades | 668 | 658 | −10 |

Interpretation:
- **Trade count** fell modestly (−2.4 %), exactly the expected "impossible trades
  removed" signature.
- **Return** rose because the ~29 removed trades were net losers in aggregate over
  2020-2025. A real broker would have rejected these orders, so the pre-fix
  backtest was booking P&L (here, net-negative P&L) on trades that could never
  have executed. The correction is directionally the opposite of the handoff's
  guess on return, but it is **not a regression** — it removes fictitious fills.
- Bear-call trades are 0 in both runs: over this window the combo regime never
  selected the bearish direction (SPY spent the window predominantly in
  bull/neutral regime; see caveat §5 on VIX data).

---

## 3. Zero-collision verification (acceptance criterion 3)

**Definition.** A collision = the SHORT strike of one open trade equals the LONG
strike of another *simultaneously-held* trade on the same **expiration + option
type** — the exact per-OCC-symbol order a broker always rejects.

**"Simultaneously held" semantics.** The daily loop runs `_manage_positions`
(closes / expirations / stops) at the **start** of each day, *before* the entry
scan. A position exiting on day X is therefore out of `open_positions` when new
entries are scanned that day — its OCC symbols are freed. Two trades are counted
as simultaneously held only when their `[entry, exit)` intervals **strictly**
overlap (a pure same-day handoff, `a.exit == b.entry`, is *not* a collision, and
the broker permits it). This matches exactly the set of legs the guard sees in
`_occupied_legs` at entry time.

Each trade is expanded into its per-OCC legs (bull-put → 2 P legs; bear-call → 2
C legs; iron-condor → 2 P + 2 C legs) and every strictly-overlapping same-expiry
pair is checked.

| Trade log | Iron condors (call legs present) | **Collision count** | Verdict |
|---|---:|---:|---|
| **NEW (guard on)** | 658 / 658 | **0** | ✅ **ZERO — verified** |
| OLD (guard off) | 668 / 668 | 31 | ❌ bug present pre-fix |

The verifier is not vacuous: a self-test (Charles's reported Mon 744/756 →
Tue 756/768 same-expiry bear-call case) is correctly flagged as 1 collision, and
the same 756/768 spread placed on a *different* expiration is correctly **not**
flagged.

Representative OLD (pre-fix) collisions now eliminated:

```
exp 2020-03-20  P290.0 : trade#20 held 2020-02-28..03-09  vs  trade#21 held 2020-03-02..03-09
exp 2020-03-20  P295.0 : trade#22 held 2020-03-03..03-09  vs  trade#23 held 2020-03-04..03-09
exp 2020-04-03  P235.0 : trade#30 held 2020-03-17..03-23  vs  trade#32 held 2020-03-18..03-26
exp 2023-06-30  C452.0 : trade#679(IC) held 2023-06-09..06-15  vs  trade#686(IC) held 2023-06-15..06-30
```

> **Observability note.** `_record_close` previously copied only the put wing of
> an iron condor into the emitted trade record, so exported IC rows lacked their
> call strikes and a leg-level audit could not see the IC call side. A minimal,
> **non-behavioral** patch adds `call_short_strike` / `call_long_strike` to the
> trade record (`None` for single spreads). All 658/668 ICs in both logs now
> carry their call legs, so the zero-collision scan is leg-complete. This does
> not affect P&L, sizing, or the guard.

---

## 4. `position_conflict` skips (acceptance criterion 4)

Skips are counted from the guard's `position_conflict` DEBUG log during the NEW run:

| Entry type | Skips |
|---|---:|
| bull_put | 1,660 |
| bear_call | 0 |
| iron_condor | 913 |
| **Total** | **2,573** |

These are **scan-level** rejections (each intraday scan tick where a candidate
would collide, across all trading days), which is why the count (2,573) is much
larger than the 31 collisions that actually materialized as opened-trade pairs in
the pre-fix run — most colliding candidates recur across the 14 intraday scans ×
multiple days until price drifts, and many are additionally gated by
`max_positions` / per-key dedup even without the guard. On each skip the guard
refunds commission and opens no trade, matching live broker behavior.

---

## 5. Caveats

1. **VIX / index data after 2023-02-13.** The Polygon *indices* entitlement is not
   authorized in this environment (HTTP 403 for `I:VIX`/`I:VIX3M`), and the local
   `historical_indices.sqlite` only covers through 2023-02-13. For ~2023-2025 the
   combo-regime and IV-rank sizing fall back to their defaults (iv_rank≈25,
   vix≈20). This shifts *absolute* numbers versus a fully-VIX-fed run, but it is
   applied **identically to OLD and NEW**, so the A/B delta (the deliverable here)
   is unaffected.
2. **Risk cap.** `configs/paper_expv8a.yaml` sets `max_risk_per_trade: 33.15`,
   above the backtester's hard ceiling of 25 %, so it is capped to 25 % (with a
   warning) in both runs — again identical across OLD/NEW.
3. The canonical multi-year V8A run is driven by a direct-`Backtester` script (as
   the champion validation scripts do), not `python main.py backtest` (which
   computes a trailing-`--days` window from *today* and runs cache-first with
   Polygon-on-miss). See `scripts/exp3310_collision_rebacktest.py`.

---

## 6. Acceptance criteria — status

| # | Criterion | Result |
|---|---|---|
| 1 | Run the full V8A backtest as the canonical config | ✅ SPY 2020-01-02→2025-12-31, `configs/paper_expv8a.yaml`, offline real data |
| 2 | Expect a modest drop in trade count and total return | ⚠️ Trade count −2.4 % (as expected); **total return rose** +2.42 pp (removed trades were net-negative) — not a regression |
| 3 | Verify ZERO simultaneous short==long leg collisions | ✅ **0** (was 31 pre-fix) |
| 4 | Log & count `position_conflict` skips | ✅ **2,573** (bull_put 1,660 / IC 913 / bear_call 0) |

---

## 7. Artifacts

- `output/exp3310_verify_new.json` — NEW collision scan (count 0) — *committed*
- `output/exp3310_verify_old.json` — OLD collision scan (count 31, with samples) — *committed*
- `scripts/exp3310_collision_rebacktest.py` — reproducible offline runner — *committed*
- `scripts/exp3310_verify_collisions.py` — leg-level collision verifier (+ self-test) — *committed*
- `output/exp3310_new_results.json` / `output/exp3310_old_results.json` — full metrics + trade logs
  (~680 KB each; `output/` is gitignored, so these are **not committed** — regenerate via the commands below)

**Reproduce:**
```bash
# NEW (guard on)
.venv/bin/python scripts/exp3310_collision_rebacktest.py new output/exp3310_new_results.json
# OLD (guard off, pre-fix equivalent)
EXP3310_DISABLE_GUARD=1 .venv/bin/python scripts/exp3310_collision_rebacktest.py old output/exp3310_old_results.json
# Verify
.venv/bin/python scripts/exp3310_verify_collisions.py output/exp3310_new_results.json
```
