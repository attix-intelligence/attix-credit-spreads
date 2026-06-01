"""Tests for compass.live.vrp_position_monitor (PR-H).

No network, no Alpaca, no Polygon — every dependency is a fake. The monitor's
contract is: given a registry of opens, a snapshot of broker positions, a VIX
reading, and a clock, produce the right decision per spread and dispatch a close
through the injected provider.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from compass.live.vrp_contracts import OrderIntent, OrderLeg
from compass.live.vrp_position_monitor import (
    DEFAULT_CRISIS_VIX,
    OpenSpread,
    TRIGGER_CRISIS,
    TRIGGER_PROFIT,
    TRIGGER_ROLL,
    TRIGGER_STOP,
    TrackingOrderSink,
    VRPPositionMonitor,
    VRPPositionRegistry,
    _build_occ_symbol,
    _compute_cost_to_close,
    vrp_monitor_enabled,
    vrp_monitor_track_opens,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


def _intent(*, symbol="SPY", stream="exp1220", short=400.0, long_=395.0, exp="2026-07-26",
            contracts=2, est_credit=2.10, structure="bull_put") -> OrderIntent:
    """A 2-leg bull-put intent matching what VRPMultiStreamStrategy emits."""
    return OrderIntent(
        stream=stream, symbol=symbol, structure=structure,
        legs=(
            OrderLeg(side="sell", sec_type="option", symbol=f"{symbol}-short",
                     qty=contracts, strike=short, expiration=exp, right="P"),
            OrderLeg(side="buy", sec_type="option", symbol=f"{symbol}-long",
                     qty=contracts, strike=long_, expiration=exp, right="P"),
        ),
        contracts=contracts,
        est_credit=est_credit,
        rationale="test",
    )


def _make_leg_row(symbol: str, *, qty: int, current_price: float,
                  asset_class: str = "us_option") -> Dict[str, Any]:
    """Shape that AlpacaProvider.get_positions() returns (all-string values)."""
    return {
        "symbol": symbol,
        "qty": str(qty),
        "current_price": str(current_price),
        "market_value": str(qty * current_price * 100.0),
        "asset_class": asset_class,
        "avg_entry_price": "1.00",
    }


class _FakeAlpaca:
    def __init__(self, positions: List[Dict[str, Any]] | None = None) -> None:
        self._positions = positions or []
        self.close_calls: List[Dict[str, Any]] = []
        self.next_close_result: Dict[str, Any] = {"status": "submitted", "order_id": "close-1"}

    def get_positions(self) -> List[Dict[str, Any]]:
        return self._positions

    def close_spread(self, **kwargs) -> Dict[str, Any]:
        self.close_calls.append(kwargs)
        return self.next_close_result


# ── registry round-trip ──────────────────────────────────────────────────────


def test_registry_round_trip(tmp_path):
    """record_open → list_open returns the row; mark_pending_close + mark_closed
    transition the status."""
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))
    intent = _intent()
    row = reg.record_open(intent, order_id="abc")
    assert row is not None
    assert row.stream == "exp1220"
    assert row.credit_per_contract == pytest.approx(1.05)        # 2.10 / 2 contracts
    assert row.status == "open"

    open_rows = reg.list_open()
    assert len(open_rows) == 1
    assert open_rows[0].spread_id == row.spread_id
    assert open_rows[0].order_id == "abc"

    reg.mark_pending_close(row.spread_id, reason="profit_take", close_order_id="cls-1")
    assert reg.list_open()[0].status == "pending_close"

    reg.mark_closed(row.spread_id, reason="profit_take")
    # mark_closed drops the row from list_open (status=closed), but list_all keeps it.
    assert reg.list_open() == []
    closed = [r for r in reg.list_all() if r.status == "closed"]
    assert closed and closed[0].close_reason == "profit_take"


def test_registry_refuses_intent_without_credit(tmp_path):
    """Cost-based PT/SL math is meaningless without credit — refuse to track."""
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))
    bad = _intent(est_credit=None)  # type: ignore[arg-type]
    assert reg.record_open(bad) is None
    assert reg.list_open() == []


def test_registry_idempotent_on_redundant_open(tmp_path):
    """Resubmitting the same coid (Alpaca dedup retry) keeps original opened_at
    but refreshes order_id, doesn't duplicate the row."""
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))
    i = _intent()
    first = reg.record_open(i, order_id="A")
    second = reg.record_open(i, order_id="B")
    assert first is not None and second is not None
    rows = reg.list_open()
    assert len(rows) == 1
    assert rows[0].order_id == "B"


# ── tracking sink ────────────────────────────────────────────────────────────


class _RecordingSink:
    def __init__(self, result: Dict[str, Any]):
        self._result = result
        self.calls: List[OrderIntent] = []

    def submit(self, intent: OrderIntent) -> Dict[str, Any]:
        self.calls.append(intent)
        return dict(self._result)


def test_tracking_sink_records_on_success(tmp_path):
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))
    inner = _RecordingSink({"status": "submitted", "order_id": "ord-1"})
    sink = TrackingOrderSink(inner, reg)
    sink.submit(_intent())
    assert len(reg.list_open()) == 1
    assert reg.list_open()[0].order_id == "ord-1"


def test_tracking_sink_skips_on_error(tmp_path):
    """An error result must NOT pollute the registry — otherwise the monitor
    would attempt to close a position that doesn't exist."""
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))
    inner = _RecordingSink({"status": "error", "message": "boom"})
    TrackingOrderSink(inner, reg).submit(_intent())
    assert reg.list_open() == []


def test_tracking_sink_swallows_registry_failure(tmp_path, monkeypatch):
    """A bad disk write must not crash the runner mid-cycle."""
    reg = VRPPositionRegistry(str(tmp_path / "reg.json"))

    def boom(*_a, **_kw):
        raise OSError("disk full")
    monkeypatch.setattr(reg, "record_open", boom)
    inner = _RecordingSink({"status": "submitted", "order_id": "ord-2"})
    result = TrackingOrderSink(inner, reg).submit(_intent())
    # Caller sees the inner sink's result unchanged.
    assert result["status"] == "submitted"


# ── trigger evaluation ───────────────────────────────────────────────────────


def _open_spread(*, exp_offset_days=45, credit=1.05, contracts=2) -> OpenSpread:
    """Build an OpenSpread directly (skip the registry) for trigger tests."""
    exp_date = (datetime.now(timezone.utc) + timedelta(days=exp_offset_days)).strftime("%Y-%m-%d")
    return OpenSpread(
        spread_id="vrp-exp1220-SPY-{}-400-395".format(exp_date),
        stream="exp1220", symbol="SPY", structure="bull_put",
        short_strike=400.0, long_strike=395.0, expiration=exp_date,
        contracts=contracts, credit_per_contract=credit,
        opened_at=datetime.now(timezone.utc).isoformat(),
    )


def _positions_at(spread: OpenSpread, *, short_mark: float, long_mark: float) -> List[Dict[str, Any]]:
    """Build the broker positions list for one spread's legs at given marks."""
    short_occ = _build_occ_symbol(spread.symbol, spread.expiration, spread.short_strike, "put")
    long_occ = _build_occ_symbol(spread.symbol, spread.expiration, spread.long_strike, "put")
    return [
        _make_leg_row(short_occ, qty=-spread.contracts, current_price=short_mark),
        _make_leg_row(long_occ, qty=+spread.contracts, current_price=long_mark),
    ]


def _build_monitor(*, registry, alpaca, vix, crisis_vix=DEFAULT_CRISIS_VIX) -> VRPPositionMonitor:
    return VRPPositionMonitor(
        registry, alpaca_provider=alpaca, vix_source=lambda: vix,
        crisis_vix=crisis_vix,
    )


def test_profit_take_trigger(tmp_path):
    spread = _open_spread(credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    # Seed registry directly (skip TrackingOrderSink — unit-test the monitor).
    reg._write({spread.spread_id: spread.__dict__})
    alpaca = _FakeAlpaca(_positions_at(spread, short_mark=0.40, long_mark=0.02))
    # cost_to_close = 0.40 - 0.02 = 0.38; PT threshold = 0.5 * 1.05 = 0.525 → fires.
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=20.0).run_cycle()
    triggers = [d.trigger for d in report.decisions]
    assert triggers == [TRIGGER_PROFIT]
    assert len(alpaca.close_calls) == 1
    assert alpaca.close_calls[0]["ticker"] == "SPY"
    assert alpaca.close_calls[0]["spread_type"] == "bull_put"
    assert reg.list_open()[0].status == "pending_close"
    assert reg.list_open()[0].close_reason == TRIGGER_PROFIT


def test_stop_loss_trigger(tmp_path):
    spread = _open_spread(credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})
    # cost_to_close = 3.20 - 0.05 = 3.15; SL threshold = 3 × 1.05 = 3.15 → fires.
    alpaca = _FakeAlpaca(_positions_at(spread, short_mark=3.20, long_mark=0.05))
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=22.0).run_cycle()
    assert [d.trigger for d in report.decisions] == [TRIGGER_STOP]
    assert len(alpaca.close_calls) == 1


def test_dte_roll_trigger(tmp_path):
    """DTE ≤ 7 fires the roll close without needing leg marks (priority above PT/SL)."""
    spread = _open_spread(exp_offset_days=5, credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})
    alpaca = _FakeAlpaca(_positions_at(spread, short_mark=0.80, long_mark=0.20))
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=22.0).run_cycle()
    assert [d.trigger for d in report.decisions] == [TRIGGER_ROLL]


def test_crisis_vix_closes_everything(tmp_path):
    """VIX > 45 closes EVERY spread regardless of P&L or DTE."""
    s1 = _open_spread(credit=1.05, exp_offset_days=45)
    s2 = _open_spread(credit=0.80, exp_offset_days=30)
    # Distinguish IDs (different strikes would normally do this; just rename):
    s2 = OpenSpread(**{**s2.__dict__, "short_strike": 410.0, "long_strike": 405.0,
                       "spread_id": s2.spread_id + "-x"})
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({s1.spread_id: s1.__dict__, s2.spread_id: s2.__dict__})
    # Even with no broker positions (legs missing), crisis fires.
    alpaca = _FakeAlpaca([])
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=46.0).run_cycle()
    assert report.crisis is True
    assert sorted(d.trigger for d in report.decisions) == [TRIGGER_CRISIS, TRIGGER_CRISIS]
    assert len(alpaca.close_calls) == 2


def test_no_trigger_when_within_band(tmp_path):
    """cost_to_close midway between PT and SL → no action."""
    spread = _open_spread(credit=1.00)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})
    # cost_to_close = 0.80 - 0.10 = 0.70; PT threshold = 0.50, SL threshold = 3.00 → no fire.
    alpaca = _FakeAlpaca(_positions_at(spread, short_mark=0.80, long_mark=0.10))
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=18.0).run_cycle()
    assert report.decisions[0].trigger is None
    assert alpaca.close_calls == []
    assert reg.list_open()[0].status == "open"


def test_pending_close_is_not_re_evaluated(tmp_path):
    """If we already issued a close last cycle, don't fire a second close order."""
    spread = _open_spread(credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg.record_open(_intent(), order_id="ord-1")
    # Now mark it pending — the next cycle should skip dispatch.
    open_rows = reg.list_open()
    assert open_rows, "registry seed failed"
    reg.mark_pending_close(open_rows[0].spread_id, reason="profit_take", close_order_id="cls-1")
    alpaca = _FakeAlpaca([])
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=22.0).run_cycle()
    assert alpaca.close_calls == []
    assert report.decisions[0].trigger is None
    assert "awaiting close fill" in report.decisions[0].detail


def test_legs_missing_means_no_pt_or_sl(tmp_path):
    """No legs in broker snapshot → can't price → no PT/SL (and no crisis/roll
    here either, so the cycle is a no-op for this spread)."""
    spread = _open_spread(credit=1.05, exp_offset_days=45)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})
    alpaca = _FakeAlpaca([])  # nothing on the broker
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=22.0).run_cycle()
    assert report.decisions[0].trigger is None
    assert "legs missing" in report.decisions[0].detail


def test_compute_cost_to_close_math():
    """Sanity-check the per-leg mark → cost-to-close arithmetic in isolation."""
    spread = _open_spread()
    legs = _positions_at(spread, short_mark=0.50, long_mark=0.15)
    indexed = {r["symbol"]: r for r in legs}
    assert _compute_cost_to_close(spread, indexed) == pytest.approx(0.35)


def test_executor_close_gap_logs_and_skips(tmp_path, caplog):
    """Executor-routed spread hitting an exit must log EXECUTOR-CLOSE-GAP and
    leave the registry row untouched (operator action required)."""
    spread = _open_spread(credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})

    class _FakeExecutor:
        def get_positions(self):
            return _positions_at(spread, short_mark=0.30, long_mark=0.05)  # PT range

    monitor = VRPPositionMonitor(
        reg, executor_sink=_FakeExecutor(), vix_source=lambda: 20.0,
    )
    with caplog.at_level("ERROR"):
        report = monitor.run_cycle()

    assert report.decisions[0].trigger == TRIGGER_PROFIT
    assert report.skipped_executor == [spread.spread_id]
    # Row stays "open" so an operator can act manually.
    assert reg.list_open()[0].status == "open"
    assert any("EXECUTOR-CLOSE-GAP" in rec.message for rec in caplog.records)


def test_alpaca_close_error_doesnt_crash_cycle(tmp_path):
    """If close_spread raises, the cycle continues and records an error result."""
    spread = _open_spread(credit=1.05)
    reg = VRPPositionRegistry(str(tmp_path / "r.json"))
    reg._write({spread.spread_id: spread.__dict__})

    class _ExplodingAlpaca(_FakeAlpaca):
        def close_spread(self, **kwargs):
            raise RuntimeError("alpaca down")

    alpaca = _ExplodingAlpaca(_positions_at(spread, short_mark=0.30, long_mark=0.05))
    report = _build_monitor(registry=reg, alpaca=alpaca, vix=20.0).run_cycle()
    assert report.decisions[0].trigger == TRIGGER_PROFIT
    assert report.closes_submitted[0]["status"] == "error"


# ── config helpers ───────────────────────────────────────────────────────────


def test_vrp_monitor_enabled_helpers():
    """Flags are off-by-default and enabled implies tracking is on."""
    assert vrp_monitor_enabled({}) is False
    assert vrp_monitor_enabled({"vrp_position_monitor": {"enabled": False}}) is False
    assert vrp_monitor_enabled({"vrp_position_monitor": {"enabled": True}}) is True

    assert vrp_monitor_track_opens({}) is False
    assert vrp_monitor_track_opens({"vrp_position_monitor": {"track_opens": True}}) is True
    # enabled=true ⇒ tracking implicitly required (even if track_opens omitted).
    assert vrp_monitor_track_opens({"vrp_position_monitor": {"enabled": True}}) is True


def test_registry_default_for_uses_db_path(tmp_path, monkeypatch):
    """default_for() derives a sidecar JSON path next to the experiment DB."""
    db = str(tmp_path / "attix_v8a.db")
    monkeypatch.setenv("ATTIX_DB_PATH", db)
    reg = VRPPositionRegistry.default_for({})
    assert reg.path == f"{db}.vrp_positions.json"


def test_registry_default_for_respects_explicit_path(tmp_path):
    """Explicit registry_path overrides the env+db fallback chain."""
    p = str(tmp_path / "explicit.json")
    reg = VRPPositionRegistry.default_for({"vrp_position_monitor": {"registry_path": p}})
    assert reg.path == p
