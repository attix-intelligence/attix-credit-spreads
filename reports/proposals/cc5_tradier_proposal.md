# CC5 Independent Proposal — Getting to a Profitable Real-Money Model on Tradier

**Author:** cc5 (independent; no coordination with other sessions)
**Date:** 2026-07-05
**Inputs read:** `reports/attix_program_review_2026-07-05.html`, `reports/PAPER_REVIEW_GOLIVE_RANKING.md`, `experiments/EXP-3570-live-months-replay/CC_EDGE_VS_LUCK_REVERIFY.md`, plus my own read-only inspection of configs, scanner code, git history, and experiment records (evidence cited inline).
**Constraints honored:** no code modified, no orders placed, no live configs touched, nothing committed.

---

## 0. Executive summary

**Proposal in one paragraph:** Do not launch any existing model. Retire the regime-flipping "champion" signal entirely — its direction calls are statistically a coin flip (p = 0.145) and its live implementation is provably un-twinnable. Instead, harden the one thing that survived June — EXP-1220's risk process — into a fully **mechanical, deterministic SPY put-credit program** ("ATX-M1") with delta-based strikes, hard trend/VIX/event gates instead of a regime state machine, EXP-1220 sizing, and broker-side entry rate-limiting. Because it is mechanical, its backtest twin is trivially exact — which converts the program's core unsolved problem (live ≠ backtest) from a research project into a non-issue. Gate it through (1) a real-data backtest on the **fixed** engine, (2) 10 weeks of single-account paper + Tradier dry-run shadow spanning 2 NFP prints and a FOMC, with pre-registered pass/fail criteria, then (3) go live on Tradier at a $30–50k sub-allocation in mid-September 2026. Meanwhile, **halt EXP-800 on Tradier completely** (not just size-freeze). Honest expected return at launch sizing: **+6–15%/yr with max drawdown designed ≤ 10%** — not +45%. If Carlos needs a bigger number than that, the truthful answer is that this program does not currently have an edge that supports it.

Where I agree with the program review: freeze/stop EXP-800, root-cause the dup bug, EXP-1220's risk process + event gating are the only validated assets, ~6–10 weeks of paper is the minimum honest bar, launch small.

Where I disagree:
1. **The review keeps the champion regime signal at the core of the launch config. I would delete it.** The evidence for the signal is zero (details §2). Composing good risk management around a coin-flip signal produces a well-risk-managed coin flip.
2. **The review's "build the twin" step points the effort the wrong way.** It proposes making the backtester replicate the live compass/regime logic. That is a week of work to faithfully reproduce a signal we have no reason to keep. Simplify the *strategy* until the twin is exact by construction — don't complicate the *twin* until it matches an unvalidatable strategy.
3. **"Freeze EXP-800 at 1 lot" is not enough.** A luck-ruled model with an un-root-caused 12× duplication event in its lineage should not hold live order-submission authority at any size. Plumbing validation (the one real benefit of keeping it) transfers to the new program's dry-run/pilot phase.

---

## 1. What I independently verified (my own evidence, not restated from the review)

1. **The live/backtest divergence has an identified structural root, still present in the live code.** The live scanner synthesizes the VIX term-structure signal from a VIX 50-day percentile proxy — `scripts/exp800_safe_kelly_scanner.py:208-213`: `vix_ratio_proxy = 0.9 + (vix_p50/100)*0.2` — while the backtest engine's `ComboRegimeDetector` (`compass/regime.py`) consumes real VIX/VIX3M. These are different algorithms that will keep disagreeing on regime state forever. No amount of "twin building" reconciles them without changing one side.
2. **The corrected backtest baseline is negative.** EXP-3311b (2026-07-03, `experiments/EXP-3311b-vix-fix-validation/REPORT.md`) proved that until commit `8f1bc8c`, the production backtest path silently ran **VIX-blind (1508/1508 days on vix=20 defaults)** whenever no Polygon indices key was configured. With real VIX restored, the canonical V8A replay flips from +4.9% to **−8.91% (Sharpe −0.06, MaxDD −31.8%) over 2020–2025**. Implication that the review does not draw sharply enough: **an unknown but probably large fraction of the ~150 historical backtest results are contaminated** and cannot be used even directionally. Any launch decision must rest only on backtests re-run through the fixed engine after 8f1bc8c.
3. **The duplicate-entry defenses in place today did not exist in a form that stopped Apr-02, and the current ones are unproven against that exact event.** The order-dedup fix `c8e073f` landed **Mar-13**, *before* the Apr-02 12× duplication — so the deployed defenses demonstrably failed or were bypassed. Later hardening (`4aa742a` pre-flight position-conflict check, `dad0865` client-id date scoping) plausibly covers it, but nobody has replayed the Apr-02 sequence against the current code to prove it. "Plausibly fixed" is not a live-money standard.
4. **The event-gate infrastructure exists but only covers NFP.** `configs/event_blacklist.json` has NFP dates through Dec-2026 (BLS-sourced, verified 2026-05-21); there is no FOMC or CPI gating anywhere in the active configs. The June killer was NFP, but FOMC and CPI are the same class of scheduled-macro gap risk.
5. **EXP-1220's config is already 80% of a mechanical strategy.** `configs/paper_exp1220.yaml`: bull puts only, no ICs, $5 wide, Monday-only cadence, 50% profit target, 2× credit stop, 9.35% max risk/trade, max 5 positions, DD circuit breaker. Its broker record (per the go-live ranking) shows the stops actually fire: losers −$40…−$260 vs credits +$550–900. The residual non-mechanical parts are its combo regime detector and %-OTM strikes.

---

## 2. Strategy choice: ATX-M1 — mechanical SPY put-credit harvest (EXP-1220, mechanicalized)

### Why this and not the review's composite

The program has exactly one economically defensible source of return: the **SPY variance/put risk premium** — a documented, persistent, academically supported premium (the program's own EXP-3300/Dew-Becker GEX work found it strengthening 2023→2025). Everything layered on top of it here — regime flipping to bear calls, ML overlays, iron condor switching, Kelly compounding — has either negative or null evidence:

- Direction calls: 6/8 resolved, p = 0.145 vs coin flip (EDGE-vs-LUCK re-verify). Zero evidence of timing skill.
- Regime gates: EXP-3303B's regime-transition gate failed its only real test (round-trip to zero).
- ML overlay: EXP-503 is negative.
- The June bear-call profits (+$16k) that make the flip look valuable netted to **−$155** against the Jun-05 bullish max-loss they were flipping away from — the whipsaw round trip is the signature of a signal chasing its own tail.

A mechanical program makes one honest claim: *collect the put premium far out-of-the-money, in defined-risk verticals, only in benign conditions, sized so the inevitable tail hit is survivable.* When conditions are not benign, it holds cash. It never claims to know direction. This is also the only strategy class whose backtest twin can be **exact**: every entry decision is a pure function of observable market data — no regime state machine, no cooldown counters, no proxy signals. Twin parity stops being a research project and becomes an assertion test.

### Specification

| Parameter | Value | Provenance |
|---|---|---|
| Instrument | SPY bull put verticals only. No bear calls, no ICs, no ML, no Kelly. | §2 rationale |
| Cadence | Monday entries only (1 new spread max per week) | EXP-1220 (`scan_days: [0]`) |
| DTE | Target 30, accept 21–45 | EXP-1220 |
| Short strike | **Delta-targeted 0.10–0.12** (not %-OTM) | Lesson 001 (`tasks/lessons.md`): fixed %-OTM misbehaves across vol regimes; delta self-adapts |
| Width | $5 | EXP-1220 |
| Min credit | ≥ $0.30 (6% of width) | EXP-1220 |
| **Entry gates (ALL must pass)** | | |
| Trend | SPY close > 200-dma, else **no entry** (never flip short) | Sitting out is the correct response to a coin-flip direction signal |
| Vol ceiling | VIX < 30 **and** VIX/VIX3M < 1.0 (real VIX3M — the SQLite indices DB already carries it; wire it to live) | Removes the proxy divergence at the root |
| Vol floor | VIX ≥ 12 | No premium worth the tail below this |
| Event blackout | No entry if NFP, FOMC decision, or CPI release falls within the next 2 trading days | EXP-3311 mechanism, extended; calendar build item |
| **Exits (mechanical)** | | |
| Profit take | 50% of credit | EXP-1220 |
| Stop | Close at 2× credit loss | EXP-1220 — the one stop discipline proven on broker record |
| Time | Close at DTE ≤ 5 | EXP-1220 (gamma) |

Everything above is expressible in the existing config schema (`paper_exp1220.yaml` fields) except delta-targeting on the live path (config flag `use_delta_selection` exists), real VIX3M in the live scanner, and the extended event calendar — those are the Phase-0 build items.

### Why it should be profitable (honest version)

The gross put premium at 0.10–0.12 delta / 30 DTE on SPY historically runs well above realized tail cost *when the seller (a) avoids scheduled macro gaps, (b) avoids inverted term structure, and (c) cuts losers before max loss*. The program's own broker evidence is consistent: EXP-1220 ran a version of this at +6.2% with −11.8% MaxDD through a quarter that put every sibling at −23% to −42% DD. The claim is **not** "this earned 45% on paper" — it is "this is the only configuration with a plausible premium, bounded tail, and provable implementation." Expected outcome at the risk framework below: **+6–15%/yr, MaxDD design ≤10%**. If the Phase-0 backtest on clean data cannot support even that, the correct decision is to launch nothing, and this proposal terminates with that answer.

---

## 3. Risk framework

### Sizing (per-trade and book)

- **Per-trade max loss ≤ 5% of NAV** (tighter than EXP-1220's 9.35%; on $50k that's $2.5k ≈ 5–6 contracts of a 5-wide). Hard contract cap **10 per order** regardless of NAV math.
- **Book max-loss ≤ 20% of NAV** (vs fleet-wide 51–131% in June). Max 4 concurrent spreads, max 1 new spread per expiry.
- Sizing base: **broker-reported equity**, refreshed at order time — never internal scanner NAV (the scanner-vs-broker NAV mismatch is on the record in the monthly-attribution discrepancies).
- No leverage. The review's own leverage sweep shows vol drag caps useful leverage ≈2× even taking the June curve at face value; at launch it is 1×, full stop.

### Circuit breakers (drawdown from broker-equity HWM)

| Trigger | Action | Reset |
|---|---|---|
| DD ≤ −6% | Halve per-trade risk (2.5%) | DD recovers above −4% |
| DD ≤ −10% | **Halt all new entries** | DD above −4% **and** 5 sessions elapsed (finite + self-clearing — the EXP-800 tier-3 deadlock lesson) |
| Any single day ≤ −4% | Skip next scheduled entry, page Carlos | Manual ack |

**Breakers must be live-fire proven before launch** (see §4 Phase-1). Nowhere in the fleet's entire history has a breaker been observed firing on a broker record — "configured" ≠ "works."

### Ops/structural guards (the class of risk that actually blew things up)

- **Broker-side daily entry rate limit: the executor rejects a second spread-open on the same underlying per day, independent of scanner state.** The Apr-02 event was 12 same-day entries from the 30-min scheduler; every scanner-side dedup can fail together with the scanner — the last line of defense must live in the executor.
- **Apr-02 replay test as a merge gate:** reconstruct the Apr-02 scan sequence against current `execution/execution_engine.py` and assert exactly one fill survives. Until this test exists and passes, no live authority for anything.
- **Position-reconciliation loop:** scanner book vs broker positions diffed every scan cycle; any mismatch (orphan legs, unknown positions — the EXP-503 −800-share naked short class) → automatic `live_submit=false` + alert.
- Expiry-week cleanup job (assignment artifacts).
- **Kill criteria while live:** −10% on the allocation → halt + written post-mortem before any restart; any duplication/orphan/unexplained broker event → immediate halt.

### Event gates

Extend `configs/event_blacklist.json` from NFP-only to NFP + FOMC decision days + CPI releases (BLS/Fed published calendars; quarterly re-verification cron already exists for NFP). Gate: no new entry within 2 trading days before the event. This is EXP-3311's n=1-validated mechanism generalized to the whole scheduled-macro class.

---

## 4. Validation plan (pre-registered gates; each gate can kill the launch)

### Phase 0 — Build + clean backtest (weeks of Jul-06 and Jul-13)

1. Root-cause the Apr-02 duplication (30-min scheduler re-entry path) and land the Apr-02 replay test + executor-side rate limit.
2. Wire real VIX3M into the live scan path (data exists in the SQLite indices DB; the EXP-3311b fix already proved end-to-end loading).
3. Extend the event calendar (FOMC/CPI).
4. Compose `paper_atxm1.yaml` from `paper_exp1220.yaml` (§2 spec) plus a byte-identical backtest config.
5. **Backtest ATX-M1 through the fixed engine** (post-`8f1bc8c`, real VIX, IronVault/real marks per Rule Zero): 2020-01 → 2026-06, explicitly including COVID-2020, the 2022 bear, and Jun-2026.

**GATE 1 (pre-registered):** net positive over the full window; positive in ≥4 of 6 calendar years; MaxDD ≤ 15%; Jun-2026 sub-window DD ≤ 12%; no year worse than −8%. **Fail → no launch, report "no edge at survivable sizing" to Carlos.** Given the corrected V8A baseline is −8.9%, failure here is a live possibility and finding it now is the point.

### Phase 1 — Paper + shadow (weeks of Jul-20 → Sep-25, ~10 weeks)

- **One** fresh Alpaca paper account (no more 9-clone fleets — they add correlation, not evidence). $100k seed, exact launch config.
- **Tradier dry-run shadow in parallel:** the identical scanner pointed at the Tradier account with `live_submit=false`, logging would-be orders against real Tradier quotes/margin — validates the live plumbing without EXP-800 and without risk.
- **Weekly twin-parity report:** every paper decision (entry/no-entry, strikes, size, exits) re-derived by the backtest engine on the same data; discrepancies are bugs, not tolerances. Mechanical rules make this exact.
- **Breaker live-fire drill (once, scheduled):** temporarily inject a synthetic HWM to force tier-1 and tier-2 triggers in the paper account and verify the size reduction/halt on the *broker order record*. This closes the "breakers never observed firing" gap without waiting for a real drawdown.
- Window spans **NFP Aug-07, NFP Sep-04** (both in the verified blacklist), one FOMC and ≥2 CPI prints — ≥4 scheduled-event tests of the gates.

**GATE 2 (pre-registered):** 100% twin parity on entry/exit decisions (any unexplained divergence = fail); zero ops anomalies (dups, orphans, stuck orders, reconciliation mismatches); realized MaxDD ≤ 12%; both breaker drills verified on broker record; all event blackouts observed. Return is **not** a gate criterion — 10 weeks of returns is noise, and gating on it would select for luck again (the EXP-800 lesson). Mechanism gates, not outcome gates.

### Phase 2 — Tradier go-live (week of Sep-28, if both gates pass)

- Sub-allocation **$30–50k** of the $133k (rest stays cash).
- Week 1: 1 contract per trade regardless of sizing math (fill-quality/slippage shakedown vs paper).
- Week 2+: design sizing (≤5% NAV/trade on the sub-allocation).
- Weekly reviews vs the twin; kill criteria from §3 armed from day one; Carlos gets the parity report weekly.
- First scale-up decision (raising the sub-allocation) no earlier than **Dec-2026** with a full clean quarter live.

## 5. Timeline

| When | What |
|---|---|
| Jul 06–17 | Phase 0: dup-bug root-cause + replay test, executor rate limit, VIX3M live wiring, event calendar, ATX-M1 config, clean-engine backtest → **Gate 1** |
| Jul 20 – Sep 25 | Phase 1: single paper account + Tradier dry-run shadow; twin-parity weekly; breaker drill; spans NFP Aug-07 & Sep-04, FOMC, 2× CPI → **Gate 2** |
| Week of Sep 28 | Phase 2: Tradier live, $30–50k, 1-lot first week |
| Dec 2026 | First scale-up review (1 clean live quarter) |

Roughly the review's schedule (it says ~Sep 2026 too) — the difference is what ships, not when.

## 6. What to do with the current EXP-800 Tradier deployment

**Halt it entirely — this week.** Concretely (Carlos's call to execute; I touched nothing):

1. Set `live_submit: false` in `configs/live_exp800_tradier.yaml` (currently `true`, line 159) and cancel any pending orders (a 14-contract order was submitted Jul-3 under the Phase-3 30-lot cap).
2. Let the account's open exposure flatten (it is essentially flat already: ≈$133k, one round-tripped condor, −$183 lifetime).
3. Revoke the Phase-3 30-contract authorization formally — the standing config authorizes up to 30 contracts on a model formally ruled luck, whose duplication path is unproven-fixed, whose direction signal is a coin flip, and whose backtest twin loses money. That authorization is the single largest live risk in the program today, and it costs nothing to remove.
4. Keep the account funded and the executor wiring warm — it becomes ATX-M1's dry-run target in Phase 1 and its live account in Phase 2. (This preserves the only genuine argument for keeping EXP-800 running — plumbing validation — while removing the order authority.)
5. Do **not** reuse the EXP-800 Kelly/HWM state for anything downstream; ATX-M1 starts with fresh state and its own DB.

I am deliberately stricter than the review's "freeze at 1-lot." A 1-lot EXP-800 earns ~nothing, proves nothing that the dry-run shadow doesn't prove more safely, and keeps a known-defective decision loop holding live order authority. There is no upside that justifies it.

## 7. Top 3 risks of my own proposal

1. **Gate 1 may reveal there is no launchable edge at all — and the timeline dies there.** The corrected V8A baseline (−8.91%) shows what clean data does to this program's claims. If mechanical VRP harvesting at 0.10–0.12 delta doesn't clear costs on real marks with the fixed engine, this proposal delivers "launch nothing," which fails the stated goal of a profitable Tradier launch. I consider surfacing that in week 2 a feature, but it is honestly the most likely failure mode of this plan.
2. **I removed the thing that made the June money.** No bear calls means that in a sustained bear market ATX-M1 sits ~fully in cash (trend gate) — long stretches of zero P&L, and the +$16k-style bear-call wins of Jun-08–12 never happen. If SPY enters a 2022-style year, this program earns roughly nothing for months and Carlos may reasonably ask why we're paying ops overhead for cash. My answer — a coin-flip signal shorting into rallies is how EXP-800's Mar-31/Apr-01 bear calls hit max loss — is statistically sound but will feel wrong every week a bear-call would have paid.
3. **Even a passed Gate 2 is thin evidence — ~10 weeks, ~10 entries, one regime.** Mechanism gates (parity, breakers, blackouts) verify the *implementation*, not the *edge*; a benign Aug–Sep passes a mediocre strategy. The launch therefore remains a controlled, bounded bet (worst case ≈ −10% of a $30–50k sub-allocation ≈ −$3–5k) rather than a statistically proven one — and it will take 2–4 live quarters before anyone can honestly claim more. Anyone selling a faster path to "proven" is re-running the EXP-800 mistake.

Secondary risks worth one line each: single-strategy/single-underlying concentration returns (accepted at this allocation; diversification is a post-Q1-2027 question, and last time "diversification" produced nine clones); the 2-day event blackout is calendar-dependent (a mis-dated FOMC entry in the blacklist silently defeats the gate — hence the quarterly re-verification cron must cover all three calendars); Tradier fill quality at 0.10-delta strikes is unmeasured (mitigated by the 1-lot shakedown week).

## 8. Honest expectations (so nobody is surprised later)

- At §3 sizing on a $50k sub-allocation: roughly **$250–650/month** expected, with occasional −$2.5k stop weeks and a design worst-case around −$5k before halt. Per year: +6–15% on the allocation.
- The +45% (EXP-800) and Sharpe-6.39 (v8a) numbers should be retired from all planning documents. One was luck plus a bug; the other doesn't survive real VIX.
- The path to bigger numbers is a real second edge (different underlying, different premium, different mechanism — not a re-skinned SPY put spread), earned *after* ATX-M1 has a clean live quarter — or accepting more capital at the same modest rate. There is no sizing or leverage trick that turns this edge into 45%/quarter; the review's own leverage table shows that.

---

*cc5, 2026-07-05. Written independently; disagreements with the program review are explicit in §0. Nothing herein was executed — proposal only.*
