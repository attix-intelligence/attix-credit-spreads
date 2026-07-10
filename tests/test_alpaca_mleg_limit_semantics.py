"""FIX #4: Alpaca MLEG limit-price sign semantics.

Alpaca multileg convention (alpaca-py LimitOrderRequest docstring + docs):
POSITIVE limit_price = max net DEBIT to pay; NEGATIVE = min net CREDIT to
receive (abs value). A credit-spread open submitted with a positive limit is
a debit cap that never binds — paper fills at ANY credit (Jul 6/9 2026
live-vs-backtest parity investigation).

These tests pin the corrected convention at every MLEG build site:
  - strategy/alpaca_provider.py   (LimitOrderRequest, order_class=MLEG)
  - compass/alpaca_connector.py   (MultilegOrderRequest)
  - compass/orchestrator/order_router.py (MultilegOrderRequest)

No network: submit_order is mocked; requests are captured and inspected.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# strategy/alpaca_provider.py
# ═══════════════════════════════════════════════════════════════════════════

def _make_provider():
    from strategy.alpaca_provider import AlpacaProvider

    provider = object.__new__(AlpacaProvider)
    provider.client = MagicMock()
    breaker = MagicMock()
    breaker.call.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
    provider._circuit_breaker = breaker

    order = MagicMock()
    order.id = "ord-1"
    order.client_order_id = "cid-1"
    order.status = "accepted"
    order.submitted_at = "2026-07-10T13:30:00Z"
    provider.client.submit_order.return_value = order

    provider.find_option_symbol = MagicMock(
        side_effect=lambda ticker, exp, strike, opt: (
            f"{ticker}260724{'P' if opt == 'put' else 'C'}{int(strike * 1000):08d}"
        )
    )
    return provider


class TestAlpacaProviderMlegSign:
    def test_open_credit_spread_limit_is_negative_credit_floor(self):
        provider = _make_provider()
        result = provider.submit_credit_spread(
            ticker="SPY",
            short_strike=730.0,
            long_strike=718.0,
            expiration="2026-07-24",
            spread_type="bull_put",
            contracts=13,
            limit_price=3.14,
        )

        assert result["status"] == "submitted"
        req = provider.client.submit_order.call_args.args[0]
        # min-credit floor of $3.14 ⇒ Alpaca MLEG limit must be -3.14
        assert req.limit_price == -3.14
        assert str(req.order_class).lower().endswith("mleg")
        # strategy-intent reporting stays positive (credit received)
        assert result["limit_price"] == 3.14

    def test_open_credit_spread_rounds_to_cents(self):
        provider = _make_provider()
        provider.submit_credit_spread(
            ticker="SPY",
            short_strike=730.0,
            long_strike=718.0,
            expiration="2026-07-24",
            spread_type="bull_put",
            contracts=1,
            limit_price=1.20500001,
        )
        req = provider.client.submit_order.call_args.args[0]
        assert req.limit_price == pytest.approx(-1.21)

    def test_close_spread_limit_stays_positive_debit_cap(self):
        provider = _make_provider()
        result = provider.close_spread(
            ticker="SPY",
            short_strike=736.0,
            long_strike=724.0,
            expiration="2026-07-24",
            spread_type="bull_put",
            contracts=14,
            limit_price=1.55,
        )
        assert result["status"] == "submitted"
        req = provider.client.submit_order.call_args.args[0]
        # buy-to-close pays a debit ⇒ positive limit is the correct sign
        assert req.limit_price == 1.55


# ═══════════════════════════════════════════════════════════════════════════
# Shared stub for MultilegOrderRequest paths (alpaca-py 0.38.0 pinned in
# requirements.txt does not export MultilegOrderRequest, so we stub the SDK
# modules to exercise the guarded-import code path).
# ═══════════════════════════════════════════════════════════════════════════

class _StubMultilegOrderRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.limit_price = kwargs.get("limit_price")


class _StubOptionLegRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture()
def stub_alpaca_mleg_sdk(monkeypatch):
    requests_mod = types.ModuleType("alpaca.trading.requests")
    requests_mod.MultilegOrderRequest = _StubMultilegOrderRequest
    requests_mod.OptionLegRequest = _StubOptionLegRequest

    enums_mod = types.ModuleType("alpaca.trading.enums")
    for name in ("OrderSide", "TimeInForce", "OrderClass"):
        enum_stub = MagicMock(name=name)
        setattr(enums_mod, name, enum_stub)
    enums_mod.OrderSide.BUY = "buy"
    enums_mod.OrderSide.SELL = "sell"
    enums_mod.TimeInForce.DAY = "day"
    enums_mod.TimeInForce.GTC = "gtc"
    enums_mod.OrderClass.MLEG = "mleg"

    trading_mod = types.ModuleType("alpaca.trading")
    trading_mod.requests = requests_mod
    trading_mod.enums = enums_mod
    alpaca_mod = types.ModuleType("alpaca")
    alpaca_mod.trading = trading_mod

    monkeypatch.setitem(sys.modules, "alpaca", alpaca_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading", trading_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums_mod)
    return requests_mod


def _spread_order(net_credit):
    from compass.alpaca_connector import OptionLeg, SpreadOrder

    legs = [
        OptionLeg(ticker="SPY", expiration="2026-07-24", strike=730.0,
                  option_type="P", side="SELL", quantity=1),
        OptionLeg(ticker="SPY", expiration="2026-07-24", strike=718.0,
                  option_type="P", side="BUY", quantity=1),
    ]
    return SpreadOrder(
        stream="exp1220",
        strategy="bull_put_spread",
        legs=legs,
        net_credit=net_credit,
        client_order_id="test-cid",
    )


class TestCompassConnectorMlegSign:
    def test_submit_spread_negates_net_credit(self, stub_alpaca_mleg_sdk):
        from compass.alpaca_connector import AlpacaConnector

        conn = object.__new__(AlpacaConnector)
        conn._sdk = "alpaca-py"
        conn._trading_client = MagicMock()
        resp = MagicMock()
        resp.id = "ord-2"
        resp.status = "accepted"
        conn._trading_client.submit_order.return_value = resp

        order = _spread_order(net_credit=3.14)
        out = conn.submit_spread(order)

        assert out.status != "REJECTED"
        req = conn._trading_client.submit_order.call_args.kwargs["order_data"]
        assert req.limit_price == -3.14

    def test_submit_spread_debit_intent_maps_to_positive_cap(self, stub_alpaca_mleg_sdk):
        from compass.alpaca_connector import AlpacaConnector

        conn = object.__new__(AlpacaConnector)
        conn._sdk = "alpaca-py"
        conn._trading_client = MagicMock()
        conn._trading_client.submit_order.return_value = MagicMock(id="x", status="accepted")

        # debit intent (e.g. calendar) expressed as negative net_credit
        order = _spread_order(net_credit=-1.25)
        conn.submit_spread(order)
        req = conn._trading_client.submit_order.call_args.kwargs["order_data"]
        assert req.limit_price == 1.25


class TestOrderRouterMlegSign:
    def test_atomic_mleg_negates_net_credit(self, stub_alpaca_mleg_sdk):
        from compass.orchestrator.order_router import OrderRouter

        router = object.__new__(OrderRouter)
        connector = MagicMock()
        resp = MagicMock()
        resp.id = "ord-3"
        resp.status = "accepted"
        connector._trading_client.submit_order.return_value = resp
        router.connector = connector

        spread = _spread_order(net_credit=2.83)
        broker_id, status, reasons = router._submit_atomic_mleg(spread)

        assert broker_id == "ord-3"
        req = connector._trading_client.submit_order.call_args.kwargs["order_data"]
        assert req.limit_price == -2.83
