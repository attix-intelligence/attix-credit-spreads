"""
SENTINEL Gates 7, 8 & 9 — Runtime health monitors.

Gate 7 — Orphan / Unmanaged Position Detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compares Alpaca /v2/positions vs DB open trades every scan.
Detects orphans (Alpaca-only) and ghosts (DB-only).
  - Orphan persists ≥3 scans → CRITICAL
  - ≥5 simultaneous orphans → HALT experiment
  - Ghost → CRITICAL (external close not captured)

Gate 8 — Live-vs-Backtest Runtime Drift Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Monitors each active experiment's rolling 30-trade window and compares
against backtest baselines stored in ``sentinel_state.json`` under the
``backtest_baseline`` key.

Tracked metrics:
  win_rate, avg_loss, peak_drawdown_pct

Alert thresholds:
  Metric       | WARNING        | CRITICAL       | HALT
  -------------|----------------|----------------|-------------
  win_rate     | -10 pp         | -15 pp         | -20 pp
  avg_loss     | 1.5x baseline  | 2.0x baseline  | 3.0x baseline
  drawdown     | 80% MC worst   | 100% MC worst  | 110% MC worst

Gate 9 — Position Lifecycle Monitor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tracks every position from open→close and enforces time-bounded lifecycle.
Flags positions stuck in intermediate states:

  Status              | WARNING     | CRITICAL
  --------------------|-------------|----------
  pending_open        | 30 min      | 2 hrs
  pending_close       | 30 min      | 2 hrs
  needs_investigation | immediately | 4 hrs
  open (no mgmt)      | 24 hrs      | —

Usage
-----
  from sentinel.runtime import orphan_gate, check_runtime_drift

  orphan_gate("EXP-400")                        # Gate 7
  drift_alerts = check_runtime_drift("EXP-400") # Gate 8
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Rolling window size
WINDOW_SIZE = 30

# Minimum trades before any alert fires
MIN_TRADES = 10

# Low-confidence zone — severity is downgraded by one tier
LOW_CONFIDENCE_THRESHOLD = 20


# ---------------------------------------------------------------------------
# Backtest baselines (keyed in sentinel_state.json under backtest_baseline)
# ---------------------------------------------------------------------------

# Fallback baselines if sentinel_state.json has no backtest_baseline entry.
# These are the known baselines from backtests / MC simulations.
_DEFAULT_BASELINES: Dict[str, Dict[str, float]] = {
    "EXP-400":  {"win_rate": 78.0, "avg_pnl": 525.0,  "avg_loss": 2100.0, "mc_worst_dd_pct": 41.5},
    "EXP-401":  {"win_rate": 72.0, "avg_pnl": 825.0,  "avg_loss": 2800.0, "mc_worst_dd_pct": 10.5},
    "EXP-503":  {"win_rate": 68.0, "avg_pnl": 750.0,  "avg_loss": 2200.0, "mc_worst_dd_pct": 21.3},
    "EXP-600":  {"win_rate": 75.0, "avg_pnl": 850.0,  "avg_loss": 2500.0, "mc_worst_dd_pct": 29.1},
    "EXP-800":  {"win_rate": 78.0, "avg_pnl": 525.0,  "avg_loss": 2100.0, "mc_worst_dd_pct": 41.5},
    "EXP-1220": {"win_rate": 80.0, "avg_pnl": 1200.0, "avg_loss": 1800.0, "mc_worst_dd_pct": 16.8},
}


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

# win_rate: delta in percentage points below baseline
_WR_WARN    = 10.0   # -10pp
_WR_CRIT    = 15.0   # -15pp
_WR_HALT    = 20.0   # -20pp

# avg_loss: multiplier over baseline average loss
_AL_WARN    = 1.5
_AL_CRIT    = 2.0
_AL_HALT    = 3.0

# drawdown: fraction of MC worst-case drawdown
_DD_WARN    = 0.80   # 80% of MC worst
_DD_CRIT    = 1.00   # 100% of MC worst
_DD_HALT    = 1.10   # 110% of MC worst


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RuntimeMetrics:
    """Rolling window metrics for one experiment."""
    exp_id: str
    window_size: int = 0          # actual number of trades in window
    total_closed: int = 0         # total closed trades in DB

    win_rate: Optional[float] = None        # percentage 0-100
    avg_pnl: Optional[float] = None         # mean PnL (all trades)
    avg_loss: Optional[float] = None        # mean |PnL| of losers
    avg_win: Optional[float] = None         # mean PnL of winners
    wins: int = 0
    losses: int = 0

    peak_equity: Optional[float] = None
    trough_equity: Optional[float] = None
    current_equity: Optional[float] = None
    peak_drawdown_pct: Optional[float] = None   # as positive percentage


@dataclass
class DriftAlert:
    """A single drift alert for one metric on one experiment."""
    exp_id: str
    metric: str              # "win_rate" | "avg_loss" | "drawdown"
    severity: str            # "warning" | "critical" | "halt"
    message: str
    live_value: float
    baseline_value: float
    low_confidence: bool = False   # True when 10 <= trades < 20


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(exp_id: str) -> Optional[Path]:
    """Resolve the trades DB path for an experiment via sentinel_state.json."""
    try:
        from sentinel.state import load_state
        state = load_state()
        exp = state.get("experiments", {}).get(exp_id, {})
        paper_config = exp.get("paper_config")
        if paper_config:
            cfg_path = _PROJECT_ROOT / paper_config
            if cfg_path.exists():
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f)
                db_path = cfg.get("db_path")
                if db_path:
                    resolved = _PROJECT_ROOT / db_path
                    if resolved.exists():
                        return resolved
    except Exception as e:
        logger.debug("runtime: failed to resolve DB for %s: %s", exp_id, e)
    return None


def _get_baseline(exp_id: str) -> Optional[Dict[str, float]]:
    """
    Retrieve backtest baseline for *exp_id*.

    Checks sentinel_state.json first (under experiments.<exp_id>.backtest_baseline),
    then falls back to the hardcoded _DEFAULT_BASELINES.
    """
    try:
        from sentinel.state import load_state
        state = load_state()
        exp_state = state.get("experiments", {}).get(exp_id, {})
        baseline = exp_state.get("backtest_baseline")
        if baseline and isinstance(baseline, dict):
            return baseline
    except Exception:
        pass
    return _DEFAULT_BASELINES.get(exp_id)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_metrics(exp_id: str, window: int = WINDOW_SIZE) -> Optional[RuntimeMetrics]:
    """
    Compute rolling-window trade metrics from the experiment's trades DB.

    Returns None if the DB is unavailable or has no closed trades.
    """
    db_path = _resolve_db_path(exp_id)
    if not db_path:
        logger.warning("runtime: no DB found for %s — skipping", exp_id)
        return None

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")

    try:
        # Total closed trades
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM trades WHERE status LIKE 'closed%'"
        ).fetchone()
        total_closed = total_row["cnt"] if total_row else 0

        if total_closed == 0:
            return RuntimeMetrics(exp_id=exp_id, window_size=0, total_closed=0)

        # Rolling window: last N closed trades by exit_date
        rows = conn.execute(
            """
            SELECT pnl, exit_date FROM trades
            WHERE status LIKE 'closed%' AND pnl IS NOT NULL
            ORDER BY exit_date DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()

        if not rows:
            return RuntimeMetrics(exp_id=exp_id, window_size=0, total_closed=total_closed)

        pnls = [float(r["pnl"]) for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        metrics = RuntimeMetrics(
            exp_id=exp_id,
            window_size=len(pnls),
            total_closed=total_closed,
            win_rate=round(len(wins) / len(pnls) * 100, 1) if pnls else None,
            avg_pnl=round(sum(pnls) / len(pnls), 2) if pnls else None,
            avg_loss=round(sum(abs(p) for p in losses) / len(losses), 2) if losses else 0.0,
            avg_win=round(sum(wins) / len(wins), 2) if wins else 0.0,
            wins=len(wins),
            losses=len(losses),
        )

        # Peak-to-trough drawdown from equity curve
        # Reconstruct equity from the scanner_state table (peak_equity) or
        # from the config's account_size + cumulative PnL
        try:
            peak_row = conn.execute(
                "SELECT value FROM scanner_state WHERE key = 'peak_equity'"
            ).fetchone()
            if peak_row:
                metrics.peak_equity = float(peak_row["value"])

            # Get current equity from config account_size + total PnL
            total_pnl_row = conn.execute(
                "SELECT SUM(pnl) AS total FROM trades WHERE status LIKE 'closed%' AND pnl IS NOT NULL"
            ).fetchone()
            total_pnl = float(total_pnl_row["total"]) if total_pnl_row and total_pnl_row["total"] else 0.0

            # Read account_size from config
            cfg_path = _PROJECT_ROOT / _get_paper_config_path(exp_id)
            if cfg_path.exists():
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f)
                account_size = float(cfg.get("risk", {}).get("account_size", 100000))
            else:
                account_size = 100000.0

            metrics.current_equity = account_size + total_pnl

            if metrics.peak_equity and metrics.current_equity:
                dd = (metrics.peak_equity - metrics.current_equity) / metrics.peak_equity * 100
                metrics.peak_drawdown_pct = round(max(dd, 0.0), 2)
            elif metrics.current_equity < account_size:
                # No peak_equity in scanner_state — use account_size as peak
                metrics.peak_equity = account_size
                dd = (account_size - metrics.current_equity) / account_size * 100
                metrics.peak_drawdown_pct = round(max(dd, 0.0), 2)

        except Exception as e:
            logger.debug("runtime: equity calculation failed for %s: %s", exp_id, e)

        return metrics

    finally:
        conn.close()


def _get_paper_config_path(exp_id: str) -> str:
    """Get paper_config relative path from sentinel_state.json."""
    try:
        from sentinel.state import load_state
        state = load_state()
        return state.get("experiments", {}).get(exp_id, {}).get("paper_config", "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def _classify_severity(
    raw_severity: str,
    window_size: int,
) -> str:
    """
    Downgrade severity by one tier when window is in the low-confidence zone
    (10-19 trades).  Below MIN_TRADES, return empty string (suppress alert).
    """
    if window_size < MIN_TRADES:
        return ""  # suppress

    if window_size < LOW_CONFIDENCE_THRESHOLD:
        # Downgrade by one tier
        downgrades = {"halt": "critical", "critical": "warning", "warning": "info"}
        return downgrades.get(raw_severity, raw_severity)

    return raw_severity


def detect_drift(
    metrics: RuntimeMetrics,
    baseline: Dict[str, float],
) -> List[DriftAlert]:
    """
    Compare live metrics against backtest baseline and return any alerts.

    Returns an empty list when everything is within tolerance.
    """
    alerts: List[DriftAlert] = []
    exp_id = metrics.exp_id
    n = metrics.window_size
    low_conf = MIN_TRADES <= n < LOW_CONFIDENCE_THRESHOLD

    # --- Win rate drift ---
    if metrics.win_rate is not None and "win_rate" in baseline:
        bl_wr = baseline["win_rate"]
        delta = bl_wr - metrics.win_rate  # positive = live is worse

        if delta >= _WR_HALT:
            raw = "halt"
        elif delta >= _WR_CRIT:
            raw = "critical"
        elif delta >= _WR_WARN:
            raw = "warning"
        else:
            raw = ""

        if raw:
            sev = _classify_severity(raw, n)
            if sev and sev != "info":
                alerts.append(DriftAlert(
                    exp_id=exp_id,
                    metric="win_rate",
                    severity=sev,
                    message=(
                        f"Win rate drift: live {metrics.win_rate:.1f}% vs "
                        f"baseline {bl_wr:.1f}% (Δ {-delta:+.1f}pp, "
                        f"{n} trades{'*' if low_conf else ''})"
                    ),
                    live_value=metrics.win_rate,
                    baseline_value=bl_wr,
                    low_confidence=low_conf,
                ))

    # --- Average loss drift ---
    if metrics.avg_loss is not None and metrics.avg_loss > 0 and "avg_loss" in baseline:
        bl_al = baseline["avg_loss"]
        ratio = metrics.avg_loss / bl_al if bl_al > 0 else 0.0

        if ratio >= _AL_HALT:
            raw = "halt"
        elif ratio >= _AL_CRIT:
            raw = "critical"
        elif ratio >= _AL_WARN:
            raw = "warning"
        else:
            raw = ""

        if raw:
            sev = _classify_severity(raw, n)
            if sev and sev != "info":
                alerts.append(DriftAlert(
                    exp_id=exp_id,
                    metric="avg_loss",
                    severity=sev,
                    message=(
                        f"Avg loss drift: live ${metrics.avg_loss:,.0f} vs "
                        f"baseline ${bl_al:,.0f} ({ratio:.1f}x, "
                        f"{metrics.losses} losers in {n} trades{'*' if low_conf else ''})"
                    ),
                    live_value=metrics.avg_loss,
                    baseline_value=bl_al,
                    low_confidence=low_conf,
                ))

    # --- Drawdown drift ---
    if metrics.peak_drawdown_pct is not None and "mc_worst_dd_pct" in baseline:
        bl_dd = baseline["mc_worst_dd_pct"]  # e.g. 41.5 means -41.5%
        if bl_dd > 0:
            dd_ratio = metrics.peak_drawdown_pct / bl_dd

            if dd_ratio >= _DD_HALT:
                raw = "halt"
            elif dd_ratio >= _DD_CRIT:
                raw = "critical"
            elif dd_ratio >= _DD_WARN:
                raw = "warning"
            else:
                raw = ""

            if raw:
                sev = _classify_severity(raw, n)
                if sev and sev != "info":
                    alerts.append(DriftAlert(
                        exp_id=exp_id,
                        metric="drawdown",
                        severity=sev,
                        message=(
                            f"Drawdown drift: live -{metrics.peak_drawdown_pct:.1f}% vs "
                            f"MC worst -{bl_dd:.1f}% ({dd_ratio:.0%} of limit"
                            f"{'*' if low_conf else ''})"
                        ),
                        live_value=metrics.peak_drawdown_pct,
                        baseline_value=bl_dd,
                        low_confidence=low_conf,
                    ))

    return alerts


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def check_runtime_drift(
    exp_id: str,
    record_snapshot: bool = True,
) -> List[DriftAlert]:
    """
    Full Gate 8 check for one experiment.

    1. Compute rolling 30-trade metrics from trades DB
    2. Compare against backtest baseline
    3. Optionally record snapshot to sentinel.db
    4. Return list of drift alerts (empty = healthy)

    If *record_snapshot* is True (default), writes the rolling metrics
    to the experiment_snapshots table in sentinel.db so the daily report
    and HTML dashboards can display trend data.
    """
    baseline = _get_baseline(exp_id)
    if not baseline:
        logger.info("runtime: no baseline for %s — skipping drift check", exp_id)
        return []

    metrics = compute_metrics(exp_id)
    if not metrics or metrics.window_size == 0:
        logger.info("runtime: no closed trades for %s — skipping", exp_id)
        return []

    # Detect drift
    alerts = detect_drift(metrics, baseline)

    # Record snapshot
    if record_snapshot:
        try:
            from sentinel.history import SentinelDB
            db = SentinelDB()
            db.record_snapshot(
                exp_id,
                equity=metrics.current_equity,
                open_positions=0,  # runtime check doesn't know open positions
                total_trades=metrics.total_closed,
                win_rate=metrics.win_rate,
                notes=(
                    f"Gate8 rolling-{metrics.window_size}: "
                    f"WR={metrics.win_rate:.1f}% "
                    f"avgPnL=${metrics.avg_pnl:,.0f} "
                    f"avgLoss=${metrics.avg_loss:,.0f} "
                    f"DD={metrics.peak_drawdown_pct:.1f}%"
                    if metrics.win_rate is not None and metrics.avg_pnl is not None
                    and metrics.avg_loss is not None and metrics.peak_drawdown_pct is not None
                    else f"Gate8 rolling-{metrics.window_size}"
                ),
            )
        except Exception as e:
            logger.warning("runtime: snapshot write failed for %s: %s", exp_id, e)

    # Log alerts
    for alert in alerts:
        log_fn = logger.critical if alert.severity == "halt" else (
            logger.warning if alert.severity == "critical" else logger.info
        )
        log_fn("GATE8 %s [%s] %s: %s", exp_id, alert.severity.upper(), alert.metric, alert.message)

    return alerts


def check_all_runtime_drift(
    record_snapshot: bool = True,
    halt_on_breach: bool = False,
) -> Dict[str, List[DriftAlert]]:
    """
    Run Gate 8 for all active experiments.

    Returns a dict mapping experiment ID to its list of drift alerts.
    If *halt_on_breach* is True, experiments with halt-severity alerts
    are halted in sentinel_state.json.
    """
    try:
        from sentinel.state import load_state, set_halt
        state = load_state()
    except Exception as e:
        logger.error("runtime: cannot load sentinel_state.json: %s", e)
        return {}

    active_ids = [
        eid for eid, exp in state.get("experiments", {}).items()
        if exp.get("status") == "active"
    ]

    all_alerts: Dict[str, List[DriftAlert]] = {}

    for exp_id in sorted(active_ids):
        alerts = check_runtime_drift(exp_id, record_snapshot=record_snapshot)
        all_alerts[exp_id] = alerts

        # Enforce halt if requested
        if halt_on_breach and alerts:
            halt_alerts = [a for a in alerts if a.severity == "halt"]
            if halt_alerts:
                reason = "; ".join(a.message for a in halt_alerts)
                try:
                    set_halt(exp_id, f"Gate8 runtime drift halt: {reason[:200]}")
                    logger.critical(
                        "GATE8: HALTED %s — %d metric(s) breached halt threshold",
                        exp_id, len(halt_alerts),
                    )
                    # Record halt alert in sentinel.db
                    from sentinel.history import SentinelDB
                    db = SentinelDB()
                    db.record_alert(
                        "critical",
                        f"Gate8 HALT: {reason[:200]}",
                        experiment_id=exp_id,
                    )
                except Exception as e:
                    logger.error("runtime: failed to halt %s: %s", exp_id, e)

    return all_alerts


# ---------------------------------------------------------------------------
# Pretty-print for CLI / daily report integration
# ---------------------------------------------------------------------------


def format_drift_report(
    all_alerts: Dict[str, List[DriftAlert]],
    all_metrics: Optional[Dict[str, RuntimeMetrics]] = None,
) -> str:
    """
    Format Gate 8 results as a human-readable text block.

    Suitable for inclusion in the daily Telegram message or CLI output.
    """
    lines: List[str] = []
    lines.append("<b>Gate 8 — Runtime Drift</b>")

    if not all_alerts:
        lines.append("  <i>No active experiments to check.</i>")
        return "\n".join(lines)

    any_alerts = False
    for exp_id in sorted(all_alerts):
        alerts = all_alerts[exp_id]
        m = all_metrics.get(exp_id) if all_metrics else None

        if not alerts:
            # Clean — show summary metrics if available
            if m and m.win_rate is not None:
                lines.append(
                    f"  ✅ {exp_id}: WR={m.win_rate:.0f}% "
                    f"avgL=${m.avg_loss:,.0f} DD={m.peak_drawdown_pct:.1f}% "
                    f"({m.window_size}t)"
                )
            else:
                lines.append(f"  ✅ {exp_id}: within tolerance")
            continue

        any_alerts = True
        for a in alerts:
            icon = {"halt": "🛑", "critical": "🔴", "warning": "⚠️"}.get(a.severity, "❓")
            conf = " <i>(low-confidence)</i>" if a.low_confidence else ""
            lines.append(f"  {icon} {exp_id}: {a.message}{conf}")

    if not any_alerts:
        lines.append("  <i>All experiments within baseline tolerance.</i>")

    return "\n".join(lines)
