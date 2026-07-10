"""FIX #2 tests: live entry-order cancel/replace reprice ladder (executor route).

Covers:
  * ExecutionEngine persists entry-order tracking fields on executor submit
  * PositionMonitor._check_entry_orders ladder behaviour:
      - no action within the reprice interval
      - cancel/replace one step down with a NEW idempotency key per replace
      - floor clamp on the last rung; give-up at the floor / after max_steps
      - cancel failure blocks the replacement (never two live entry orders)
      - resubmit failure fails the trade (no phantom pending_open)
      - filled → promoted to open; broker-terminal → failed_open
      - partial fill is never cancelled
  * credit-floor derivation (vertical vs iron condor, absolute override)

Mocked broker only — FakeEntrySink records calls; no real HTTP anywhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from execution.position_monitor import PositionMonitor
from shared.database import get_trade_by_id, upsert_trade


EXP = "2026-07-24"


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeEntrySink:
    """Stub of ExecutorOrderSink for entry-ladder tests. Records every call."""

    def __init__(
        self,
        order_status: Optional[Dict] = None,
        submit_result: Optional[Dict] = None,
        cancel_raises: bool = False,
    ) -> None:
        # Raw executor OrderStatusResponse shape (what get_order_status returns).
        self.order_status = order_status or {"status": "submitted", "filled_quantity": 0}
        self.submit_result = submit_result
        self.cancel_raises = cancel_raises
        self.cancel_calls: List[str] = []
        self.submit_calls: List[Any] = []
        self._order_seq = 0

    def get_order_status(self, order_id: str) -> Dict:
        return self.order_status

    def cancel_order(self, order_id: str) -> Dict:
        if self.cancel_raises:
            raise RuntimeError("executor 502: cancel failed")
        self.cancel_calls.append(order_id)
        return {"status": "cancelled"}

    def submit(self, intent) -> Dict:
        self.submit_calls.append(intent)
        if self.submit_result is not None:
            return self.submit_result
        self._order_seq += 1
        return {"status": "submitted", "order_id": f"exec-ord-replace-{self._order_seq}"}

    def get_positions(self) -> List[Dict]:
        return []


# ── helpers ──────────────────────────────────────────────────────────────────

def _config(**reprice_overrides) -> Dict:
    reprice = {"enabled": True, "interval_minutes": 3, "step": 0.05, "max_steps": 6}
    reprice.update(reprice_overrides)
    return {
        "risk": {
            "profit_target": 55,
            "stop_loss_multiplier": 1.25,
            "min_credit_pct": 5,
        },
        "strategy": {"manage_dte": 0, "iron_condor": {"enabled": True}},
        "execution": {"entry_reprice": reprice},
    }


def _monitor(tmp_path, sink, **reprice_overrides) -> PositionMonitor:
    return PositionMonitor(
        alpaca_provider=None,
        config=_config(**reprice_overrides),
        db_path=str(tmp_path / "reprice_test.db"),
        executor_sink=sink,
    )


def _seed_pending(
    monitor: PositionMonitor,
    *,
    trade_id: str = "cs-exp800-t1",
    strategy_type: str = "bull_put",
    credit: float = 3.22,
    limit_credit: Optional[float] = 3.22,
    reprice_count: int = 0,
    age_minutes: float = 10.0,
    **extra,
) -> Dict:
    submitted_at = (
        datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    ).isoformat()
    trade = dict(
        id=trade_id,
        ticker="SPY",
        strategy_type=strategy_type,
        status="pending_open",
        short_strike=630.0,
        long_strike=618.0,  # width $12 → vertical floor = 12 × 5% = 0.60
        expiration=EXP,
        credit=credit,
        contracts=1,
        entry_date=submitted_at,
        entry_order_id="exec-ord-orig",
        entry_order_submitted_at=submitted_at,
        entry_limit_credit=limit_credit,
        entry_reprice_count=reprice_count,
    )
    trade.update(extra)
    upsert_trade(trade, source="execution", path=monitor.db_path)
    return trade


# ── engine persists tracking fields ──────────────────────────────────────────

def test_engine_persists_entry_order_tracking(tmp_path):
    from execution.execution_engine import ExecutionEngine

    sink = MagicMock(name="ExecutorOrderSink")
    sink.submit.return_value = {
        "status": "submitted", "order_id": "exec-ord-42",
        "broker_order_id": "bk-99", "message": "ok",
    }
    db_path = str(tmp_path / "engine.db")
    engine = ExecutionEngine(
        alpaca_provider=None,
        db_path=db_path,
        config={
            "experiment_id": "EXP-800-TRADIER",
            "live_submit": True,
            "risk": {"max_contracts": 1, "account_size": 100_000},
            "tradier_live": {"enabled": True, "sink_type": "executor"},
        },
        executor_sink=sink,
    )
    opp = {
        "ticker": "SPY", "type": "bull_put", "expiration": EXP,
        "short_strike": 630.0, "long_strike": 618.0,
        "credit": 3.22, "contracts": 1,
    }
    with patch("execution.market_hours.is_rth_now", return_value=True):
        result = engine.submit_opportunity(opp)

    assert result["status"] == "submitted"
    rec = get_trade_by_id(result["client_order_id"], path=db_path)
    assert rec is not None
    assert rec["status"] == "pending_open"
    assert rec["entry_order_id"] == "exec-ord-42"
    assert rec["entry_reprice_count"] == 0
    assert rec["entry_limit_credit"] == pytest.approx(3.22)
    assert rec.get("entry_order_submitted_at")


# ── ladder behaviour ─────────────────────────────────────────────────────────

def test_no_reprice_within_interval(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, age_minutes=1.0)

    monitor._check_entry_orders()

    assert sink.cancel_calls == []
    assert sink.submit_calls == []
    assert get_trade_by_id("cs-exp800-t1", path=monitor.db_path)["status"] == "pending_open"


def test_reprice_steps_down_with_new_idempotency_key(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, limit_credit=3.22)

    monitor._check_entry_orders()

    assert sink.cancel_calls == ["exec-ord-orig"]
    assert len(sink.submit_calls) == 1
    intent = sink.submit_calls[0]
    # NEW idempotency key per replace: the stream carries the rung suffix, and
    # the sink derives its idempotency_key from the stream.
    assert intent.stream == "cs-exp800-t1-r1"
    assert intent.est_credit == pytest.approx(3.17)  # 3.22 - 0.05
    assert intent.structure == "bull_put"
    sell = [l for l in intent.legs if l.side == "sell"][0]
    buy = [l for l in intent.legs if l.side == "buy"][0]
    assert sell.strike == 630.0 and buy.strike == 618.0

    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "pending_open"
    assert rec["entry_order_id"] == "exec-ord-replace-1"
    assert rec["entry_limit_credit"] == pytest.approx(3.17)
    assert rec["entry_reprice_count"] == 1


def test_successive_replaces_use_distinct_keys(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, limit_credit=3.22)

    monitor._check_entry_orders()
    # Age the replacement past the interval, then run the ladder again.
    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    rec["entry_order_submitted_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).isoformat()
    upsert_trade(rec, source="execution", path=monitor.db_path)
    monitor._check_entry_orders()

    streams = [i.stream for i in sink.submit_calls]
    assert streams == ["cs-exp800-t1-r1", "cs-exp800-t1-r2"]
    credits = [i.est_credit for i in sink.submit_calls]
    assert credits == [pytest.approx(3.17), pytest.approx(3.12)]
    assert sink.cancel_calls == ["exec-ord-orig", "exec-ord-replace-1"]


def test_floor_clamps_last_step(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, limit_credit=0.62)  # floor 0.60; 0.62-0.05 would breach it

    monitor._check_entry_orders()

    assert len(sink.submit_calls) == 1
    assert sink.submit_calls[0].est_credit == pytest.approx(0.60)


def test_gives_up_at_floor(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, limit_credit=0.60)  # already sitting at the floor

    monitor._check_entry_orders()

    assert sink.cancel_calls == ["exec-ord-orig"]
    assert sink.submit_calls == []  # hard floor: never replace below min_credit
    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "failed_open"
    assert "entry_reprice_gave_up" in rec["exit_reason"]


def test_gives_up_after_max_steps(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, limit_credit=3.00, reprice_count=6)

    monitor._check_entry_orders()

    assert sink.submit_calls == []
    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "failed_open"
    assert "entry_reprice_gave_up" in rec["exit_reason"]


def test_cancel_failure_blocks_replacement(tmp_path):
    sink = FakeEntrySink(cancel_raises=True)
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor)

    monitor._check_entry_orders()

    # Never submit a replacement while the original may still be live.
    assert sink.submit_calls == []
    assert get_trade_by_id("cs-exp800-t1", path=monitor.db_path)["status"] == "pending_open"


def test_resubmit_failure_fails_trade(tmp_path):
    sink = FakeEntrySink(submit_result={"status": "error", "message": "executor 500"})
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor)

    monitor._check_entry_orders()

    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "failed_open"
    assert "entry_reprice_resubmit_failed" in rec["exit_reason"]


def test_filled_promotes_to_open(tmp_path):
    sink = FakeEntrySink(
        order_status={"status": "filled", "filled_quantity": 1, "average_fill_price": 3.05}
    )
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor)

    monitor._check_entry_orders()

    assert sink.cancel_calls == [] and sink.submit_calls == []
    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "open"
    assert rec["entry_fill_credit"] == pytest.approx(3.05)


def test_broker_terminal_status_fails_entry(tmp_path):
    sink = FakeEntrySink(order_status={"status": "rejected", "filled_quantity": 0})
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor)

    monitor._check_entry_orders()

    rec = get_trade_by_id("cs-exp800-t1", path=monitor.db_path)
    assert rec["status"] == "failed_open"
    assert "entry_rejected" in rec["exit_reason"]


def test_partial_fill_never_cancelled(tmp_path):
    sink = FakeEntrySink(
        order_status={"status": "partially_filled", "filled_quantity": 1}
    )
    monitor = _monitor(tmp_path, sink)
    _seed_pending(monitor, contracts=2)

    monitor._check_entry_orders()

    assert sink.cancel_calls == [] and sink.submit_calls == []
    assert get_trade_by_id("cs-exp800-t1", path=monitor.db_path)["status"] == "pending_open"


def test_untracked_pending_open_ignored(tmp_path):
    """Pre-FIX#2 records (no entry_order_id) are left to the existing recovery paths."""
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    upsert_trade(
        dict(
            id="legacy-1", ticker="SPY", strategy_type="bull_put",
            status="pending_open", short_strike=630.0, long_strike=618.0,
            expiration=EXP, credit=1.0, contracts=1,
            entry_date=datetime.now(timezone.utc).isoformat(),
        ),
        source="execution", path=monitor.db_path,
    )

    monitor._check_entry_orders()

    assert sink.cancel_calls == [] and sink.submit_calls == []


# ── floor derivation / config ────────────────────────────────────────────────

def test_vertical_floor_from_min_credit_pct(tmp_path):
    monitor = _monitor(tmp_path, FakeEntrySink())
    pos = {"strategy_type": "bull_put", "short_strike": 630.0, "long_strike": 618.0}
    assert monitor._entry_credit_floor(pos) == pytest.approx(0.60)  # 12 × 5%


def test_condor_floor_from_combined_credit_pct(tmp_path):
    monitor = _monitor(tmp_path, FakeEntrySink())
    pos = {
        "strategy_type": "iron_condor",
        "put_short_strike": 630.0, "put_long_strike": 618.0,
        "call_short_strike": 650.0, "call_long_strike": 662.0,
    }
    assert monitor._entry_credit_floor(pos) == pytest.approx(4.80)  # 2×12 × 20%


def test_absolute_floor_override(tmp_path):
    monitor = _monitor(tmp_path, FakeEntrySink(), credit_floor=1.25)
    pos = {"strategy_type": "bull_put", "short_strike": 630.0, "long_strike": 618.0}
    assert monitor._entry_credit_floor(pos) == pytest.approx(1.25)


def test_reprice_disabled_by_default(tmp_path):
    monitor = PositionMonitor(
        alpaca_provider=None,
        config={"risk": {}, "strategy": {}},
        db_path=str(tmp_path / "off.db"),
        executor_sink=FakeEntrySink(),
    )
    assert monitor._reprice_enabled is False


def test_condor_replace_builds_four_leg_intent(tmp_path):
    sink = FakeEntrySink()
    monitor = _monitor(tmp_path, sink)
    _seed_pending(
        monitor,
        trade_id="cs-exp800-ic1",
        strategy_type="iron_condor",
        limit_credit=5.00,
        put_short_strike=630.0, put_long_strike=618.0,
        call_short_strike=650.0, call_long_strike=662.0,
    )

    monitor._check_entry_orders()

    assert len(sink.submit_calls) == 1
    intent = sink.submit_calls[0]
    assert intent.structure == "iron_condor"
    assert intent.stream == "cs-exp800-ic1-r1"
    assert intent.est_credit == pytest.approx(4.95)
    assert len(intent.legs) == 4
    sides = [(l.side, l.right, l.strike) for l in intent.legs]
    assert ("sell", "P", 630.0) in sides and ("buy", "P", 618.0) in sides
    assert ("sell", "C", 650.0) in sides and ("buy", "C", 662.0) in sides
