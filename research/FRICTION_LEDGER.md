# EXP-P0A — Friction Budget Ledger

**Date:** 2026-07-12 · **Author:** cc1 · **Status:** measurement complete — no strategy backtest run, no data past 2024-12-31 touched.
**Runner:** `experiments/honest-fills-fleet/friction_ledger.py` → `results/friction_ledger.json` (full 144-row table; this document aggregates).
**Method:** weekly Friday grid 2020-01 → 2024-12; per (structure, underlier, class): real premium distributions from `options_cache.db` closes (spot inferred per date/expiry via put-call parity — no external feed); friction = commissions ($0.65/contract/side, round trip) + the engine's slippage model ($0.05 entry + $0.10 exit per spread side × 100). **Every future prereg must cite this table** (program rule). Coverage floor: classes with < 20 samples dropped.

## Headline findings

1. **The engine's friction model is roughly right for near-ATM SPY — and a floor everywhere else.** Roll (1984) effective-spread estimate on 250 contract-days of SPY 5-min bars (near-ATM, 10–50 DTE): median **$0.089/leg** (IQR $0.043–$0.161). Implied round-trip crossing cost for a 2-leg vertical ≈ $20.4 incl. commissions vs the engine model's $17.6 — the model is ~15–20 % optimistic on the *most liquid options class in the world*. OTM legs and non-SPY underliers have wider relative spreads that trade-based bars cannot measure — quotes data (or P0B live probes) required; until then, treat every non-SPY friction number below as a **lower bound**.
2. **Sector-ETF and TLT verticals are DOA — P1A is killed and P1F is gutted before any backtest.** Median credits on XLF verticals ($3–24/lot) are *below the friction budget itself* in most classes, never mind the 2× DOA threshold. XLI: DOA in 7 of 8 classes. TLT: DOA in 6 of 8 (survivors are marginal at 25–28 % min-edge). This is the program working as designed: two experiments materially re-scoped for the cost of one measurement script.
3. **Friction alone explains a large share of the retired family's failure.** The EXP-1220 class (SPY 30-DTE narrow 5 %-OTM) needed **33 % of its median credit** just to clear friction; the 15-DTE 5 %-OTM class needed 68 %. Selling thin premium through a fat pipe was structurally hopeless regardless of signal.
4. **What friction does NOT kill:** SPY/QQQ 30-DTE iron condors (7.7–9.5 % min-edge), SPY/QQQ ATM calendars (4.6–5.2 % of debit), SPY/QQQ short-DTE iron flies (5.6–8.6 % — P2B's structure), QQQ wide verticals (7.4–13.4 %), GLD 2 %-OTM verticals and GLD calendars (9–20 %). The viable surface is **index-ETF premium in fat-credit structures**, not sector singles in thin ones.
5. **P1E's broken-wing butterfly, as sketched, does not exist as a credit trade**: at 98/95/broken-1.5× geometry the structure prices at a net **debit** everywhere ($3–89/lot). The prereg must either rework geometry (wider body/wings) or reclassify it as a debit-convexity trade (P1C-adjacent) with a $35.2/RT friction budget and no "credit" framing.

## Aggregated ledger (weighted-median premium per 1-lot vs friction)

Friction: verticals & calendars $17.60/RT (2 contracts); condors, flies, BWBs $35.20/RT (4 contracts). Expire-worthless variant saves the closing commissions (−$1.30/−$2.60). **DOA = median premium < 2× friction.** Full per-width detail in the JSON.

### Put credit verticals (the reference structure)

| DTE / width / OTM | SPY | QQQ | GLD | TLT | XLI | XLF |
|---|---|---|---|---|---|---|
| 30 / wide(~3 %) / 2 % | $215 · 8 % | $237 · 7 % | $188 · 9 % | $69 · 26 % | $38 · 46 % ⚠️ | $24 · **DOA** |
| 30 / wide / 5 % | $115 · 15 % | $131 · 13 % | $61 · 29 % | **DOA** | **DOA** | **DOA** |
| 30 / narrow(~1.2 %) / 2 % | $106 · 17 % | $123 · 14 % | $96 · 18 % | **DOA** | **DOA** | **DOA** |
| 30 / narrow / 5 % *(≈ EXP-1220 class)* | $53 · **33 %** | $66 · 27 % | $38 · 46 % ⚠️ | **DOA** | **DOA** | **DOA** |
| 15 / wide / 2 % | $162 · 11 % | $186 · 10 % | $113 · 16 % | $64 · 28 % | **DOA** | **DOA** |
| 15 / narrow / 5 % | **DOA** (68 %) | $45 · 39 % ⚠️ | **DOA** | **DOA** | **DOA** | **DOA** |

*(cell = weighted-median premium · min-edge % of premium; ⚠️ = clears DOA but min-edge > 33 % — thin)*

### Multi-leg structures

| Structure / class | SPY | QQQ | GLD | TLT | XLI | XLF |
|---|---|---|---|---|---|---|
| Iron condor 30 DTE (4 %P/3 %C, wide) | $231–395 · 9–15 % | $388–455 · 8–9 % | $176 · 20 % | $89 · 40 % ⚠️ | $128 · 28 % | $71 · 50 % ⚠️ |
| Iron condor 15 DTE | $58–290 · 12–61 % (width-sensitive) | $307–369 · 10–12 % | $77 · 46 % ⚠️ | $81 · 44 % ⚠️ | $104 · 34 % ⚠️ | **DOA** |
| Iron fly ~7 DTE (±2 % wings) | $486–628 · 5.6–7.2 % | $412–464 · 7.6–8.6 % | — | — | $137 · 26 % | $79 · 45 % ⚠️ |
| ATM calendar put 15/45 (debit) | $340 · 5.2 % | $380 · 4.6 % | $131 · 13 % | $74 · 24 % | $97 · 18 % | **DOA** |
| BWB 98/95/broken (net) | **−$81 debit** | −$66 | −$89 | −$31 | −$18 | −$3 |

## Program implications (per the pre-stated kill criteria)

| Experiment | Ledger verdict |
|---|---|
| **P1A XLF/XLI verticals** | **KILLED as designed** — every XLF class DOA; XLI DOA in 7/8 (lone survivor marginal at 46 % min-edge). Salvageable remnant, if any: XLI/TLT iron condors (28–40 % min-edge) — a different prereg, and thin. |
| **P1F TLT** | Verticals mostly DOA; re-scope to TLT iron condors (40 %, marginal) or 2 %-OTM wide verticals (26 %) — prereg only if P0B shows real TLT spreads no worse than modeled; else drop. |
| **P1B calendars** | **Alive**: GLD 13 %, TLT 24 %; XLF calendar DOA (drop SLV backfill priority accordingly — GLD first). SPY/QQQ calendars are the most friction-efficient premium structures measured (≈ 5 %) — calendars are a *new structure*, so SPY/QQQ calendars are governance-eligible and should be added to the P1B prereg. |
| **P2B event flies** | **Alive and friction-cheap** on SPY/QQQ (5.6–8.6 %) — best premium-to-friction ratio of any short structure measured. |
| **P1E BWB** | Geometry rework required (prices as a debit as speced); reclassify or redesign at prereg. |
| **P1C long-vol** | Debit structures pay ~$17.6–35.2/RT friction; calm-regime bleed budget in its prereg must include this explicitly. |
| **QQQ note** | QQQ wide verticals/ICs are friction-viable; whether QQQ credit verticals are inside the closed-family boundary is a governance call for Maximus/Carlos at prereg time — the ledger only says friction doesn't kill them. |

## Caveats (read before citing)

- Premiums are computed from **daily close marks** (trade-based), i.e., mid-ish estimates — not executable quotes. Honest fill probability (23–60 % measured fleet-wide) affects opportunity count, not per-trade friction, and is not in these numbers.
- The Roll estimator uses trade prices and understates spreads when trading clusters on one side; SPY-only, near-ATM only. Non-SPY effective spreads are unmeasured → P0B live probes are the calibration path.
- Spot inference (put-call parity on closes) can be off by a strike step on illiquid chains; class widths round to listed strikes, so "narrow/wide" bucket edges blur across the 2020→2024 price range.
- Structure P&L potential ≠ premium: for calendars/debit structures the ledger prices friction against the *debit*, which is a budget statement, not an edge claim.

## Machine-readable summary

```json
{"experiment": "EXP-P0A", "window": ["2020-01-01", "2024-12-31"], "rows_full": "experiments/honest-fills-fleet/results/friction_ledger.json",
 "friction_rt_usd": {"2leg": 17.6, "4leg": 35.2}, "commission_per_contract_side": 0.65,
 "roll_spy": {"n": 250, "median_eff_spread_per_leg": 0.089, "iqr": [0.043, 0.161], "engine_model_entry_per_side": 0.05, "verdict": "engine ~15-20% optimistic near-ATM SPY; floor elsewhere"},
 "doa": {"XLF_verticals": "all", "XLI_verticals": "7of8", "TLT_verticals": "6of8", "SPY_15dte_5pctOTM_narrow": true, "XLF_calendar": true, "XLF_ic15": true},
 "viable_min_edge_pct": {"SPY_QQQ_ic30": [7.7, 15.2], "SPY_QQQ_calendar": [4.6, 5.2], "SPY_QQQ_ironfly7": [5.6, 8.6], "QQQ_wide_verticals": [7.4, 13.4], "GLD_2pctOTM_verticals": [9.4, 20.1], "GLD_calendar": [13.4, 13.4]},
 "bwb_as_speced": "net debit everywhere; geometry rework required",
 "program_kills": ["P1A (XLF/XLI verticals)"], "program_rescopes": ["P1F->TLT ICs marginal", "P1B->add SPY/QQQ calendars, GLD before SLV", "P1E->geometry rework"]}
```
