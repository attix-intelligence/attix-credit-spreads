"""WS-2 tests: 4-leg iron-condor routing through the executor sink.

Covers: ExecutorOrderSink.submit() building a 4-leg iron_condor payload,
malformed-intent rejection, ExecutionEngine._build_executor_intent condor
variant, and the widened structure guard in _submit_via_executor.

No real HTTP — a FakeHttp session is injected into ExecutorClient (same
pattern as tests/test_executor_order_sink.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from compass.live.executor_order_sink import ExecutorClient, ExecutorOrderSink
from compass.live.vrp_contracts import OrderIntent, OrderLeg
from execution.execution_engine import ExecutionEngine


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


def _sink(http: FakeHttp) -> ExecutorOrderSink:
    client = ExecutorClient("http://exec.test", "key", http=http)
    return ExecutorOrderSink(client, account_id="6YA42569", account_type="live")


def _condor_intent(*, contracts: int = 2, est_credit: Optional[float] = 3.20) -> OrderIntent:
    exp = "2026-07-17"
    return OrderIntent(
        stream="cs-exp800-abc123",
        symbol="SPY",
        structure="iron_condor",
        legs=(
            OrderLeg("sell", "option", "SPY260717P00630000", contracts,
                     strike=630.0, expiration=exp, right="P"),
            OrderLeg("buy", "option", "SPY260717P00618000", contracts,
                     strike=618.0, expiration=exp, right="P"),
            OrderLeg("sell", "option", "SPY260717C00650000", contracts,
                     strike=650.0, expiration=exp, right="C"),
            OrderLeg("buy", "option", "SPY260717C00662000", contracts,
                     strike=662.0, expiration=exp, right="C"),
        ),
        contracts=contracts,
        est_credit=est_credit,
    )


# ── sink: 4-leg payload ─────────────────────────────────────────────────────

def test_condor_submit_builds_4_leg_payload():
    http = FakeHttp()
    result = _sink(http).submit(_condor_intent())

    assert result["status"] == "submitted"
    assert len(http.calls) == 1
    body = http.calls[0]["json"]
    assert http.calls[0]["url"].endswith("/v1/orders/spread")
    assert body["strategy"] == "iron_condor"
    assert body["account_id"] == "6YA42569"
    assert body["account_type"] == "live"
    assert body["order_type"] == "limit"
    assert body["net_credit"] == 3.20

    legs = body["legs"]
    assert len(legs) == 4
    assert [(l["side"], l["option_type"], l["strike"]) for l in legs] == [
        ("sell_to_open", "put", 630.0),
        ("buy_to_open", "put", 618.0),
        ("sell_to_open", "call", 650.0),
        ("buy_to_open", "call", 662.0),
    ]
    assert all(l["symbol"] == "SPY" for l in legs)
    assert all(l["expiration"] == "2026-07-17" for l in legs)
    assert all(l["quantity"] == 2 for l in legs)


def test_condor_no_credit_falls_back_to_market():
    http = FakeHttp()
    _sink(http).submit(_condor_intent(est_credit=None))
    body = http.calls[0]["json"]
    assert body["order_type"] == "market"
    assert "net_credit" not in body


def test_condor_idempotency_key_covers_all_strikes():
    http = FakeHttp()
    _sink(http).submit(_condor_intent())
    key = http.calls[0]["json"]["idempotency_key"]
    for strike in ("618", "630", "650", "662"):
        assert strike in key


def test_malformed_condor_intent_rejected_without_http():
    bad = OrderIntent(
        stream="s", symbol="SPY", structure="iron_condor",
        legs=(
            OrderLeg("sell", "option", "SPY260717P00630000", 1,
                     strike=630.0, expiration="2026-07-17", right="P"),
            OrderLeg("buy", "option", "SPY260717P00618000", 1,
                     strike=None, expiration="2026-07-17", right="P"),
        ),
        contracts=1,
    )
    http = FakeHttp()
    result = _sink(http).submit(bad)
    assert result["status"] == "error"
    assert http.calls == []


def test_two_leg_spread_payload_unchanged():
    """WS-2 must not alter the existing bull_put payload shape."""
    intent = OrderIntent(
        stream="exp1220", symbol="SPY", structure="bull_put",
        legs=(
            OrderLeg("sell", "option", "SPY260717P00630000", 3,
                     strike=630.0, expiration="2026-07-17", right="P"),
            OrderLeg("buy", "option", "SPY260717P00618000", 3,
                     strike=618.0, expiration="2026-07-17", right="P"),
        ),
        contracts=3, est_credit=1.75,
    )
    http = FakeHttp()
    _sink(http).submit(intent)
    body = http.calls[0]["json"]
    assert body["strategy"] == "bull_put_spread"
    assert len(body["legs"]) == 2
    assert body["legs"][0]["side"] == "sell_to_open"
    assert body["legs"][1]["side"] == "buy_to_open"
    assert body["net_credit"] == 1.75


def test_unsupported_structure_still_raises():
    intent = OrderIntent(
        stream="s", symbol="SPY", structure="calendar",
        legs=(), contracts=1,
    )
    with pytest.raises(NotImplementedError):
        _sink(FakeHttp()).submit(intent)


# ── engine: condor intent building ──────────────────────────────────────────

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
    "contracts": 2,
}


def _engine(tmp_path, sink=None):
    return ExecutionEngine(
        alpaca_provider=None,
        db_path=str(tmp_path / "test_condor.db"),
        config={"risk": {"drawdown_cb_pct": 0}},
        executor_sink=sink,
    )


def test_build_executor_intent_condor(tmp_path):
    engine = _engine(tmp_path)
    intent = engine._build_executor_intent(
        client_id="cs-exp800-abc", ticker="SPY", spread_type="iron_condor",
        contracts=2, credit=3.20, expiration="2026-07-17",
        short_strike=630.0, long_strike=618.0, opp=CONDOR_OPP,
    )
    assert intent.structure == "iron_condor"
    assert len(intent.legs) == 4
    assert [(l.side, l.right, l.strike) for l in intent.legs] == [
        ("sell", "P", 630.0),
        ("buy", "P", 618.0),
        ("sell", "C", 650.0),
        ("buy", "C", 662.0),
    ]
    assert intent.legs[2].symbol == "SPY260717C00650000"
    assert intent.est_credit == 3.20
    assert all(l.qty == 2 for l in intent.legs)


def test_build_executor_intent_condor_missing_wing_raises(tmp_path):
    engine = _engine(tmp_path)
    opp = dict(CONDOR_OPP)
    del opp["call_short_strike"]
    with pytest.raises(ValueError, match="missing per-wing strikes"):
        engine._build_executor_intent(
            client_id="cs-x", ticker="SPY", spread_type="iron_condor",
            contracts=1, credit=3.20, expiration="2026-07-17",
            short_strike=630.0, long_strike=618.0, opp=opp,
        )


def test_build_executor_intent_two_leg_unchanged(tmp_path):
    engine = _engine(tmp_path)
    intent = engine._build_executor_intent(
        client_id="cs-x", ticker="SPY", spread_type="bull_put",
        contracts=3, credit=1.75, expiration="2026-07-17",
        short_strike=630.0, long_strike=618.0,
    )
    assert intent.structure == "bull_put"
    assert len(intent.legs) == 2
    assert intent.legs[0].right == "P"


def test_submit_via_executor_accepts_condor(tmp_path, monkeypatch):
    """Structure guard must pass condors through to the sink (RTH + live_submit
    gates stubbed open; sink recorded)."""
    http = FakeHttp()
    engine = _engine(tmp_path, sink=_sink(http))
    monkeypatch.setattr("execution.market_hours.is_rth_now", lambda: True)
    monkeypatch.setenv("LIVE_SUBMIT", "1")
    engine.config["risk"]["max_contracts"] = 30

    result = engine.submit_opportunity(dict(CONDOR_OPP))
    assert result["status"] == "submitted"
    # calls[0] is the WS-3 conflict-check positions GET; the submit is the POST.
    posts = [c for c in http.calls if c["method"] == "POST"]
    assert len(posts) == 1
    body = posts[0]["json"]
    assert body["strategy"] == "iron_condor"
    assert len(body["legs"]) == 4


def test_submit_via_executor_still_rejects_straddle(tmp_path, monkeypatch):
    http = FakeHttp()
    engine = _engine(tmp_path, sink=_sink(http))
    monkeypatch.setattr("execution.market_hours.is_rth_now", lambda: True)
    monkeypatch.setenv("LIVE_SUBMIT", "1")
    engine.config["risk"]["max_contracts"] = 30

    opp = dict(CONDOR_OPP)
    opp["type"] = "straddle"
    result = engine.submit_opportunity(opp)
    assert result["status"] == "error"
    assert "does not support structure" in result["message"]
    assert [c for c in http.calls if c["method"] == "POST"] == []
