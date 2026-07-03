"""WS-6 tests: PT/SL exit routing through the executor sink.

Covers: ExecutorOrderSink.submit_close() payloads (2-leg + 4-leg, limit vs
market, "close-" idempotency prefix, validation), and PositionMonitor's
broker-agnostic pieces (_fetch_broker_positions, _get_close_order_status,
_occ_symbol, _submit_executor_close, _close_position executor flow, and
_reconcile_pending_closes with executor statuses).

No real HTTP — FakeHttp is injected into ExecutorClient for sink tests and a
FakeSink stub is used for monitor tests (same patterns as
tests/test_executor_condor_routing.py).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pytest

from compass.live.executor_order_sink import ExecutorClient, ExecutorOrderSink
from compass.live.vrp_contracts import OrderIntent, OrderLeg
from execution.position_monitor import PositionMonitor
from shared.database import get_trades, upsert_trade


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeHttp:
    def __init__(self, queue: Optional[List] = None) -> None:
        self.queue: List = list(queue or [])
        self.calls: List[Dict[str, Any]] = []
        self.headers: Dict[str, str] = {}

    def request(self, method: str, url: str, **kw) -> _FakeResponse:
        if method == "GET" and url.endswith("/auth/csrf-token"):
            return _FakeResponse(200, {"csrf_token": "fake-csrf-token"})
        self.calls.append({"method": method, "url": url, "json": kw.get("json")})
        if not self.queue:
            return _FakeResponse(200, {"success": True, "order_id": "ord-1", "status": "submitted"})
        status, body = self.queue.pop(0)
        return _FakeResponse(status, body)


def _http_sink(http: FakeHttp) -> ExecutorOrderSink:
    client = ExecutorClient("http://exec.test", "key", http=http)
    return ExecutorOrderSink(client, account_id="6YA42569", account_type="live")


class FakeSink:
    """Stub of ExecutorOrderSink for monitor-level tests."""

    def __init__(
        self,
        positions: Optional[List[Dict]] = None,
        order_status: Optional[Dict] = None,
        submit_result: Optional[Dict] = None,
    ) -> None:
        self.positions = positions or []
        self.order_status = order_status or {}
        self.submit_result = submit_result or {"status": "submitted", "order_id": "exec-ord-1"}
        self.close_calls: List[tuple] = []

    def get_positions(self) -> List[Dict]:
        return self.positions

    def get_order_status(self, order_id: str) -> Dict:
        return self.order_status

    def submit_close(self, intent: OrderIntent, *, net_debit=None) -> Dict:
        self.close_calls.append((intent, net_debit))
        return self.submit_result


# ── helpers ──────────────────────────────────────────────────────────────────

EXP = "2026-07-17"


def _config() -> Dict:
    return {
        "risk": {"profit_target": 50, "stop_loss_multiplier": 3.5},
        "strategy": {"manage_dte": 0},
        "execution": {"commission_per_contract": 0},
    }


def _monitor(tmp_path, sink=None) -> PositionMonitor:
    return PositionMonitor(
        alpaca_provider=None,
        config=_config(),
        db_path=str(tmp_path / "monitor_test.db"),
        executor_sink=sink,
    )


def _trade(
    trade_id: str = "cs-exp800-t1",
    strategy_type: str = "bull_put",
    status: str = "open",
    credit: float = 1.00,
    contracts: int = 2,
    **extra,
) -> Dict:
    t = dict(
        id=trade_id,
        ticker="SPY",
        strategy_type=strategy_type,
        status=status,
        short_strike=630.0,
        long_strike=618.0,
        expiration=EXP,
        credit=credit,
        contracts=contracts,
        entry_date="2026-06-25T15:00:00+00:00",
    )
    t.update(extra)
    return t


def _condor_trade(**extra) -> Dict:
    return _trade(
        trade_id="cs-exp800-ic1",
        strategy_type="iron_condor",
        put_short_strike=630.0,
        put_long_strike=618.0,
        call_short_strike=650.0,
        call_long_strike=662.0,
        credit=3.20,
        **extra,
    )


def _close_intent(structure: str = "bull_put", contracts: int = 2) -> OrderIntent:
    if structure == "iron_condor":
        legs = (
            OrderLeg("buy", "option", "SPY260717P00630000", contracts,
                     strike=630.0, expiration=EXP, right="P"),
            OrderLeg("sell", "option", "SPY260717P00618000", contracts,
                     strike=618.0, expiration=EXP, right="P"),
            OrderLeg("buy", "option", "SPY260717C00650000", contracts,
                     strike=650.0, expiration=EXP, right="C"),
            OrderLeg("sell", "option", "SPY260717C00662000", contracts,
                     strike=662.0, expiration=EXP, right="C"),
        )
    else:
        legs = (
            OrderLeg("buy", "option", "SPY260717P00630000", contracts,
                     strike=630.0, expiration=EXP, right="P"),
            OrderLeg("sell", "option", "SPY260717P00618000", contracts,
                     strike=618.0, expiration=EXP, right="P"),
        )
    return OrderIntent(
        stream="cs-exp800-t1", symbol="SPY", structure=structure,
        legs=legs, contracts=contracts,
    )


# ── sink: submit_close payloads ──────────────────────────────────────────────

def test_submit_close_2leg_limit_payload():
    http = FakeHttp()
    result = _http_sink(http).submit_close(_close_intent(), net_debit=0.50)

    assert result["status"] == "submitted"
    body = http.calls[0]["json"]
    assert http.calls[0]["url"].endswith("/v1/orders/spread")
    assert body["strategy"] == "bull_put_spread"
    assert body["order_type"] == "limit"
    assert body["net_debit"] == 0.50
    assert "net_credit" not in body
    assert body["idempotency_key"].startswith("close-")

    legs = body["legs"]
    assert [(l["side"], l["strike"]) for l in legs] == [
        ("buy_to_close", 630.0),
        ("sell_to_close", 618.0),
    ]
    assert all(l["quantity"] == 2 for l in legs)


def test_submit_close_condor_payload():
    http = FakeHttp()
    _http_sink(http).submit_close(_close_intent("iron_condor"), net_debit=1.10)
    body = http.calls[0]["json"]
    assert body["strategy"] == "iron_condor"
    assert [(l["side"], l["option_type"], l["strike"]) for l in body["legs"]] == [
        ("buy_to_close", "put", 630.0),
        ("sell_to_close", "put", 618.0),
        ("buy_to_close", "call", 650.0),
        ("sell_to_close", "call", 662.0),
    ]


def test_submit_close_no_debit_is_market():
    http = FakeHttp()
    _http_sink(http).submit_close(_close_intent())
    body = http.calls[0]["json"]
    assert body["order_type"] == "market"
    assert "net_debit" not in body


def test_submit_close_idempotency_distinct_from_open():
    http = FakeHttp()
    sink = _http_sink(http)
    intent = _close_intent()
    sink.submit(OrderIntent(
        stream=intent.stream, symbol=intent.symbol, structure="bull_put",
        legs=(
            OrderLeg("sell", "option", "SPY260717P00630000", 2,
                     strike=630.0, expiration=EXP, right="P"),
            OrderLeg("buy", "option", "SPY260717P00618000", 2,
                     strike=618.0, expiration=EXP, right="P"),
        ),
        contracts=2, est_credit=1.0,
    ))
    sink.submit_close(intent)
    open_key = http.calls[0]["json"]["idempotency_key"]
    close_key = http.calls[1]["json"]["idempotency_key"]
    assert close_key.startswith("close-")
    assert not open_key.startswith("close-")
    assert close_key != open_key
    for strike in ("618", "630"):
        assert strike in open_key and strike in close_key


def test_submit_close_malformed_leg_rejected_without_http():
    bad = OrderIntent(
        stream="s", symbol="SPY", structure="bull_put",
        legs=(
            OrderLeg("buy", "option", "SPY260717P00630000", 1,
                     strike=630.0, expiration=EXP, right="P"),
            OrderLeg("sell", "option", "SPY260717P00618000", 1,
                     strike=None, expiration=EXP, right="P"),
        ),
        contracts=1,
    )
    http = FakeHttp()
    result = _http_sink(http).submit_close(bad)
    assert result["status"] == "error"
    assert http.calls == []


def test_submit_close_condor_wrong_leg_count_rejected():
    bad = OrderIntent(
        stream="s", symbol="SPY", structure="iron_condor",
        legs=_close_intent().legs,  # only 2 legs
        contracts=1,
    )
    http = FakeHttp()
    result = _http_sink(http).submit_close(bad)
    assert result["status"] == "error"
    assert "4 legs" in result["message"]
    assert http.calls == []


def test_submit_close_unsupported_structure_raises():
    intent = OrderIntent(stream="s", symbol="SPY", structure="straddle",
                         legs=(), contracts=1)
    with pytest.raises(NotImplementedError):
        _http_sink(FakeHttp()).submit_close(intent)


def test_submit_close_http_error_returns_error_dict():
    http = FakeHttp(queue=[(500, {"detail": "boom"})])
    result = _http_sink(http).submit_close(_close_intent(), net_debit=0.50)
    assert result["status"] == "error"


# ── monitor: broker-agnostic helpers ─────────────────────────────────────────

def test_fetch_broker_positions_normalizes_executor_shape(tmp_path):
    sink = FakeSink(positions=[{
        "symbol": "SPY260717P00630000",
        "quantity": -2,
        "market_value": -150.0,
        "current_price": 0.75,
        "average_cost": 1.10,
        "unrealized_pnl": 70.0,
    }])
    monitor = _monitor(tmp_path, sink=sink)
    positions = monitor._fetch_broker_positions()
    assert positions == [{
        "symbol": "SPY260717P00630000",
        "qty": -2,
        "market_value": -150.0,
        "current_price": 0.75,
        "avg_entry_price": 1.10,
        "unrealized_pl": 70.0,
    }]


def test_fetch_broker_positions_rebuilds_occ_from_tradier_shape(tmp_path):
    """Tradier-route positions carry the UNDERLYING in symbol with the
    contract split into option_type/strike/expiration (Phase 2 finding)."""
    sink = FakeSink(positions=[{
        "symbol": "SPY",
        "security_type": "option",
        "quantity": -1,
        "average_cost": 6.11,
        "market_value": 0.0,
        "current_price": 0.0,
        "unrealized_pnl": 0.0,
        "option_type": "put",
        "strike": 740.0,
        "expiration": "2026-07-24",
    }])
    monitor = _monitor(tmp_path, sink=sink)
    positions = monitor._fetch_broker_positions()
    assert positions[0]["symbol"] == "SPY260724P00740000"
    assert positions[0]["qty"] == -1


def test_fetch_broker_positions_no_source_raises(tmp_path):
    monitor = _monitor(tmp_path, sink=None)
    with pytest.raises(RuntimeError, match="no broker position source"):
        monitor._fetch_broker_positions()


def test_get_close_order_status_normalizes(tmp_path):
    sink = FakeSink(order_status={
        "status": "filled",
        "filled_quantity": 2,
        "average_fill_price": 0.40,
        "last_updated": "2026-07-01T15:00:00Z",
    })
    monitor = _monitor(tmp_path, sink=sink)
    order = monitor._get_close_order_status("ord-9")
    assert order == {
        "status": "filled",
        "filled_qty": 2,
        "filled_avg_price": 0.40,
        "filled_at": "2026-07-01T15:00:00Z",
    }


def test_occ_symbol_without_alpaca_uses_module_builder(tmp_path):
    monitor = _monitor(tmp_path, sink=FakeSink())
    assert monitor._occ_symbol("SPY", EXP, 630.0, "put") == "SPY260717P00630000"
    assert monitor._occ_symbol("SPY", EXP, 650.0, "call") == "SPY260717C00650000"


# ── monitor: _submit_executor_close intent building ──────────────────────────

def test_submit_executor_close_bull_put(tmp_path):
    sink = FakeSink()
    monitor = _monitor(tmp_path, sink=sink)
    pos = _trade()

    result = monitor._submit_executor_close(pos, 2, EXP, "bull_put")
    assert result["status"] == "submitted"
    intent, net_debit = sink.close_calls[0]
    assert intent.structure == "bull_put"
    assert intent.stream == "cs-exp800-t1"
    assert [(l.side, l.right, l.strike) for l in intent.legs] == [
        ("buy", "P", 630.0),
        ("sell", "P", 618.0),
    ]
    assert intent.legs[0].symbol == "SPY260717P00630000"
    # credit 1.00, no current_value → limit = 50% of credit
    assert net_debit == 0.50


def test_submit_executor_close_bear_call_spread_variant(tmp_path):
    sink = FakeSink()
    monitor = _monitor(tmp_path, sink=sink)
    pos = _trade(strategy_type="bear_call_spread", short_strike=650.0, long_strike=662.0)

    monitor._submit_executor_close(pos, 2, EXP, "bear_call_spread")
    intent, _ = sink.close_calls[0]
    assert intent.structure == "bear_call"
    assert [(l.side, l.right, l.strike) for l in intent.legs] == [
        ("buy", "C", 650.0),
        ("sell", "C", 662.0),
    ]


def test_submit_executor_close_condor(tmp_path):
    sink = FakeSink()
    monitor = _monitor(tmp_path, sink=sink)
    pos = _condor_trade(current_value=1.00)

    monitor._submit_executor_close(pos, 2, EXP, "iron_condor")
    intent, net_debit = sink.close_calls[0]
    assert intent.structure == "iron_condor"
    assert [(l.side, l.right, l.strike) for l in intent.legs] == [
        ("buy", "P", 630.0),
        ("sell", "P", 618.0),
        ("buy", "C", 650.0),
        ("sell", "C", 662.0),
    ]
    # current_value 1.00 → limit = 1.10 (10% buffer)
    assert net_debit == 1.10


def test_submit_executor_close_condor_missing_wing_errors(tmp_path):
    sink = FakeSink()
    monitor = _monitor(tmp_path, sink=sink)
    pos = _condor_trade()
    pos.pop("call_short_strike")
    pos.pop("call_long_strike")

    result = monitor._submit_executor_close(pos, 2, EXP, "iron_condor")
    assert result["status"] == "error"
    assert "missing per-wing strikes" in result["message"]
    assert sink.close_calls == []


def test_submit_executor_close_straddle_unsupported(tmp_path):
    sink = FakeSink()
    monitor = _monitor(tmp_path, sink=sink)
    pos = _trade(strategy_type="straddle")

    result = monitor._submit_executor_close(pos, 2, EXP, "straddle")
    assert result["status"] == "error"
    assert "does not support structure" in result["message"]
    assert sink.close_calls == []


# ── monitor: _close_position executor flow ───────────────────────────────────

def test_close_position_executor_stores_close_order_id(tmp_path):
    sink = FakeSink(submit_result={"status": "submitted", "order_id": "exec-ord-7"})
    monitor = _monitor(tmp_path, sink=sink)
    pos = _trade()
    upsert_trade(pos, source="execution", path=monitor.db_path)

    monitor._close_position(pos, reason="profit_target")

    pending = get_trades(status="pending_close", source="execution", path=monitor.db_path)
    assert len(pending) == 1
    assert pending[0]["close_order_id"] == "exec-ord-7"
    assert pending[0]["exit_reason"] == "profit_target"
    assert len(sink.close_calls) == 1


def test_close_position_executor_failure_resets_to_open(tmp_path):
    sink = FakeSink(submit_result={"status": "error", "message": "rejected by broker"})
    monitor = _monitor(tmp_path, sink=sink)
    pos = _trade()
    upsert_trade(pos, source="execution", path=monitor.db_path)

    monitor._close_position(pos, reason="stop_loss")

    assert get_trades(status="pending_close", source="execution", path=monitor.db_path) == []
    reopened = get_trades(status="open", source="execution", path=monitor.db_path)
    assert len(reopened) == 1
    assert not reopened[0].get("close_order_id")


# ── monitor: _reconcile_pending_closes with executor statuses ────────────────

def _pending_close_trade(monitor: PositionMonitor, **extra) -> Dict:
    pos = _trade(
        status="pending_close",
        close_order_id="exec-ord-7",
        exit_reason="profit_target",
        close_order_submitted_at="2026-07-01T14:00:00+00:00",
        **extra,
    )
    upsert_trade(pos, source="execution", path=monitor.db_path)
    return pos


def test_reconcile_pending_closes_filled_records_pnl(tmp_path):
    sink = FakeSink(order_status={
        "status": "filled",
        "filled_quantity": 2,
        "average_fill_price": 0.40,
        "last_updated": "2026-07-01T15:00:00Z",
    })
    monitor = _monitor(tmp_path, sink=sink)
    _pending_close_trade(monitor)

    monitor._reconcile_pending_closes()

    # close_trade derives status from pnl sign: positive → closed_profit
    closed = get_trades(status="closed_profit", source="execution", path=monitor.db_path)
    assert len(closed) == 1
    # credit 1.00, fill 0.40, 2 contracts, commission disabled → (1.00-0.40)*2*100
    assert closed[0]["pnl"] == pytest.approx(120.0)


def test_reconcile_pending_closes_rejected_resets_to_open(tmp_path):
    sink = FakeSink(order_status={"status": "rejected"})
    monitor = _monitor(tmp_path, sink=sink)
    _pending_close_trade(monitor)

    monitor._reconcile_pending_closes()

    assert get_trades(status="pending_close", source="execution", path=monitor.db_path) == []
    reopened = get_trades(status="open", source="execution", path=monitor.db_path)
    assert len(reopened) == 1
    assert not reopened[0].get("close_order_id")


def test_reconcile_pending_closes_still_open_stays_pending(tmp_path):
    sink = FakeSink(order_status={"status": "open"})
    monitor = _monitor(tmp_path, sink=sink)
    _pending_close_trade(monitor)

    monitor._reconcile_pending_closes()

    pending = get_trades(status="pending_close", source="execution", path=monitor.db_path)
    assert len(pending) == 1
