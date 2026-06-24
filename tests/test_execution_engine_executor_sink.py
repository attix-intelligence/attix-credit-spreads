"""Tests for ExecutionEngine's executor-sink dispatch path (V8A-TRADIER).

Covers the NEW branch added in feat/v8a-tradier-executor-sink-last-mile:

  * routing to ExecutorOrderSink when ``executor_sink`` is supplied
  * RTH market-hours guard (broker-agnostic, NYSE 09:30-16:00 ET)
  * default-OFF ``live_submit`` gate (cfg or env LIVE_SUBMIT)
  * Phase-1 ``risk.max_contracts`` belt-and-suspenders cap
  * the Alpaca path is byte-for-byte untouched when no executor sink is wired
  * the original DRY RUN path still fires when both sinks are None

The Alpaca-path-unchanged test is the load-bearing safety claim of the PR.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── helpers ─────────────────────────────────────────────────────────────────

# 2026-06-23 14:00 UTC = 10:00 ET (Tue, DST) — solidly inside NYSE RTH.
_INSIDE_RTH = datetime(2026, 6, 23, 14, 0, 0, tzinfo=timezone.utc)
# 2026-06-23 22:00 UTC = 18:00 ET (Tue, DST) — well after the close.
_AFTER_HOURS = datetime(2026, 6, 23, 22, 0, 0, tzinfo=timezone.utc)


def _opp(contracts: int = 1, spread_type: str = "bear_call") -> Dict[str, Any]:
    return {
        "ticker": "SPY",
        "type": spread_type,
        "expiration": "2026-07-18",
        "short_strike": 545.0,
        "long_strike": 557.0,  # bear_call width $12 (matches v8a-tradier.yaml)
        "credit": 3.22,
        "contracts": contracts,
    }


def _config(*, live_submit: Optional[bool] = None, max_contracts: int = 1) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "experiment_id": "EXP-V8A-TRADIER",
        "risk": {"max_contracts": max_contracts, "account_size": 100_000},
        "tradier_live": {
            "enabled": True,
            "account_id": "tradier_6YA42569",
            "account_type": "live",
            "sink_type": "executor",
        },
    }
    if live_submit is not None:
        cfg["live_submit"] = live_submit
    return cfg


def _build_mock_sink() -> MagicMock:
    sink = MagicMock(name="ExecutorOrderSink")
    sink.submit.return_value = {
        "status": "submitted",
        "order_id": "exec-ord-42",
        "broker_order_id": "bk-99",
        "message": "ok",
    }
    return sink


@pytest.fixture(autouse=True)
def _clear_live_submit_env(monkeypatch):
    """Ensure no LIVE_SUBMIT env var leaks between tests."""
    monkeypatch.delenv("LIVE_SUBMIT", raising=False)


# ── 1) Happy path: routing + submit ─────────────────────────────────────────

def test_executor_routing_when_sink_present_and_gate_on(tmp_path):
    from execution.execution_engine import ExecutionEngine

    sink = _build_mock_sink()
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=True, max_contracts=1),
        executor_sink=sink,
    )

    with patch("execution.execution_engine.is_rth_now", create=True, return_value=True), \
         patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=1, spread_type="bear_call"))

    assert result["status"] == "submitted", f"unexpected result: {result}"
    assert result["order_id"] == "exec-ord-42"
    assert result["broker_order_id"] == "bk-99"
    sink.submit.assert_called_once()

    # The intent the sink received: structure preserved, sell-leg short, buy-leg long.
    intent = sink.submit.call_args.args[0]
    assert intent.structure == "bear_call"
    assert intent.symbol == "SPY"
    assert intent.contracts == 1
    sell_legs = [leg for leg in intent.legs if leg.side == "sell"]
    buy_legs = [leg for leg in intent.legs if leg.side == "buy"]
    assert len(sell_legs) == 1 and sell_legs[0].strike == 545.0
    assert len(buy_legs) == 1 and buy_legs[0].strike == 557.0


# ── 2) RTH guard blocks after-hours submits ─────────────────────────────────

def test_executor_path_blocked_after_hours(tmp_path):
    from execution.execution_engine import ExecutionEngine

    sink = _build_mock_sink()
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=True),
        executor_sink=sink,
    )

    # Patch the helper as imported into market_hours; engine imports it lazily.
    with patch("execution.market_hours.is_rth_now", return_value=False):
        result = engine.submit_opportunity(_opp(contracts=1))

    assert result["status"] == "market_closed"
    assert "RTH" in result["message"]
    sink.submit.assert_not_called()


# ── 3) Default-OFF live_submit gate ─────────────────────────────────────────

def test_executor_path_dry_runs_when_live_submit_off(tmp_path, caplog):
    from execution.execution_engine import ExecutionEngine

    sink = _build_mock_sink()
    # NO live_submit in config — default is OFF.
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=None),
        executor_sink=sink,
    )

    with patch("execution.market_hours.is_rth_now", return_value=True), \
         caplog.at_level("INFO"):
        result = engine.submit_opportunity(_opp(contracts=1))

    assert result["status"] == "dry_run"
    assert result["message"] == "live_submit gate off"
    sink.submit.assert_not_called()
    # Log line preserves the [DRY RUN — live_submit=false] tag for log scrapers.
    assert any("[DRY RUN — live_submit=false]" in rec.message for rec in caplog.records), \
        "expected log line tagged '[DRY RUN — live_submit=false]'"


def test_executor_path_dry_runs_when_live_submit_off_env_unset(tmp_path, monkeypatch):
    """Empty LIVE_SUBMIT env (or 'false') keeps the gate OFF."""
    from execution.execution_engine import ExecutionEngine

    monkeypatch.setenv("LIVE_SUBMIT", "false")
    sink = _build_mock_sink()
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=None),
        executor_sink=sink,
    )
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=1))
    assert result["status"] == "dry_run"
    sink.submit.assert_not_called()


def test_executor_path_submits_when_live_submit_env_on(tmp_path, monkeypatch):
    """LIVE_SUBMIT=true env flips the gate even if YAML has no key."""
    from execution.execution_engine import ExecutionEngine

    monkeypatch.setenv("LIVE_SUBMIT", "true")
    sink = _build_mock_sink()
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=None),
        executor_sink=sink,
    )
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=1))
    assert result["status"] == "submitted"
    sink.submit.assert_called_once()


# ── 4) Phase-1 contracts cap ────────────────────────────────────────────────

def test_executor_path_blocks_when_contracts_exceed_phase1_cap(tmp_path):
    from execution.execution_engine import ExecutionEngine

    sink = _build_mock_sink()
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        config=_config(live_submit=True, max_contracts=1),
        executor_sink=sink,
    )
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=2))

    assert result["status"] == "error"
    assert "phase1 cap" in result["message"].lower()
    sink.submit.assert_not_called()


# ── 5) Alpaca path is BYTE-IDENTICAL when no executor sink wired ────────────

def test_alpaca_path_unchanged_when_no_executor_sink(tmp_path):
    """Load-bearing safety claim: the existing Alpaca submit path must NOT
    consult the new RTH helper, must take Alpaca's get_market_clock, and must
    call submit_credit_spread.  All assertions sanity-checked against the
    unchanged existing test in tests/test_execution_fixes.py.
    """
    from execution.execution_engine import ExecutionEngine

    mock_alpaca = MagicMock()
    mock_alpaca.submit_credit_spread.return_value = {
        "status": "submitted", "order_id": "ord-alpaca",
    }
    mock_alpaca.get_account.return_value = {"equity": 100_000.0, "portfolio_value": 100_000.0}
    mock_alpaca.get_market_clock.return_value = {"is_open": True}
    mock_alpaca.get_positions.return_value = []

    engine = ExecutionEngine(
        alpaca_provider=mock_alpaca,
        db_path=str(tmp_path / "test.db"),
        executor_sink=None,
    )

    with patch("execution.market_hours.is_rth_now", return_value=False) as mock_rth:
        result = engine.submit_opportunity(_opp(contracts=1, spread_type="bull_put"))

    # Existing Alpaca path was taken — submit_credit_spread called, market clock checked.
    assert result["status"] == "submitted"
    mock_alpaca.submit_credit_spread.assert_called_once()
    mock_alpaca.get_market_clock.assert_called()
    # The new RTH helper must NOT have been consulted from the Alpaca path,
    # even though we forced it to return False — proves the branch divergence.
    mock_rth.assert_not_called()


# ── 6) Original DRY RUN path still fires when both sinks are None ──────────

def test_dry_run_unchanged_when_no_provider(tmp_path, caplog):
    """The pre-existing dry-run log line (NOT the new live_submit one) must
    fire when no executor sink AND no alpaca provider are configured."""
    from execution.execution_engine import ExecutionEngine

    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test.db"),
        executor_sink=None,
    )
    with caplog.at_level("INFO"):
        result = engine.submit_opportunity(_opp(contracts=1, spread_type="bull_put"))

    assert result["status"] == "dry_run"
    assert result["message"] == "alpaca not configured"
    # Pre-existing log shape: "ExecutionEngine [DRY RUN]: would submit SPY bull_put ..."
    msgs = [rec.message for rec in caplog.records]
    assert any("[DRY RUN]" in m and "[DRY RUN — live_submit=false]" not in m for m in msgs), \
        f"expected the pre-existing '[DRY RUN]' log line; got: {msgs}"


# ── 7) Executor sink error path → status='error' + DB mark ─────────────────

def test_executor_sink_returning_error_status_marks_failed_open(tmp_path):
    from execution.execution_engine import ExecutionEngine
    from shared.database import get_trades

    sink = MagicMock(name="ExecutorOrderSink")
    sink.submit.return_value = {
        "status": "error", "message": "validation failed: net_credit must be positive",
    }

    db_path = str(tmp_path / "test.db")
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=db_path,
        config=_config(live_submit=True),
        executor_sink=sink,
    )
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=1))

    assert result["status"] == "error"
    assert "executor submit failed" in result["message"]
    trades = get_trades(path=db_path)
    assert len(trades) == 1
    assert trades[0]["status"] == "failed_open"


def test_executor_sink_raising_exception_marks_failed_open(tmp_path):
    from execution.execution_engine import ExecutionEngine
    from shared.database import get_trades

    sink = MagicMock(name="ExecutorOrderSink")
    sink.submit.side_effect = RuntimeError("connection refused")

    db_path = str(tmp_path / "test.db")
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=db_path,
        config=_config(live_submit=True),
        executor_sink=sink,
    )
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(_opp(contracts=1))

    assert result["status"] == "error"
    assert "connection refused" in result["message"]
    trades = get_trades(path=db_path)
    assert len(trades) == 1
    assert trades[0]["status"] == "failed_open"
