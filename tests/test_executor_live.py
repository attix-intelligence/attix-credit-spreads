"""Tests for ``web_dashboard.executor_live`` — env-var-driven discovery of
per-experiment executor creds, the executor-→-Alpaca shape adapter, and
the cached fetch path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_executor_env(monkeypatch):
    """Strip any EXECUTOR_* env vars leaking in from CI so discovery starts
    from a clean slate per test."""
    for var in list(__import__("os").environ):
        if var.startswith(("EXECUTOR_API_KEY_EXP", "EXECUTOR_BASE_URL_EXP", "EXECUTOR_ACCOUNT_ID_EXP")):
            monkeypatch.delenv(var, raising=False)
    # Reset the module cache too — otherwise a prior test's data sticks around
    # for the cache-TTL window and the next test's discover finds nothing new.
    from web_dashboard import executor_live
    executor_live._cache.clear()


def test_discovery_requires_full_triple(monkeypatch, caplog):
    """API_KEY alone is not enough — without BASE_URL+ACCOUNT_ID we skip and
    warn so a half-configured deploy is diagnosable from logs."""
    from web_dashboard import executor_live
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "user-key")
    # BASE_URL + ACCOUNT_ID missing
    keys = executor_live.discover_experiment_keys()
    assert keys == {}
    assert any(
        "EXECUTOR_BASE_URL_EXPV8AIBKR" in rec.message
        and "EXECUTOR_ACCOUNT_ID_EXPV8AIBKR" in rec.message
        for rec in caplog.records
    )


def test_discovery_finds_full_triple(monkeypatch):
    from web_dashboard import executor_live
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "user-key")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://exec.example.com")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPV8AIBKR", "ibkr_tafintech-p11-paper")
    keys = executor_live.discover_experiment_keys()
    assert keys == {
        "EXPV8AIBKR": (
            "user-key",
            "https://exec.example.com",
            "ibkr_tafintech-p11-paper",
        )
    }


def test_discovery_ignores_blank_api_key(monkeypatch):
    """Present-but-empty ``EXECUTOR_API_KEY_*`` must NOT count as configured —
    the empty-string footgun."""
    from web_dashboard import executor_live
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://exec.example.com")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPV8AIBKR", "ibkr_tafintech-p11-paper")
    assert executor_live.discover_experiment_keys() == {}


def test_normalize_strips_dashes():
    from web_dashboard import executor_live
    assert executor_live._normalize("EXP-V8A-IBKR") == "EXPV8AIBKR"
    assert executor_live._normalize("expv8aibkr") == "EXPV8AIBKR"


def test_adapt_position_stock_long():
    """A long stock position from the executor becomes the Alpaca-shaped dict
    html.py renders. ``qty`` is a string (Alpaca's convention)."""
    from web_dashboard import executor_live
    src = {
        "symbol": "AAPL",
        "security_type": "stock",
        "quantity": 100,
        "average_cost": 260.89,
        "current_price": 270.0,
        "market_value": 27000.0,
        "unrealized_pnl": 911.0,
        "unrealized_pnl_pct": 3.49,
        "day_pnl": None,
        "option_type": None,
        "strike": None,
        "expiration": None,
    }
    out = executor_live._adapt_position(src)
    assert out["symbol"] == "AAPL"
    assert out["qty"] == "100"
    assert out["side"] == "long"
    assert out["market_value"] == "27000.0"
    assert out["unrealized_pl"] == "911.0"
    assert out["avg_entry_price"] == "260.89"
    assert out["opened_at"] is None
    assert out["security_type"] == "stock"


def test_adapt_position_short_quantity_flips_side():
    from web_dashboard import executor_live
    out = executor_live._adapt_position({
        "symbol": "SPY", "quantity": -50, "market_value": -25000,
        "unrealized_pnl": 0, "average_cost": 500, "current_price": 500,
    })
    assert out["qty"] == "-50"
    assert out["side"] == "short"


def test_adapt_position_passes_option_fields():
    from web_dashboard import executor_live
    out = executor_live._adapt_position({
        "symbol": "SPY", "security_type": "option", "quantity": 1,
        "average_cost": 2.5, "current_price": 2.0,
        "market_value": 200, "unrealized_pnl": -50,
        "option_type": "put", "strike": 500.0, "expiration": "2026-06-30",
    })
    assert out["option_type"] == "put"
    assert out["strike"] == 500.0
    assert out["expiration"] == "2026-06-30"


def _mock_balance():
    return {
        "total_equity": 1042243.02,
        "cash": 975235.73,
        "buying_power": 4022843.78,
        "margin_balance": 31076.61,
        "unrealized_pnl": 29621.33,
        "realized_pnl_today": 0.0,
        "positions_count": 5,
    }


def _mock_positions():
    return [
        {"symbol": "AAPL", "security_type": "stock", "quantity": 1,
         "average_cost": 260.89, "current_price": 0.0, "market_value": 0.0,
         "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0, "day_pnl": None,
         "option_type": None, "strike": None, "expiration": None},
        {"symbol": "MSFT", "security_type": "stock", "quantity": 18,
         "average_cost": 470.24, "current_price": 0.0, "market_value": 0.0,
         "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0, "day_pnl": None,
         "option_type": None, "strike": None, "expiration": None},
    ]


def test_fetch_live_data_happy_path():
    """Balance + positions wire through to the Alpaca-shaped dict the renderer
    expects, with the executor field mappings honoured."""
    from web_dashboard import executor_live

    def fake_get(base_url, api_key, path, params=None):
        assert api_key == "user-key"
        assert base_url == "https://exec.example.com"
        assert params == {"account_id": "ibkr_tafintech-p11-paper"}
        if path == "/v1/portfolio/balance":
            return _mock_balance()
        if path == "/v1/portfolio/positions":
            return _mock_positions()
        raise AssertionError(f"unexpected path {path}")

    with patch.object(executor_live, "_get", side_effect=fake_get):
        out = executor_live.fetch_live_data(
            "EXPV8AIBKR", "user-key",
            "https://exec.example.com", "ibkr_tafintech-p11-paper",
        )

    assert out["error"] is None
    assert out["equity"] == 1042243.02
    assert out["cash"] == 975235.73
    assert out["buying_power"] == 4022843.78
    assert out["unrealized_pl"] == 29621.33
    assert out["day_pl"] == 0.0
    assert out["broker"] == "ibkr_executor"
    assert len(out["positions"]) == 2
    assert out["positions"][0]["symbol"] == "AAPL"
    assert out["positions"][0]["qty"] == "1"
    assert out["positions"][1]["symbol"] == "MSFT"


def test_fetch_live_data_balance_error_aborts():
    """Balance failure short-circuits — positions aren't even attempted."""
    from web_dashboard import executor_live

    def fake_get(base_url, api_key, path, params=None):
        if path == "/v1/portfolio/balance":
            raise RuntimeError("502 bad gateway")
        raise AssertionError("positions must not be fetched after balance failure")

    with patch.object(executor_live, "_get", side_effect=fake_get):
        out = executor_live.fetch_live_data(
            "EXPV8AIBKR", "k", "https://x", "acct",
        )

    assert out["error"] and "502 bad gateway" in out["error"]
    assert out["equity"] is None
    assert out["positions"] == []


def test_fetch_live_data_positions_error_non_fatal():
    """Positions failure leaves balance fields populated and positions=[]."""
    from web_dashboard import executor_live

    def fake_get(base_url, api_key, path, params=None):
        if path == "/v1/portfolio/balance":
            return _mock_balance()
        raise RuntimeError("positions 500")

    with patch.object(executor_live, "_get", side_effect=fake_get):
        out = executor_live.fetch_live_data(
            "EXPV8AIBKR", "k", "https://x", "acct",
        )

    assert out["error"] is None
    assert out["equity"] == 1042243.02
    assert out["positions"] == []


def test_get_live_executor_returns_none_without_creds(monkeypatch):
    from web_dashboard import executor_live
    # No env vars set
    assert executor_live.get_live_executor("EXP-V8A-IBKR") is None


def test_get_live_executor_caches(monkeypatch):
    from web_dashboard import executor_live
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "k")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://x")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPV8AIBKR", "acct")

    fetch_mock = MagicMock(return_value={
        "equity": 1.0, "fetched_at": "x", "error": None,
        "positions": [], "orders": [], "buying_power": 0, "cash": 0,
        "unrealized_pl": 0, "day_pl": 0, "broker": "ibkr_executor",
    })
    with patch.object(executor_live, "fetch_live_data", fetch_mock):
        a = executor_live.get_live_executor("EXP-V8A-IBKR")
        b = executor_live.get_live_executor("EXP-V8A-IBKR")
        c = executor_live.get_live_executor("expv8aibkr")  # accent-insensitive

    assert a is b is c
    assert fetch_mock.call_count == 1


def test_get_all_live_executor_skips_when_no_keys(monkeypatch):
    from web_dashboard import executor_live
    assert executor_live.get_all_live_executor() == {}


def test_get_all_live_executor_fanout(monkeypatch):
    from web_dashboard import executor_live
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPV8AIBKR", "k1")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPV8AIBKR", "https://x")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPV8AIBKR", "acct1")
    monkeypatch.setenv("EXECUTOR_API_KEY_EXPFOO", "k2")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXPFOO", "https://y")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXPFOO", "acct2")

    def fake_fetch(norm, k, base, acct):
        return {"equity": 1.0, "norm": norm, "error": None,
                "positions": [], "orders": [], "buying_power": 0,
                "cash": 0, "unrealized_pl": 0, "day_pl": 0,
                "fetched_at": "x", "broker": "ibkr_executor"}

    with patch.object(executor_live, "fetch_live_data", side_effect=fake_fetch):
        out = executor_live.get_all_live_executor()
    assert set(out) == {"EXPV8AIBKR", "EXPFOO"}


# ---------------------------------------------------------------------------
# Broker tag derivation (Tradier-via-executor support)
# ---------------------------------------------------------------------------

def test_broker_tag_for_account():
    from web_dashboard import executor_live
    assert executor_live.broker_tag_for_account("tradier_6YA42569") == "tradier"
    assert executor_live.broker_tag_for_account("ibkr_tafintech-p11-paper") == "ibkr_executor"
    assert executor_live.broker_tag_for_account("") == "ibkr_executor"


def test_fetch_live_data_stamps_tradier_broker():
    """A tradier_* executor account must label the card 'Tradier', not 'IBKR',
    and carry via_executor so the renderer knows the routing."""
    from web_dashboard import executor_live

    def fake_get(base_url, api_key, path, params=None):
        if path == "/v1/portfolio/balance":
            return _mock_balance()
        if path == "/v1/portfolio/positions":
            return []
        raise AssertionError(f"unexpected path {path}")

    with patch.object(executor_live, "_get", side_effect=fake_get):
        out = executor_live.fetch_live_data(
            "EXP800TRADIER", "k", "https://x", "tradier_6YA42569",
        )

    assert out["error"] is None
    assert out["broker"] == "tradier"
    assert out["via_executor"] is True


# ---------------------------------------------------------------------------
# Live-trading card augmentation (data.query_live_trading_experiments)
# ---------------------------------------------------------------------------

def test_live_trading_rows_get_executor_injection(monkeypatch):
    """Real-money cards (account_type=live) must run the same live-executor
    injection pipeline as paper cards — regression test for the empty
    EXP-800-TRADIER card (equity/positions present at broker, card blank)."""
    from web_dashboard import data as dash_data
    from web_dashboard import executor_live

    exp = {
        "id": "EXP-800-TRADIER",
        "name": "EXP-800 Safe Kelly 9/7/4 — Tradier LIVE",
        "account_type": "live",
        "broker": "tradier_live",
        "account_id": "tradier_6YA42569",
        "status": "active",
    }
    base_row = {
        "id": "EXP-800-TRADIER", "name": exp["name"], "ticker": "SPY",
        "total_closed": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "total_pnl": 0.0, "open_count": 0, "error": "Database not found",
    }
    monkeypatch.setattr(dash_data, "get_live_trading_experiments", lambda: [exp])
    monkeypatch.setattr(dash_data, "query_experiment", lambda e, report_date=None: dict(base_row))

    monkeypatch.setenv("EXECUTOR_API_KEY_EXP800TRADIER", "k")
    monkeypatch.setenv("EXECUTOR_BASE_URL_EXP800TRADIER", "https://exec.example.com")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID_EXP800TRADIER", "tradier_6YA42569")

    def fake_get(base_url, api_key, path, params=None):
        assert params == {"account_id": "tradier_6YA42569"}
        if path == "/v1/portfolio/balance":
            return {"total_equity": 132992.24, "cash": 132992.24,
                    "buying_power": 0.0, "unrealized_pnl": 0.0,
                    "realized_pnl_today": 0.0}
        if path == "/v1/portfolio/positions":
            return []
        raise AssertionError(f"unexpected path {path}")

    with patch.object(executor_live, "_get", side_effect=fake_get):
        rows = dash_data.query_live_trading_experiments()

    assert len(rows) == 1
    row = rows[0]
    assert row["alpaca"] is not None
    assert row["alpaca"]["equity"] == 132992.24
    assert row["alpaca"]["broker"] == "tradier"
    assert row["data_source"] == "live"
    assert row["is_live_trading"] is True
    assert row["broker"] == "tradier_live"
