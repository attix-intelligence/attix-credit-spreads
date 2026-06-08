"""Broker-agnostic adapter layer tests.

Covers ``shared.brokers``:
  * ``get_adapter()`` factory dispatch on the registry ``broker`` field,
  * ``AlpacaBrokerAdapter`` re-projection from the legacy dict shape,
  * ``ExecutorBrokerAdapter`` re-projection (with option fields populated),
  * Runtime ``BrokerAdapter`` ``isinstance`` so future adapters are caught
    by the type system, not by hope.

The existing ``alpaca_live`` and ``executor_live`` modules stay the live-
data path; these adapters wrap them so the new aggregate-equity rollup
and the executor equity writer aren't coupled to Alpaca's wire shape.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clean_broker_env(monkeypatch):
    """Strip both Alpaca and executor per-experiment env vars so dispatch
    starts from a clean slate every test (CI workers occasionally leak)."""
    import os
    for var in list(os.environ):
        if var.startswith(("ALPACA_API_KEY_EXP", "ALPACA_API_SECRET_EXP",
                           "EXECUTOR_API_KEY_EXP", "EXECUTOR_BASE_URL_EXP",
                           "EXECUTOR_ACCOUNT_ID_EXP")):
            monkeypatch.delenv(var, raising=False)


# =====================================================================
# Factory dispatch
# =====================================================================

def test_get_adapter_defaults_to_alpaca_when_broker_field_missing(monkeypatch):
    """Backward compat — a registry entry that pre-dates the ``broker``
    field must still dispatch to the Alpaca adapter (the rollout convention)."""
    from shared.brokers import AlpacaBrokerAdapter, get_adapter
    monkeypatch.setenv("ALPACA_API_KEY_EXP400", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_EXP400", "s")
    a = get_adapter("EXP-400", registry_entry={})
    assert isinstance(a, AlpacaBrokerAdapter)
    assert a.normalized_id == "EXP400"
    assert a.broker_name == "Alpaca"


def test_get_adapter_dispatches_to_executor_for_ibkr_paper(monkeypatch):
    from shared.brokers import ExecutorBrokerAdapter, get_adapter
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "k")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://x")
    entry = {"broker": "ibkr_paper", "executor_account_id": "ibkr_acct"}
    a = get_adapter("EXP-V8A-IBKR", registry_entry=entry)
    assert isinstance(a, ExecutorBrokerAdapter)
    assert a._account_id == "ibkr_acct"
    assert a.broker_name == "IBKR"


def test_get_adapter_returns_none_when_creds_missing(monkeypatch):
    """No env vars → no adapter. The caller treats absence as "skip this
    experiment", same diagnostic the existing live modules emit."""
    from shared.brokers import get_adapter
    assert get_adapter("EXP-400", {"broker": "alpaca"}) is None
    entry = {"broker": "ibkr_paper", "executor_account_id": "acct"}
    assert get_adapter("EXP-V8A-IBKR", entry) is None


def test_get_adapter_executor_uses_env_account_id_when_registry_missing(monkeypatch):
    """Registry can be silent on account_id and an env override picks up the
    slack. Either source works; registry wins when both are set."""
    from shared.brokers import ExecutorBrokerAdapter, get_adapter
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "k")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://x")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPV8AIBKR", "env-acct")
    a = get_adapter("EXP-V8A-IBKR", registry_entry={"broker": "ibkr_paper"})
    assert isinstance(a, ExecutorBrokerAdapter)
    assert a._account_id == "env-acct"


# =====================================================================
# AlpacaBrokerAdapter
# =====================================================================

def test_alpaca_adapter_projects_snapshot_from_raw_dict():
    """The adapter delegates to ``alpaca_live.fetch_live_data`` and re-shapes
    the dict into ``AccountSnapshot`` without touching the data path. The
    raw dict is preserved on ``snapshot.raw`` for mid-migration callers."""
    from shared.brokers import AlpacaBrokerAdapter
    from web_dashboard import alpaca_live

    fake_raw = {
        "equity": 101_466.78, "cash": 100_000.0, "buying_power": 200_000.0,
        "unrealized_pl": 312.50, "day_pl": -50.0, "positions": [],
        "orders": [], "error": None, "fetched_at": "2026-06-08T19:30:00+00:00",
    }
    a = AlpacaBrokerAdapter("EXP400", "k", "s")
    with patch.object(alpaca_live, "fetch_live_data", return_value=fake_raw):
        snap = a.fetch_snapshot()
    assert snap.broker == "alpaca"
    assert snap.nav == 101_466.78
    assert snap.cash == 100_000.0
    assert snap.buying_power == 200_000.0
    assert snap.unrealized_pnl == 312.50
    assert snap.realized_pnl_today == -50.0
    assert snap.raw is fake_raw  # mid-migration consumers can still read it


def test_alpaca_adapter_snapshot_raises_when_balance_errored():
    """Adapters MUST raise on transport failure so the caller can route to
    fallbacks. The legacy ``alpaca_live`` dict carries the error string in
    ``raw["error"]``; the adapter surfaces it as a RuntimeError."""
    from shared.brokers import AlpacaBrokerAdapter
    from web_dashboard import alpaca_live
    fake_raw = {"equity": None, "error": "account: 401 unauthorized",
                "positions": [], "orders": []}
    a = AlpacaBrokerAdapter("EXP400", "k", "s")
    with patch.object(alpaca_live, "fetch_live_data", return_value=fake_raw):
        with pytest.raises(RuntimeError, match="401 unauthorized"):
            a.fetch_snapshot()


def test_alpaca_adapter_positions_handle_string_qty():
    """Alpaca returns ``qty`` as a STRING from /v2/positions. The adapter
    must coerce so downstream consumers see typed fields."""
    from shared.brokers import AlpacaBrokerAdapter
    from web_dashboard import alpaca_live
    raw = {
        "equity": 100_000.0, "error": None,
        "positions": [
            {"symbol": "AAPL", "qty": "10", "side": "long",
             "avg_entry_price": "150.00", "current_price": "160.00",
             "market_value": "1600.00", "unrealized_pl": "100.00"},
            # OCC-encoded option symbol (Alpaca convention)
            {"symbol": "SPY   260618P00728000", "qty": "-1", "side": "short",
             "avg_entry_price": "2.50", "current_price": "2.00",
             "market_value": "-200.00", "unrealized_pl": "50.00"},
        ],
        "orders": [],
    }
    a = AlpacaBrokerAdapter("EXP400", "k", "s")
    with patch.object(alpaca_live, "fetch_live_data", return_value=raw):
        positions = a.fetch_positions()
    assert positions[0].qty == 10
    assert positions[0].security_type == "stock"
    assert positions[0].underlying == "AAPL"
    assert positions[1].qty == -1
    assert positions[1].security_type == "option"
    assert positions[1].underlying == "SPY"  # stripped from OCC padding
    assert positions[1].occ_symbol == "SPY   260618P00728000"
    assert positions[1].side == "short"


# =====================================================================
# ExecutorBrokerAdapter
# =====================================================================

def test_executor_adapter_projects_snapshot():
    from shared.brokers import ExecutorBrokerAdapter
    from web_dashboard import executor_live
    fake = {
        "equity": 100_500.0, "cash": 99_000.0, "buying_power": 400_000.0,
        "unrealized_pl": 250.0, "day_pl": 0.0, "positions": [], "orders": [],
        "error": None, "fetched_at": "2026-06-08T19:30:00+00:00",
        "broker": "ibkr_executor",
    }
    a = ExecutorBrokerAdapter("EXPV8AIBKR", "k", "https://x", "ibkr_acct")
    with patch.object(executor_live, "fetch_live_data", return_value=fake):
        snap = a.fetch_snapshot()
    assert snap.broker == "ibkr_executor"
    assert snap.nav == 100_500.0
    assert snap.cash == 99_000.0
    assert snap.buying_power == 400_000.0


def test_executor_adapter_positions_extract_option_fields():
    """When the executor IBKR backend populates structured option fields
    (the companion PR in attix-intelligence/executor), the adapter wires
    them straight through to the broker-agnostic ``Position``."""
    from shared.brokers import ExecutorBrokerAdapter
    from web_dashboard import executor_live
    fake = {
        "equity": 100_000.0, "error": None,
        "positions": [
            {"symbol": "SPY   260618P00728000", "qty": "-1", "side": "short",
             "avg_entry_price": "2.50", "current_price": "2.00",
             "market_value": "-200.00", "unrealized_pl": "50.00",
             "security_type": "option", "option_type": "put",
             "strike": 728.0, "expiration": "2026-06-18"},
        ],
        "orders": [],
    }
    a = ExecutorBrokerAdapter("EXPV8AIBKR", "k", "https://x", "ibkr_acct")
    with patch.object(executor_live, "fetch_live_data", return_value=fake):
        positions = a.fetch_positions()
    p = positions[0]
    assert p.security_type == "option"
    assert p.option_type == "put"
    assert p.strike == 728.0
    assert p.expiration == date(2026, 6, 18)
    assert p.occ_symbol == "SPY   260618P00728000"
    assert p.underlying == "SPY"


def test_executor_adapter_raises_on_balance_error():
    from shared.brokers import ExecutorBrokerAdapter
    from web_dashboard import executor_live
    fake = {"equity": None, "error": "balance: 408 timeout",
            "positions": [], "orders": []}
    a = ExecutorBrokerAdapter("EXPV8AIBKR", "k", "https://x", "ibkr_acct")
    with patch.object(executor_live, "fetch_live_data", return_value=fake):
        with pytest.raises(RuntimeError, match="408 timeout"):
            a.fetch_snapshot()


def test_executor_adapter_fetch_equity_history_returns_empty():
    """The executor exposes no native equity-history endpoint — the
    adapter MUST return ``[]`` so the dashboard's equity_history DB table
    remains the source of truth for the chart."""
    from shared.brokers import ExecutorBrokerAdapter
    a = ExecutorBrokerAdapter("EXPV8AIBKR", "k", "https://x", "ibkr_acct")
    assert a.fetch_equity_history() == []


# =====================================================================
# Protocol satisfaction
# =====================================================================

def test_both_adapters_satisfy_broker_adapter_protocol():
    """``BrokerAdapter`` is ``@runtime_checkable`` so adding a future
    Tradier adapter that forgets ``fetch_equity_history`` fails this
    isinstance check, not the runtime."""
    from shared.brokers import (
        AlpacaBrokerAdapter, BrokerAdapter, ExecutorBrokerAdapter,
    )
    assert isinstance(AlpacaBrokerAdapter("X", "k", "s"), BrokerAdapter)
    assert isinstance(
        ExecutorBrokerAdapter("X", "k", "https://x", "acct"), BrokerAdapter
    )
