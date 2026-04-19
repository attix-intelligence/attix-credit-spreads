# Sentinel v2 — Runtime Enforcement System

Sentinel is the automated safety layer for all paper trading experiments.
It runs pre-scan gates before each trading session and runtime gates during execution
to prevent misconfigured, drifting, or unhealthy experiments from placing trades.

## Architecture

```
sentinel_state.json        ← coordination file (read by every scanner)
     │
     ├── sentinel/guards.py      ← pre-scan gates (G0-G5), run at scanner startup
     ├── sentinel/runtime.py     ← runtime gates (G6-G9), run during execution
     ├── sentinel/state.py       ← state management (load/save/fingerprint)
     ├── sentinel/history.py     ← SentinelDB (SQLite: snapshots, alerts, config changes)
     ├── sentinel/orchestrator.py ← orchestrates full gate pipeline
     ├── sentinel/alerter.py     ← Telegram alert integration
     │
     ├── scripts/run_sentinel.py   ← main entry point (cron / manual)
     ├── scripts/sentinel_cli.py   ← CLI for manual checks and alert management
     │
     └── web_dashboard/           ← /sentinel route for visual health dashboard
         ├── html.py  (render_sentinel_page, _compute_health_score, _freshness_dot)
         └── app.py   (sentinel_dashboard route handler)
```

## Gate Reference

### Pre-scan Gates (run before each trading session)

| Gate | Name | What it checks | Severity |
|------|------|----------------|----------|
| G0 | Registry Status | Experiment must be `active` or `paper_trading` in registry.json | BLOCK |
| G1 | Sentinel State | Experiment must not be `halted` in sentinel_state.json | BLOCK |
| G2 | Config Fingerprint | SHA-256 of config file must match stored fingerprint | BLOCK |
| G3 | Alpaca API Health | Alpaca account must be reachable and return valid equity | BLOCK |
| G4 | Account Validation | Account ID must match expected account for experiment | BLOCK |
| G5 | Certification | Experiment must have a valid deployment certificate | WARN |

### Runtime Gates (run during execution)

| Gate | Name | What it checks | Severity |
|------|------|----------------|----------|
| G6 | Sizing Validation | Position size must be within configured risk limits | BLOCK |
| G7 | Orphan Detection | Detects positions not tracked by any experiment | CRITICAL |
| G8 | Drift Tracking | Live win rate / avg loss vs backtest baseline | WARNING/CRITICAL |
| G9 | Lifecycle Monitor | Detects stuck or expired positions | WARNING |

## Health Score (0-100)

Computed per experiment in `_compute_health_score()`:

- **Halted experiment** → 0
- **Halt-severity gate** → 0
- **Critical gate** → -30 per gate
- **Warning gate** → -10 per gate
- **Stale health check** (>48h) → -20
- **Stale health check** (>24h) → -5
- **Never checked** → -5

## sentinel_state.json

The coordination file read by every scanner at startup:

```json
{
  "sentinel_version": "1.1",
  "runtime_gates_enabled": true,
  "experiments": {
    "EXP-400": {
      "status": "active",
      "paper_config": "configs/paper_champion.yaml",
      "config_fingerprint": "5de182dc...",
      "account_id": "PA36XFVLG0WE",
      "last_health_check": "2026-04-19T10:00:00+00:00",
      "halt_reason": null,
      "backtest_baseline": {
        "win_rate": 78.0,
        "avg_pnl": 525.0,
        "avg_loss": 2100.0,
        "mc_worst_dd_pct": 41.5
      }
    }
  }
}
```

## CLI Usage

```bash
# Show all experiments with health scores
python scripts/sentinel_cli.py status

# Run all gates for one experiment
python scripts/sentinel_cli.py check EXP-503

# List open alerts
python scripts/sentinel_cli.py alerts
python scripts/sentinel_cli.py alerts --all

# Resolve an alert
python scripts/sentinel_cli.py resolve 42 --operator charles --note "false positive"

# Generate daily health report
python scripts/sentinel_cli.py report
python scripts/sentinel_cli.py report --html --output-dir output/sentinel_reports
```

## Dashboard

The `/sentinel` route (session-authenticated) shows:

- **Summary cards**: average health score, critical count, halted count, warnings
- **Per-experiment health cards**: health score badge, gate status pills (G0-G8), data freshness indicator, halt reasons
- **Alert history table**: all alerts with severity, experiment, message, and resolution status

## Runbook

### Experiment shows health score 0

1. Check `sentinel_state.json` — is the experiment `halted`?
2. If halted, check `halt_reason` for the cause
3. Fix the underlying issue (e.g., reduce position size, update config)
4. Set `"status": "active"` and `"halt_reason": null` in sentinel_state.json
5. Re-run: `python scripts/sentinel_cli.py check EXP-XXX`

### Config drift detected (G2 FAIL)

1. Run `python scripts/sentinel_cli.py check EXP-XXX` to see the mismatch
2. If the config change was intentional:
   - Update the fingerprint: `python scripts/run_sentinel.py --experiment EXP-XXX`
3. If unintentional, revert the config file to match the stored fingerprint

### Stale health check (G3 WARNING/CRITICAL)

1. Check if the scanner cron is running: `crontab -l`
2. Check scanner logs for Alpaca API errors
3. Verify Alpaca credentials in the experiment's `.env` file
4. Manual check: `python scripts/sentinel_cli.py check EXP-XXX`

### Alert won't resolve

1. List alerts: `python scripts/sentinel_cli.py alerts`
2. Resolve by ID: `python scripts/sentinel_cli.py resolve <ID> --note "reason"`
3. If the alert keeps re-firing, fix the underlying issue first

### Adding a new experiment to Sentinel

1. Add the experiment to `experiments/registry.json`
2. Add an entry to `sentinel_state.json` under `experiments`
3. Include: `status`, `paper_config`, `config_fingerprint`, `account_id`, `backtest_baseline`
4. Run: `python scripts/sentinel_cli.py check EXP-XXX` to verify all gates pass

## Database (sentinel.db)

SQLite database at `sentinel/db/sentinel.db` with tables:

- **experiment_snapshots**: daily equity, positions, win rate snapshots
- **config_changes**: tracked config field changes with approval status
- **deployment_certificates**: gate-pass certification records
- **alerts_log**: all alerts with resolution tracking

## Testing

```bash
# Run all sentinel v2 tests
python -m pytest tests/test_sentinel_v2.py -v

# Run specific test class
python -m pytest tests/test_sentinel_v2.py::TestHealthScore -v
```
