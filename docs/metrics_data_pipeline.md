# Metrics Data Pipeline

**Audience:** every Sentinel-gate author, scanner author, and dashboard
author who pulls "trades that count" out of `data/pilotai_expNNN.db`.

**TL;DR:** **never** write `... FROM trades WHERE status LIKE 'closed%' ...`
again. Always go through one of two helpers in `metrics/eligible_trades.py`:

| Use case                                              | Helper                       | CTE name                  |
|-------------------------------------------------------|------------------------------|---------------------------|
| Closed-trade metrics (Sharpe, win-rate, totals)       | `metrics_eligible_cte()`     | `metrics_eligible_trades` |
| Live-position counts (concentration, OCC reconciler)  | `open_eligible_cte()`        | `open_eligible_trades`    |

Both helpers return a `WITH ... AS (SELECT * FROM trades WHERE …)` prefix
that you concatenate ahead of the rest of your `SELECT`. The deny-list
lives **once**, in code, and applies to every per-experiment SQLite DB.

---

## Why this exists

Until 2026-05, several Gate metric calculations leaked placeholder /
recovery / reset rows into rolling 30-trade Sharpe, win-rate, and total
PnL. The audit at `~/.openclaw/workspace/reports/metrics-leakage-audit-2026-05-02.html`
found **450 of 599 closed rows (75.1 %) were ineligible** — biggest
offenders: exp400 (72), exp401 (71), exp1220 (61).

Root cause: gate code did `... WHERE status LIKE 'closed%' ...`, which
matches `closed_pre_reset`, `closed_recovery`, and friends — none of
which are real fills. The dominant leak was in `sentinel/runtime.py`'s
metric block, **not** the EXP-1220 incident that surfaced the issue.

The fix is structural: deny-list lives in one place, every gate goes
through it, CI prevents regression.

---

## The deny-list (single source of truth)

Defined in `metrics/eligible_trades.py`:

```python
_DENY_STATUSES_FOR_METRICS = (
    "unmanaged",            # placeholder before management took over
    "failed_open",          # never filled
    "closed_pre_reset",     # killed by the reset fixture
    "superseded_by_recovery",
    "needs_investigation",  # human review pending — not a real outcome
    "pending_open",         # not yet filled
    "pending_close",        # in flight
)
_DENY_SOURCE_PATTERNS = ("%backfill%", "%placeholder%", "%recovery%")
_DENY_SOURCES_EXACT   = ("register_orphan_v3",)
```

Plus an unconditional excludes:
- `id LIKE 'orphan-%'` and `id LIKE 'synthetic-%'`
- `COALESCE(excluded_from_metrics, 0) = 0` (cc3's flag column,
  added by `scripts/migrate_excluded_from_metrics.py`)

For `open_eligible_cte()`, the filter is a **whitelist**:
`status IN ('open','pending_open','pending_close')`. This is intentional —
concentration and reconciliation gates need to see live in-flight
orders, but still want zombies/orphans suppressed.

---

## How to use

### Closed-trade metrics

```python
from metrics import OPEN_CTE_NAME  # if needed
from metrics import metrics_eligible_cte, ELIGIBLE_CTE_NAME

cte = metrics_eligible_cte()  # returns "WITH metrics_eligible_trades AS (...) "

rows = conn.execute(
    cte
    + f"SELECT pnl FROM {ELIGIBLE_CTE_NAME} "
    "WHERE status LIKE 'closed%' "
    "ORDER BY exit_date DESC LIMIT 30"
).fetchall()
```

### Open / live positions

```python
from metrics import open_eligible_cte, OPEN_CTE_NAME

cte = open_eligible_cte()
rows = conn.execute(
    cte + f"SELECT id, ticker, expiration FROM {OPEN_CTE_NAME}"
).fetchall()
```

### Counting active positions across statuses

```python
from metrics import open_eligible_cte, OPEN_CTE_NAME

row = conn.execute(
    open_eligible_cte() + f"SELECT COUNT(*) FROM {OPEN_CTE_NAME}"
).fetchone()
active = row[0]
```

---

## When to opt out (`# noqa: raw-trades`)

A small number of operational queries **must** see the raw table — the
helper would silence the very alert they exist to raise. Mark these with
the inline comment:

```python
# noqa: raw-trades — RC#4 zombie detector specifically targets
# `synthetic-monitor-*` IDs, which open_eligible_cte excludes by design.
rows = conn.execute(
    "SELECT id, ticker FROM trades "
    "WHERE id LIKE 'synthetic-monitor-%' AND status = 'open'"
).fetchall()
```

Current opt-out sites (and why):

| File                          | What it does                                         | Why raw                                             |
|-------------------------------|------------------------------------------------------|-----------------------------------------------------|
| `alerts/rc_monitoring.py:152` | RC#4 zombie detection (`synthetic-monitor-*` rows)   | Helper excludes those IDs by design                 |
| `sentinel/runtime.py` (G9)    | Lifecycle scan — finds malformed lifecycle records   | Needs to see all rows including filtered ones       |
| `sentinel/runtime.py` (G23)   | Stale-orphan detection                                | Audit gate: must see orphan- IDs the helper hides   |

If you add a new opt-out, document **why** in the comment. The CI
linter accepts only the literal string `# noqa: raw-trades` within 8
lines above the offending `FROM trades` line.

---

## CI guardrail

`scripts/lint_no_raw_trades.py` runs on every PR. It searches the
codebase (excluding the helper module, the lint script itself, the
migration script, and the `tests/` dir) for any `\bFROM\s+trades\b`
match and fails the build unless either:

- the file is in the allow-list, **or**
- a `# noqa: raw-trades` comment appears within 8 lines above

To run locally:

```bash
python3 scripts/lint_no_raw_trades.py
```

---

## The `excluded_from_metrics` flag (cc3's lane)

Independent of the deny-list, every trade row carries an
`excluded_from_metrics INTEGER DEFAULT 0` column (and a free-text
`exclusion_reason TEXT`). When ops manually flags a row as not-real
(e.g. EXP-1220 unmanaged stragglers, human-investigated zombies),
they set `excluded_from_metrics = 1` with a reason. The helper's CTE
honors this via `COALESCE(excluded_from_metrics, 0) = 0`.

The schema migration is in `scripts/migrate_excluded_from_metrics.py`;
it's idempotent and supports `--all` for rolling across every
`data/pilotai_*.db`. Backup DBs (`*.bak`, `*.backup*`) are skipped.

---

## File layout

```
metrics/
├── __init__.py                    # re-exports the helpers
└── eligible_trades.py             # deny-list + CTE builders

scripts/
├── lint_no_raw_trades.py          # CI guardrail
└── migrate_excluded_from_metrics.py  # idempotent schema migration

tests/
└── test_metrics_eligible_trades.py  # 31 unit tests covering the deny-list
```

---

## Adding a new exclusion

1. Add the status / source pattern to `_DENY_STATUSES_FOR_METRICS` or
   `_DENY_SOURCE_PATTERNS` in `metrics/eligible_trades.py`.
2. Add a test in `tests/test_metrics_eligible_trades.py` that inserts
   a row with the new status/source and asserts it's filtered.
3. Run `pytest tests/test_metrics_eligible_trades.py`.
4. Re-run `python3 scripts/lint_no_raw_trades.py`.
5. Capture before/after rolling-30 metrics on a representative DB
   (e.g. exp400) for the PR description.
