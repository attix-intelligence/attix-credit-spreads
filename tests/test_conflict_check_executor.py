"""WS-3 tests: broker-agnostic pre-flight position-conflict check.

The conflict gate previously ran only `if self.alpaca:` — with the executor
sink (Tradier live path) it silently skipped, allowing strike collisions.
Now it runs whenever a live position source exists (Alpaca OR executor sink),
with executor /v1/portfolio/positions dicts (``quantity``) normalized to the
Alpaca shape (``qty``) inside _get_cached_positions.
"""
from __future__ import annotations

import pytest

from execution.execution_engine import ExecutionEngine, _build_occ_symbol


class FakeExecutorSink:
    """Mimics ExecutorOrderSink.get_positions() → raw executor position dicts."""

    def __init__(self, positions=None, error=None):
        self._positions = positions or []
        self._error = error
        self.calls = 0

    def get_positions(self):
        self.calls += 1
        if self._error:
            raise self._error
        return self._positions


def _executor_pos(occ_symbol: str, quantity: int = -2):
    """Executor Position response shape (executor/models/responses.py)."""
    return {
        "symbol": occ_symbol,
        "security_type": "option",
        "quantity": quantity,
        "average_cost": 1.75,
        "current_price": 1.60,
        "market_value": -320.0,
        "unrealized_pnl": 30.0,
        "unrealized_pnl_pct": 8.6,
    }


def _engine(tmp_path, sink=None, alpaca=None):
    return ExecutionEngine(
        alpaca_provider=alpaca,
        db_path=str(tmp_path / "test_conflict.db"),
        config={"risk": {"drawdown_cb_pct": 0}},
        executor_sink=sink,
    )


BULL_PUT_OPP = {
    "ticker": "SPY",
    "type": "bull_put",
    "expiration": "2026-07-17",
    "short_strike": 630.0,
    "long_strike": 618.0,
    "credit": 1.75,
    "contracts": 2,
}

CONDOR_OPP = {
    "ticker": "SPY",
    "type": "iron_condor",
    "expiration": "2026-07-17",
    "short_strike": 630.0,
    "long_strike": 618.0,
    "put_short_strike": 630.0,
    "put_long_strike": 618.0,
    "call_short_strike": 650.0,
    "call_long_strike": 662.0,
    "credit": 3.20,
    "contracts": 1,
}


# ---------------------------------------------------------------------------
# _get_cached_positions: executor branch + normalization
# ---------------------------------------------------------------------------

def test_executor_positions_normalized_to_alpaca_shape(tmp_path):
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    sink = FakeExecutorSink([_executor_pos(occ, quantity=-2)])
    engine = _engine(tmp_path, sink=sink)

    positions = engine._get_cached_positions()
    assert positions == [{"symbol": occ, "qty": -2}]


def test_positions_cache_avoids_refetch(tmp_path):
    sink = FakeExecutorSink([])
    engine = _engine(tmp_path, sink=sink)
    engine._get_cached_positions()
    engine._get_cached_positions()
    assert sink.calls == 1


def test_no_position_source_returns_none(tmp_path):
    engine = _engine(tmp_path, sink=None, alpaca=None)
    assert engine._get_cached_positions() is None


def test_alpaca_takes_precedence_over_sink(tmp_path):
    class FakeAlpaca:
        def get_positions(self):
            return [{"symbol": "SPY", "qty": 100}]

    sink = FakeExecutorSink([_executor_pos("QQQ")])
    engine = _engine(tmp_path, sink=sink, alpaca=FakeAlpaca())
    assert engine._get_cached_positions() == [{"symbol": "SPY", "qty": 100}]
    assert sink.calls == 0


# ---------------------------------------------------------------------------
# _check_position_conflict via executor positions
# ---------------------------------------------------------------------------

def test_conflict_detected_on_short_leg(tmp_path):
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    engine = _engine(tmp_path, sink=FakeExecutorSink([_executor_pos(occ)]))
    assert engine._check_position_conflict(BULL_PUT_OPP) == occ


def test_conflict_detected_on_condor_call_wing(tmp_path):
    occ = _build_occ_symbol("SPY", "2026-07-17", 662.0, "call")
    engine = _engine(tmp_path, sink=FakeExecutorSink([_executor_pos(occ)]))
    assert engine._check_position_conflict(CONDOR_OPP) == occ


def test_no_conflict_different_strike_or_expiry(tmp_path):
    positions = [
        _executor_pos(_build_occ_symbol("SPY", "2026-07-17", 500.0, "put")),
        _executor_pos(_build_occ_symbol("SPY", "2026-08-21", 630.0, "put")),
        _executor_pos(_build_occ_symbol("QQQ", "2026-07-17", 630.0, "put")),
    ]
    engine = _engine(tmp_path, sink=FakeExecutorSink(positions))
    assert engine._check_position_conflict(BULL_PUT_OPP) is None


def test_fetch_failure_fails_open(tmp_path):
    engine = _engine(tmp_path, sink=FakeExecutorSink(error=RuntimeError("executor down")))
    assert engine._get_cached_positions() is None
    assert engine._check_position_conflict(BULL_PUT_OPP) is None


# ---------------------------------------------------------------------------
# Gate in submit_opportunity
# ---------------------------------------------------------------------------

def test_submit_blocked_by_executor_conflict(tmp_path):
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    engine = _engine(tmp_path, sink=FakeExecutorSink([_executor_pos(occ)]))

    result = engine.submit_opportunity(dict(BULL_PUT_OPP))
    assert result["status"] == "position_conflict"
    assert occ in result["message"]

    # Conflict fires before the DB write — no pending_open record left behind.
    from shared.database import get_trade_by_id
    assert get_trade_by_id(result["client_order_id"], path=engine.db_path) is None


def test_submit_dry_run_skips_conflict_check(tmp_path, monkeypatch):
    engine = _engine(tmp_path, sink=None, alpaca=None)

    def _boom(opp):
        raise AssertionError("conflict check must not run in dry-run mode")

    monkeypatch.setattr(engine, "_check_position_conflict", _boom)
    result = engine.submit_opportunity(dict(BULL_PUT_OPP))
    assert result["status"] != "position_conflict"


# ---------------------------------------------------------------------------
# Tradier-route position shape (Phase 2 sandbox finding): the executor's
# /v1/portfolio/positions returns the UNDERLYING in ``symbol`` with the
# contract split into option_type/strike/expiration — must be rebuilt to OCC.
# ---------------------------------------------------------------------------

def _tradier_pos(strike, opt_type, expiration="2026-07-17", quantity=-2, ticker="SPY"):
    return {
        "symbol": ticker,
        "security_type": "option",
        "quantity": quantity,
        "average_cost": 6.11,
        "current_price": 0.0,
        "market_value": 0.0,
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0,
        "option_type": opt_type,
        "strike": strike,
        "expiration": expiration,
    }


def test_tradier_shape_position_rebuilt_to_occ(tmp_path):
    engine = _engine(tmp_path, sink=FakeExecutorSink([_tradier_pos(630.0, "put")]))
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    assert engine._get_cached_positions() == [{"symbol": occ, "qty": -2}]


def test_conflict_detected_on_tradier_shape_position(tmp_path):
    engine = _engine(tmp_path, sink=FakeExecutorSink([_tradier_pos(630.0, "put")]))
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    assert engine._check_position_conflict(BULL_PUT_OPP) == occ


def test_occ_shape_position_passes_through_unchanged(tmp_path):
    occ = _build_occ_symbol("SPY", "2026-07-17", 630.0, "put")
    pos = _executor_pos(occ)
    # even with option fields present, an already-OCC symbol is not rebuilt
    pos.update({"option_type": "put", "strike": 630.0, "expiration": "2026-07-17"})
    engine = _engine(tmp_path, sink=FakeExecutorSink([pos]))
    assert engine._get_cached_positions() == [{"symbol": occ, "qty": -2}]


def test_equity_position_passes_through(tmp_path):
    pos = {"symbol": "SPY", "security_type": "equity", "quantity": 100}
    engine = _engine(tmp_path, sink=FakeExecutorSink([pos]))
    assert engine._get_cached_positions() == [{"symbol": "SPY", "qty": 100}]
