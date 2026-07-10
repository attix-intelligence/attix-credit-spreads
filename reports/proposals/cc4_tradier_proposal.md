# CC4 Independent Proposal — Path to a Profitable Real-Money Model on Tradier

**Author:** cc4 (independent; no coordination with other sessions)
**Date:** 2026-07-05
**Inputs:** `reports/attix_program_review_2026-07-05.html`, `reports/PAPER_REVIEW_GOLIVE_RANKING.md` (rev 2), `experiments/EXP-3570-live-months-replay/CC_EDGE_VS_LUCK_REVERIFY.md`, plus read-only inspection of `configs/live_exp800_tradier.yaml`, `configs/paper_exp1220.yaml`, `configs/paper_exp3311.yaml`, `configs/event_blacklist.json`, `shared/database.py`, and git history.

---

## 0. Executive summary

**Launch a single, mechanical, put-side-only VRP harvester built on EXP-1220's structure and risk process — not on the champion signal — with an expanded event gate (NFP + FOMC + CPI), broker-equity breakers, and executor-enforced hard caps. Validate the *process* on paper for ~9 weeks (two NFP prints, one FOMC cycle), run a 1-lot real-money execution pilot in parallel to measure Tradier fill quality, then go live mid-September at a $20–25k risk budget inside the existing $133k account. Halt EXP-800 on Tradier entirely — not "freeze at 1 lot," halt — today.**

Where I agree with the program review: EXP-800 must stop trading real money; the risk process is the edge; leverage caps at ~1–1.5×; the 6–8 week paper window is the shortest honest route; go-live small and instrumented.

Where I disagree (details in §7):
1. **Drop the champion signal from the launch config entirely.** The review recommends "champion signal + 1220 sizing + 3311 gate." The champion signal's core content — a regime detector that flips between bull puts and bear calls — is formally indistinguishable from a coin flip (p = 0.145, CC_EDGE_VS_LUCK §3). Its structure (15 DTE, 2 % OTM, 12-wide) is exactly what max-lossed 8 accounts on one 4 % dip. Composing proven risk controls around an unproven signal is polishing the wrong core.
2. **A full backtest-twin is not a launch blocker.** Replace it with a cheaper, more targeted "decision replayer" (spec-conformance audit of every live decision). The twin can't answer the skill-vs-luck question anyway at n≈20 trades — that is a statistics problem, not an engineering problem.
3. **Freeze-at-1-lot for EXP-800 is the wrong halfway house.** Every EXP-800 real-money trade has an expected value we cannot distinguish from zero, executed by a pipeline with a live un-root-caused duplication path. Halt it; keep the plumbing warm with the *new* config's execution pilot instead.
4. **Set honest return expectations now.** The only survivable live return stream produced +6.2 % in a quarter that was mostly rally. The right expectation for the launch model is **8–15 %/yr at MaxDD ~10–12 %**, not the +45 %s on the leaderboard (which were luck + full-NAV exposure). If that number is not worth the effort, the honest decision is not to launch — not to reach for size.

---

## 1. Strategy choice: "EXP-1250" — put-side VRP harvester, EXP-1220 chassis

### What it is

One config, one underlying, one structure, mechanical rules:

| Parameter | Value | Provenance |
|---|---|---|
| Underlying | SPY only | All live evidence is SPY; no fake diversification |
| Structure | Bull put credit spread only. **No bear calls, no iron condors** | Bear calls contributed the first two max losses on the EXP-800 ledger (−$7.7k, Mar 31/Apr 1); direction-flipping is proven noise |
| DTE | target 30, min 21, max 45; force-manage at 5 DTE | EXP-1220 (`paper_exp1220.yaml`) — stays out of gamma week |
| Strikes | 5 % OTM short strike | EXP-1220 — the 2 %-OTM champion strike is what got run over |
| Width | $5 | EXP-1220 — caps the per-spread tail |
| Min credit | ≥ 6 % of width ($0.30 on a 5-wide) | EXP-1220 |
| Cadence | **Mondays only, max 1 new position per day** | EXP-1220's weekly cadence; the 1/day cap is also the structural dup-bug backstop |
| Exits | Take profit at 50 % of credit; stop at 2× credit; close at 5 DTE regardless | EXP-1220's stop discipline is the single most valuable live artifact in the program: 21 opens, biggest settled loss **−$260** vs credits $550–900 |
| Market filter (not "regime") | No entry if SPY < 200-dma, or VIX > 30, or VIX < 10 | Mechanical don't-fight-the-tape / no-premium filters. Sitting out is a position |
| Event gate | No new entries within **2 trading days before NFP, FOMC decision, or CPI print**; no entry whose *stop-management window* (last 5 DTE) lands on an event day if avoidable | EXP-3311's gate mechanism, extended. Requires extending `configs/event_blacklist.json` with FOMC + CPI calendars (both are published years ahead, like the BLS schedule) |

Call it EXP-1250 to make clear it is 1220's chassis with the 3311 gate and a real breaker — and that it is a *new* track record starting at zero.

### Why I believe this is profitable (the honest causal chain)

I am explicitly **not** resting the profitability claim on any backtest (the engine does not replicate live — EXP-3570) or on the paper leaderboard (one correlated lucky quarter). The claim rests on four legs:

1. **The premium is real.** The SPY put variance-risk premium is one of the most robust documented anomalies in finance (options systematically overprice realized vol; the put wing especially, because crash insurance has structural buyers). The program's own EXP-3300 found the SPY put-credit edge *strengthening* 2023→2025 — the one backtest finding that survives, because it's about the market, not about our engine.
2. **The failure mode of harvesting it is known and boundable.** Short-vol accounts don't die from lack of premium; they die from tail concentration. Every June casualty in the fleet is the same autopsy: full-NAV books, no stops, event-day entries. Those are all *choices*, and EXP-1220 demonstrated live that the opposite choices produce a survivable stream (−11.8 % MaxDD in the fleet-killer week vs −38 to −42 % for the clones).
3. **Account-level profitability = premium collected − tails − costs.** Legs 1+2 handle premium and tails. Costs are the honest open question ($1.30/spread commissions + slippage on a ~$400–600 credit; Alpaca paper fills are optimistic). That is exactly what the §3 execution pilot measures with real dollars *before* the real launch.
4. **What I deliberately gave up costs little.** Dropping bear calls forfeits "bear-market income" that, on the broker record, was a net loser and a coin flip. Dropping iron condors forfeits structures the live system never actually traded (0 ICs on the EXP-800 ledger). Nothing with live positive evidence was removed.

Expected performance, stated for the record so we can be judged against it: **+8–15 %/yr, MaxDD ≤ 12 %, ~40–50 trades/yr, win rate ~75–85 % with losers capped near stop levels except on gaps.** A June-2026-type event under this config should cost roughly 1–2 stopped trades + mark-to-market noise: single-digit drawdown.

---

## 2. Risk framework

Three layers, each enforced in a *different* place so one bug can't disable them all.

### 2.1 Sizing (scanner layer)

- **Sizing unit = full spread width lost, not stop level.** Stops fail on gaps; sizing must assume they do.
- Per-trade max loss ≤ **4 % of broker NAV** (at $133k: ≈$5.3k → ~11 contracts of a 5-wide; round down to **10-contract hard cap per order**).
- Book max-loss ≤ **15 % of broker NAV** (~$20k) across all open positions.
- Max 4 concurrent positions, max 1 entry/day, max 2 positions per expiry.
- Leverage: **1.0× only.** The review's own leverage table shows the edge is drag-capped at ~2×; at launch there is no case for anything above 1×. No compounding of size for the first 6 live months (`sizing_mode: flat`).
- **NAV source = broker API equity, never internal marks.** (EXP-800's live breaker never fired partly because state and reality diverged.)

### 2.2 Breakers (scanner layer, drilled before launch)

- **−8 % from broker-equity HWM → halve size.**
- **−12 % → halt new entries** until (a) book is flat AND (b) a human (Carlos) re-arms. No auto-resume, no trade-count timers — the EXP-800 tier-3 "skip 30 slots" design deadlocked once already and was patched under fire (commit 9646b87).
- **Calendar-month loss > 6 % → done for the month.**
- **Fire-drill requirement:** before go-live, each breaker must be *observed firing* against a replayed June-2026 equity curve in the paper account's own code path — not unit tests, the deployed scanner. No breaker in the fleet has ever fired live; an untested breaker is decoration.

### 2.3 Hard caps (executor layer — independent of the scanner)

The Apr-2 lesson is that scanner-level discipline can be bypassed by scanner-level bugs. The executor REST service must *reject*, on its own state:

- any order > 10 contracts;
- any order that would make aggregate open max-loss (computed from **broker positions**, not scanner DB) exceed $20k;
- **any order whose (underlying, expiry, strikes, side) matches an already-open broker position or any fill from the last 3 trading days** — this is the duplication kill-shot, and it lives below the layer where the bug occurred;
- any opening order on an event-gate day (executor reads the same `event_blacklist.json` — belt and suspenders);
- more than 2 opening orders per day, account-wide (allows 1 entry + 1 retry after a genuine cancel).

Root-cause note for the fix work: `shared/database.py`'s `alert_dedup` window is **1800 s — exactly the 30-minute scan cadence**. Each scan slot lands at or after the previous entry's dedup expiry, so same-day identical re-entries pass dedup by construction. That is consistent with the Apr-2 pattern (12 identical fills at consecutive 30-min slots). The fix is not a longer window; it is position-aware idempotency against broker state, at the executor layer, per above. (~2 days, matching the review's estimate.)

### 2.4 Event gates

- Extend `event_blacklist.json` from NFP-only to **NFP + FOMC decisions + CPI**, from published calendars, with the existing quarterly re-verification cron.
- Gate = no *new* entries within 2 trading days before the event. Positions already on stay on (they were sized to survive; churning them adds cost).
- **Fail-closed:** if the blacklist file is missing, stale (> 100 days since `_verified`), or unparseable, the gate blocks all entries rather than allowing all. A gate that fails open is how 3303B round-tripped to zero.

---

## 3. Validation plan before real money

### 3.1 What can and cannot be validated — said out loud

Nine weeks of weekly-cadence paper is **8–10 trades**. That cannot statistically prove edge; pretending otherwise is how this program produced 150 backtests and one correlated fleet. What ≥2 NFP prints + 1 FOMC cycle CAN prove is that the **machine** behaves: gates block, stops fire, sizes respect caps, breakers trigger, no dups, books stay clean. So the go-live bar is *process-validated + edge-plausible + sized so that being wrong is cheap*, with the real edge verdict scheduled 12 months out on pre-registered criteria (§3.5). This is the honest version of "launch": real money remains an experiment in year 1, and it is sized like one.

### 3.2 Pre-registration (before the paper account opens)

Commit to the repo, before first trade, a spec freeze: config hash, expected trade frequency, per-trade loss cap, book cap, breaker thresholds, and the §3.4 acceptance criteria + §3.5 kill criteria. **Any config change after that resets the paper clock.** This kills sizing creep (3311 went 8→38 lots mid-track) and forking-paths evaluation.

### 3.3 Three validation tracks in parallel (Jul 13 → Sep 11)

1. **Fresh Alpaca paper account** (new account — no inherited state) running EXP-1250 through NFP Aug-7, NFP Sep-4, FOMC Jul-28/29, CPI Jul/Aug prints.
2. **Decision replayer instead of a backtest twin.** A deterministic script that, for every live scan, takes the day's recorded inputs (chain snapshot, SPY/VIX closes, account equity, calendar) and independently recomputes what the spec says the decision should have been — entry/no-entry, strikes, size, exits — and diffs it against what the scanner actually did. Every trade in the paper window must replay clean, and it keeps running against the live deployment forever. This directly targets the program's actual repeated failure (deployed behavior ≠ documented spec: EXP-V8A oversizing, EXP-800 regime proxy, IBKR sizing base) at ~2 days' build cost instead of a multi-week twin rebuild. The full engine-parity twin remains worthwhile *research* — it stops being a *launch gate*.
3. **Real-money execution pilot on Tradier, 1 lot, from ~Aug-10** (contingent on 4 clean paper weeks + ops fixes verified): the same EXP-1250 signals, 1 contract each, ≤ $500 max loss per position, ≤ $1.5k book. Purpose is **not P&L** — it is measuring the one thing paper cannot: real Tradier fill quality on 5-wide SPY spreads (mid vs fill, time-to-fill, reprice behavior), i.e., the cost leg of the profitability claim (§1.4 leg 3). Total downside is lunch money; the information decides go-live economics. It also replaces EXP-800 as the thing keeping the live pipe exercised.

### 3.4 Go-live acceptance criteria (all required, ~Sep-14 review)

- ≥ 8 paper trades; **zero** decision-replayer mismatches; **zero** broker-record anomalies (dups, orphans, phantom fills — same forensic pull as the Jul-3 review).
- Every exit rule observed firing at least once on the broker record (profit-take, stop, 5-DTE manage); event gate observed blocking ≥ 2 real entry opportunities.
- Breaker fire-drill passed in the deployed code path (§2.2).
- Executor hard caps demonstrated by rejection test (a deliberately oversized order must bounce).
- Execution pilot: average entry slippage ≤ 15 % of credit; if worse, no-go and rethink (wider structures, SPX, or don't launch).
- Paper P&L is explicitly **not** an acceptance criterion (8 trades of P&L is noise) — but a breaker-triggering paper drawdown is an automatic no-go.

### 3.5 Post-launch kill criteria (pre-registered, evaluated monthly)

- Realized per-trade loss > 1.2× the sizing model's assumed max loss on any trade → halt, post-mortem.
- Any replayer mismatch or broker anomaly live → halt same day.
- −12 % account drawdown → breaker halt + human review (already in §2.2).
- After 12 months: if total return net of costs < 0, or realized cost share > 25 % of gross credits, the model is retired — not retuned and relaunched under a new EXP number.

---

## 4. Timeline

| When | What |
|---|---|
| **Week of Jul 6** | Halt EXP-800 Tradier (§5, day 1). Ops hardening: dup-entry root-cause + executor idempotency fix; buy in EXP-503's −800 SPY orphan; set dashboard `DASHBOARD_PASSWORD`/`SECRET_KEY` (real account data is exposed today); single kill-switch runbook. |
| **Week of Jul 6–13** | Compose `paper_exp1250.yaml`; extend event blacklist (FOMC+CPI, fail-closed); build decision replayer + breaker fire-drill harness; pre-register spec + criteria. Retire redundant paper clones (400/401/3303B/3309/503/V8A) — keep 1220 and 3311 running untouched as controls. |
| **Jul 13 → Sep 11** | Paper validation (covers NFP Aug-7 + Sep-4, FOMC Jul-28/29, 2 CPI prints). |
| **~Aug 10** | Execution pilot on Tradier, 1 lot (gated on 4 clean paper weeks + ops fixes). |
| **~Sep 14** | Go/no-go review vs §3.4. Carlos decision. |
| **~Sep 15** | Live: EXP-1250 on `tradier_6YA42569`, $20k book max-loss budget, 10-contract order cap, 1.0×, weekly replayer report. |
| **Dec 2026 / Mar + Sep 2027** | Quarterly reviews vs §3.5. Scale-up (to ~30 % NAV book cap, still 1×) only after 6 live months with zero process violations and positive net P&L. |

This is ~1 week slower than the review's path on paper-start but reaches go-live on the same date (mid-Sep), because the twin-build week is replaced by the cheaper replayer and the work parallelizes.

---

## 5. The current EXP-800 Tradier deployment

**Halt it — today, fully, not a size freeze.**

1. `live_submit: false` in `live_exp800_tradier.yaml` and deregister the worker (Carlos's action or per-session go; I have modified nothing).
2. **Cancel the pending orders** (2 pending as of Jul-3, one reportedly 14 contracts). A 14-lot × 12-wide order is ~$16.8k max loss — authorized on a model whose direction calls are a coin flip.
3. Book is flat (all cash as of Jul-3) — nothing to unwind. If anything filled since: manage to close per existing exit rules, no new entries.
4. **Formally revoke the Phase-3 30-contract authorization.** A dormant 30-lot cap (~$36k max loss per order) on a luck-ruled model with an un-root-caused duplication path is the single largest standing risk in the program. Revoking costs nothing.
5. Keep the account, token wiring, and executor service — they become EXP-1250's execution-pilot rail in August. The account keeps earning its ~flat cash return until then.

Why not the review's "freeze at 1 lot"? A 1-lot EXP-800 buys nothing: its P&L is uninformative (that's what "ruled LUCK" means), it keeps a buggy entry path attached to real money, and the "keep the plumbing warm" benefit is delivered better by the execution pilot running the config we actually intend to launch. Expected value of every additional EXP-800 trade ≈ 0 minus costs, with operational tail risk attached. Halt is strictly better.

---

## 6. Top 3 risks of THIS proposal

1. **The net edge may be too thin to survive costs at this size.** 5-wide, 5 %-OTM spreads collect small credits ($0.30–0.60); commissions + live slippage could consume 20 %+ of gross premium, turning a modest gross edge into a net zero. This is the most likely failure mode of my proposal — a slow bleed, not a blow-up. *Mitigation:* the execution pilot measures exactly this before go-live (§3.4 slippage bar); the 12-month cost-share kill criterion (§3.5) retires it honestly if paper-vs-live costs diverge. *Residual:* real; if it fires, the answer may be SPX (cash-settled, better spreads, no assignment risk) or no launch at all.
2. **I'm validating process, not edge — the launch could be a well-risk-managed strategy with no alpha.** 8–10 paper trades plus a literature prior is a rational but unproven basis; the VRP can also compress for years. *Mitigation:* sizing makes being wrong cheap (~$20k bounded book on $133k); pre-registered 12-month verdict prevents the sunk-cost relaunch loop; expectations set at 8–15 % so nobody is tempted to "fix" a merely-average year with leverage. *Residual:* opportunity cost of a year, ~bounded dollars.
3. **Untested regimes + gap risk: the whole evidence base is one rally-plus-one-dip, and stops don't work through gaps.** EXP-1250 has never seen a sustained bear or a VIX-40 shock; the trend/VIX filters that should side-line it are exactly the components with the least live evidence, and an overnight gap through both strikes produces full-width losses regardless of stops. *Mitigation:* this is why sizing assumes stops fail (full-width loss = the sizing unit, §2.1) — a 4-position book gapped to total max loss is −15 %, painful but survivable by construction; event gates remove the *scheduled* gap catalysts; the −12 % breaker + human re-arm handles the unscheduled ones. *Residual:* a 2020-March-style event still costs the full 15 % book; that is the irreducible price of being short vol at all.

Honorable mentions I'm accepting with eyes open: this is still **one bet on one underlying** — the same "SPY doesn't crash" bet as the fleet, just sized survivably (real diversification is future work, not a launch precondition); and **sizing-creep culture risk** — three months of small wins will generate pressure to scale early, which is exactly how 3311 went 8→38 lots (the §3.2 config-hash freeze + executor caps are the structural defense; the review cadence is the human one).

---

## 7. Where I differ from the program review, in one table

| Topic | Program review | This proposal | Why |
|---|---|---|---|
| Signal core | Champion signal + 1220 sizing + 3311 gate | **EXP-1220 chassis outright; champion signal dropped; bull puts only** | The champion's regime flip is p=0.145 noise and its 2 %-OTM/15-DTE/12-wide structure is the fleet-killer; 1220's 5 %-OTM/30-DTE/5-wide + stops is the only structure with live-proven loss behavior |
| Backtest twin | Launch blocker, ~1 week | **Decision replayer as blocker (~2 days); twin demoted to research** | The twin can't resolve skill-vs-luck at n≈20 anyway; the actual recurring failure is deploy≠spec, which the replayer tests directly and continuously |
| EXP-800 Tradier | Freeze size at 1 lot | **Halt entries, cancel pendings, revoke 30-lot cap; account becomes the pilot rail** | 1-lot luck-model trades have ≈0 information value and keep a buggy path attached to real money |
| Real money before go-live | None | **1-lot execution pilot from ~Aug (≤$1.5k book)** | Fill quality is the profitability swing factor and is unmeasurable on paper; the information is worth more than the bounded cost |
| Return expectation | (not stated) | **8–15 %/yr, MaxDD ≤ 12 %, stated up front** | Prevents the +45 %-anchored disappointment→leverage spiral; if 8–15 % isn't worth it, the right call is no launch |

Same destination as the review — small, instrumented, mid-September, EXP-1220-DNA — but with the unproven signal removed from the core, the validation aimed at the failure mode we actually have, and real money doing the one job paper can't do.

---
*cc4 · 2026-07-05 · Written independently per Carlos's instruction. No code, configs, or orders were modified; nothing committed.*
