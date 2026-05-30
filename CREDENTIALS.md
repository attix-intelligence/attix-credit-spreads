# CREDENTIALS.md — Alpaca Paper Trading Account Registry

**Read this first when starting a new session involving live paper trading.**

---

## Source of Truth: registry.json

**`experiments/registry.json` is the authoritative registry** (managed via `ExperimentManager`) for the
mapping between experiment names, env files, configs, Alpaca accounts, tmux sessions,
SQLite databases, and status. This file replaces the table below as the single place
to look up any experiment dimension.

```bash
# Quick-look at the registry:
cat experiments/registry.json

# Live dashboard (equity + positions for all accounts):
python3 scripts/portfolio_status.py

# Single experiment:
python3 scripts/portfolio_status.py exp400

# Active experiments only:
python3 scripts/portfolio_status.py --active

# Summary table only (no API calls):
python3 scripts/portfolio_status.py --summary
```

---

## Account Registry (current as of 2026-05-31)

| Experiment | Status | Broker Account | .env File | Config | DB |
|---|---|---|---|---|---|
| **exp400** | **ACTIVE** (tmux:exp400) | Alpaca PA3D6UPXF5F2 | `.env.champion` | `paper_champion.yaml` | `attix_champion.db` |
| **exp401** | **ACTIVE** (tmux:exp401) | Alpaca PA3Y2XDYB9I3 | `.env.exp401` | `paper_exp401.yaml` | `pilotai_exp401.db` |
| **EXP-V8A** | **ACTIVE** (Railway) | Alpaca PA3694QR73C1 | `.env.expv8a` | `paper_expv8a.yaml` | `pilotai_expv8a.db` |
| **EXP-V8A-IBKR** | **registered** (launches Mon 2026-06-01) | IBKR paper PA-DUO415613 (`ibkr_tafintech-p11-paper`) via executor | `.env.expv8a_ibkr` | `paper_expv8a_ibkr.yaml` | `pilotai_expv8a_ibkr.db` |
| exp036 | stopped | Alpaca PA3D6UPXF5F2 | `.env.exp036` | `paper_exp036.yaml` | `pilotai_exp036.db` |
| exp059 | stopped | Alpaca PA3LP867WNGU | `.env.exp059` | `exp_059_friday_ic_risk10.json` | `pilotai_exp059.db` |
| exp154 | stopped | Alpaca PA3UNOV58WGK | `.env.exp154` | `exp_154_risk5_icr12_sl35.json` | `pilotai_exp154.db` |
| exp305 | stopped | Alpaca PA3W9FZKK6XD | `.env.exp305` | `paper_exp305.yaml` | `pilotai_exp305.db` |

> Note: exp036 and exp400 share Alpaca account PA3D6UPXF5F2. exp036 was the predecessor;
> exp400 (champion) is the active experiment on that account.

### EXP-V8A-IBKR specifics (10th experiment — NEW 2026-05-31)
- **Broker:** IBKR paper, gateway account `tafintech-p11-paper` (IBKR account number `DUO415613`)
- **Sink:** `ExecutorOrderSink` (`compass/live/executor_order_sink.py` — shipped in PR #85, merged main 2026-05-30)
- **Executor `account_id` parameter:** `ibkr_tafintech-p11-paper`
- **Sizing target:** 3× max-loss/equity on ~$120K NAV → ~$360K aggregate max-loss
- **VRP knob:** `vol_target: 0.42` (vs EXP-V8A's 0.12 — linear scaling on observed 0.86× max-loss/equity at 0.12)
- **Sibling experiment:** identical VRP signals as EXP-V8A; routed to a different broker at 3× sizing. Parallel mode locked — do NOT modify EXP-V8A.
- **Carlos accepted-risk profile:** monthly +5-7%, annual +130-160% CAGR, 1y max DD ~38%, blowup prob (>30% loss in 12mo) ~15%
- **Launch plan:** `~/.openclaw/media/v8a_ibkr_launch_plan.html`

---

## Shared Polygon API Key

All experiments share a single Polygon.io API key:

```
POLYGON_API_KEY=y3y07kPIE0VkS6M3erj7uNsJ3dpLYDCH
```

This key is present in every `.env.exp*` file. The shared options cache at
`data/options_cache.db` is used across all experiments.

---

## Loading Credentials

To activate credentials for a specific experiment:

```bash
# Option A — preferred (exports into current shell)
source .env.champion     # for exp400
source .env.exp401       # for exp401

# Option B — explicit export (useful in scripts)
export $(grep -v '^#' .env.champion | xargs)
```

Each `.env.exp*` file sets:

```
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
ALPACA_PAPER=true
POLYGON_API_KEY=y3y07kPIE0VkS6M3erj7uNsJ3dpLYDCH
```

---

## Status Dashboard

```bash
# Full dashboard — reads experiments/registry.json, checks tmux, pings all Alpaca accounts:
python3 scripts/portfolio_status.py

# Legacy shell version (still works, but doesn't read the registry):
bash scripts/portfolio_status.sh
```

The Python dashboard shows: tmux state, account equity, day P&L, unrealized P&L,
total return vs $100K start, and all open positions.

---

## Starting / Stopping Experiments

```bash
# Start exp400 (champion):
tmux new -s exp400
source .env.champion
python main.py scheduler --config configs/paper_champion.yaml --env-file .env.champion

# Start exp401:
tmux new -s exp401
source .env.exp401
python main.py scheduler --config configs/paper_exp401.yaml --env-file .env.exp401

# Stop an experiment: Ctrl-C in the tmux session, then:
tmux kill-session -t exp400
```

After starting or stopping an experiment, update `experiments/registry.json` via `ExperimentManager`:
- Change `status` to `active` or `stopped`
- Update `tmux_session` to the session name (or `""` if stopped)
- Update `start_date` to today's date if restarting

---

## Known Issues

| Experiment | Issue |
|---|---|
| exp059 | Circuit breaker sync lag — DB state can diverge from Alpaca after a forced CB halt. Reconcile with `shared/reconciler.py` before restarting. |
| exp154 | Same circuit breaker / DB sync issue as exp059. Validate open positions in the DB match Alpaca before any new scan cycle. |
| exp305 | Previously had orphan positions — **reconciled 2026-03-12**. 2 trades had off-by-1 contract counts from partial fills (corrected in DB). Current state verified clean. |

---

## Adding a New Experiment

1. Create an Alpaca paper account and get the API key/secret
2. Create `.env.expNNN` with the credentials
3. Create or copy a config file in `configs/`
4. Add an entry to `experiments/registry.json` via `ExperimentManager` (copy an existing block, update all fields)
5. Verify: `python3 scripts/portfolio_status.py expNNN`

---

## WARNING

**NEVER commit `.env.exp*` files to git.**

These files contain live API keys and secrets. They are (and must remain) listed
in `.gitignore`. If you accidentally stage one, run:

```bash
git rm --cached .env.expNNN
```

and rotate the affected Alpaca API key immediately via the Alpaca dashboard.
