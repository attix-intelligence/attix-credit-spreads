# EXP-800 Tradier Live Authority Pull — executed 2026-07-12

**Operator:** cc5 · **Authorization:** Carlos explicit GO, 2026-07-12 (relayed by Kayley), approving the standing halt-and-drain recommendation
**Account:** Tradier live `6YA42569` (`tradier_6YA42569`) · **Model:** EXP-800 Safe Kelly 9/7/4 (`EXP-800-TRADIER`)
**Why (the four strikes):** ruled LUCK (2026-07-03); backtest twin divergence (live VIX-percentile proxy); un-root-caused Apr-02 12× duplicate-entry path; negative under honest fills in every variant (2026-07-10, `reports/EXP-800-BT-honest-fills-rerun.md`).

---

## 1. Halt — new entries disabled (config-to-code parity verified)

**Mechanism (the real one):** the deployed scanner's only live-order gate is the `live_submit` key at the root of `configs/live_exp800_tradier.yaml`. Parity chain verified end-to-end before flipping (dead-config lesson):

1. `railway_worker.py` spawns `main.py scheduler --config configs/live_exp800_tradier.yaml` for every registry-`active` experiment (EXP-800-TRADIER is `active`, `config_path` confirmed in `experiments/registry.json`).
2. `scripts/exp800_safe_kelly_scanner.py:101` (`_load_config`) loads the YAML root → `EXP800Scanner.__init__` stores it as `self.cfg` (line 579) → `ExecutionEngine(..., config=self.cfg)` (line 623).
3. `execution/execution_engine.py:706-721`: the executor submit path checks `config.get("live_submit", False)` **OR** env `LIVE_SUBMIT`; if neither is truthy it logs `[DRY RUN — live_submit=false]`, marks the pending trade failed, and never calls `executor_sink.submit()`.
4. **Env override ruled out:** the attix-worker Railway service env (project `dynamic-charm`, production) was enumerated via the Railway API — no `LIVE_SUBMIT*` variable exists. Config `false` therefore fully closes the gate.
5. Fail-safe checked: `_load_config`'s exception path returns `{}` → `live_submit` absent → gate defaults OFF.

**Change:** `configs/live_exp800_tradier.yaml` `live_submit: true → false`, commit `e5cfaf1` ("halt(exp800-tradier): pull live order authority"), pushed to `origin/main` 2026-07-12 ~17:34 UTC.

**Deployment:** attix-worker redeploy triggered via Railway API (plus Railway's own push-triggered build of the same commit); deployment at commit `e5cfaf1` confirmed `SUCCESS` (see §5 checklist). Market was closed (Sunday) throughout, so there was no window in which the old gate could fire between push and deploy.

**Not changed (deliberately):** registry status stays `active` — the scheduler keeps running in permanent DRY-RUN mode, which preserves position monitoring and gives free would-have-traded telemetry. Deactivating the registry entry entirely is a separate follow-up decision.

## 2. Drain — nothing to drain (already flat)

The account went flat by market action before this operation; no closing orders were needed and none were placed.

## 3. Broker evidence (Tradier native API, pulled 2026-07-12 ~17:33 UTC)

**Balances** (`GET /v1/accounts/6YA42569/balances`):

| Field | Value |
|---|---|
| total_equity | **$132,992.24** |
| total_cash | $132,992.24 (100% cash) |
| option_long_value / option_short_value | 0 / 0 |
| open_pl / close_pl | 0 / 0 |
| pending_orders_count | **0** |

**Positions** (`GET /v1/accounts/6YA42569/positions`): `{"positions":"null"}` — **no open positions.**

**Open orders** (`GET /v1/accounts/6YA42569/orders`): `null` — **no working orders** (the 14-contract order pending on Jul-3 is no longer on the book; nothing replaced it).

**Recent history** (`GET /v1/accounts/6YA42569/history`, latest events):

| Date | Type | Amount | Detail |
|---|---|---|---|
| 2026-07-06 | transfer ×2 | −$24.00 / −$31.50 | fees |
| 2026-07-02 | trade ×4 | +401.87 / +141.87 / −267.11 / −1,087.11 | SPY Jul-17 744/756 call side + 720/732 put side — condor round-trip close |
| 2026-07-01 | trade ×2 | −223.11 / +395.87 | put side legs |
| 2026-06-29 | trade ×2 | −254.11 / +708.86 | call side legs |
| 2026-06-05 | transfer ×2 | −$24.00 / −$31.50 | fees |

No trade activity after 2026-07-02. Lifetime: seed $133,230.71 (2026-06-23) → $132,992.24 = **−$238.47 (−0.18%)** across one iron-condor round trip plus fees.

## 4. Mac Studio LaunchAgents — no action taken, one human check requested

`SCANNER-OWNERSHIP.md` (2026-03-27) assigns scanner execution to Charles via Mac Studio LaunchAgents, but it predates the Railway migration and still lists EXP-800 as "NOT YET PROVISIONED". All evidence says EXP-800-TRADIER runs **only** on Railway attix-worker (registry-driven spawn; per-substream `*_EXP800TRADIER` env unmasking present on that service). **Nothing on the Mac Studio was touched, per instruction.**

**Human check for Charles:** confirm no local LaunchAgent/tmux session on the Mac Studio runs `main.py scheduler` (or any entrypoint) against `configs/live_exp800_tradier.yaml` or account `tradier_6YA42569` — `launchctl list | grep -i attix` + `tmux ls`. If one exists it would read the same repo config, so it would also be in DRY-RUN after a `git pull` — but it should be unloaded regardless.

## 5. Close-out checklist

- [x] Config-to-code parity of the halt flag verified (scanner → engine → gate; no env override; fail-safe default)
- [x] `live_submit: false` committed (`e5cfaf1`) and pushed
- [x] attix-worker redeployed at `e5cfaf1` (Railway deployment SUCCESS)
- [x] Open positions: none (broker-verified)
- [x] Working orders: none (broker-verified)
- [x] Account 100% cash, $132,992.24, pending_orders_count 0
- [ ] Charles: confirm no Mac-side LaunchAgent/tmux for EXP-800-TRADIER (§4)
- [x] Registry `active` → `retired` (2026-07-12, follow-up GO from Kayley; `retired_reason` stamped via ExperimentManager; attix-worker redeployed — scheduler process for EXP-800-TRADIER no longer spawns)
- [ ] Maximus: deliver this report to Carlos

**State after this operation:** EXP-800 retains no live order authority. Any future re-enable requires a new explicit per-session Carlos GO plus a config change, push, and redeploy — the same three-step chain documented here.

*Note on a second account:* the Tradier prod token also carries account `6YA42242` (visible in `user/profile`). It was not part of this operation and holds whatever it held; flagged for inventory completeness.
