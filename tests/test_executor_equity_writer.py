"""``ExecutorEquityWriter`` tests — discovery from env vars, upsert
behaviour, and failure-silent semantics on the trading-loop hot path.

The writer is the IBKR equivalent of ``PositionMonitor._record_equity_point``
for accounts that route through the executor (V8A-IBKR has no Alpaca
client). It writes one canonical point per (exp_id, day) so the dashboard
chart reads from the same table regardless of broker.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_executor_env(monkeypatch):
    """Strip un-suffixed EXECUTOR_* env vars so each test starts from a
    deterministic state — the writer reads the un-suffixed form because
    ``railway_worker.py`` translates the per-experiment suffix away in the
    subprocess."""
    import os
    for var in list(os.environ):
        if var.startswith("EXECUTOR_"):
            monkeypatch.delenv(var, raising=False)


# =====================================================================
# from_env constructor
# =====================================================================

def test_from_env_returns_none_when_no_creds(monkeypatch):
    """No env vars → no writer. Caller treats ``None`` as a skip, not an
    error — every non-executor experiment hits this path on every cycle."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    assert ExecutorEquityWriter.from_env("EXP-V8A-IBKR") is None


def test_from_env_returns_none_when_partial_creds(monkeypatch):
    """API_KEY alone is not enough — without BASE_URL+ACCOUNT_ID the
    writer must not silently construct (a half-configured writer would
    raise on every cycle and spam the log)."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    monkeypatch.setenv("EXECUTOR_API_KEY", "k")
    assert ExecutorEquityWriter.from_env("EXP-V8A-IBKR") is None
    monkeypatch.setenv("EXECUTOR_BASE_URL", "https://x")
    assert ExecutorEquityWriter.from_env("EXP-V8A-IBKR") is None


def test_from_env_builds_writer_when_all_three_present(monkeypatch):
    from execution.executor_equity_writer import ExecutorEquityWriter
    monkeypatch.setenv("EXECUTOR_API_KEY", "k")
    monkeypatch.setenv("EXECUTOR_BASE_URL", "https://x")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID", "ibkr_acct")
    w = ExecutorEquityWriter.from_env("EXP-V8A-IBKR")
    assert w is not None
    assert w.exp_id == "EXP-V8A-IBKR"
    assert w._adapter is not None
    assert w._adapter._account_id == "ibkr_acct"


# =====================================================================
# record_one_cycle
# =====================================================================

def _adapter_returning(nav=120_000.0, unrealized=250.0, realized=10.0):
    """Build an in-memory adapter stand-in so we don't have to hit the
    executor live module from a unit test."""
    from datetime import datetime, timezone
    from shared.brokers.models import AccountSnapshot
    snap = AccountSnapshot(
        broker="ibkr_executor", nav=nav, cash=100_000.0,
        buying_power=400_000.0, unrealized_pnl=unrealized,
        realized_pnl_today=realized,
        as_of=datetime(2026, 6, 8, 19, 30, tzinfo=timezone.utc),
    )
    adapter = MagicMock()
    adapter.fetch_snapshot.return_value = snap
    return adapter


def test_record_one_cycle_upserts_with_executor_source():
    """Happy path — the writer calls ``upsert_equity_point`` with
    source="executor" so dashboard queries can distinguish IBKR-sourced
    rows from Alpaca-sourced rows by the source column."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    w = ExecutorEquityWriter(
        exp_id="EXP-V8A-IBKR", adapter=_adapter_returning(nav=120_000.0),
    )
    with patch("execution.executor_equity_writer.upsert_equity_point") as mock_up:
        wrote = w.record_one_cycle()
    assert wrote is True
    mock_up.assert_called_once()
    kwargs = mock_up.call_args.kwargs
    assert kwargs["exp_id"] == "EXP-V8A-IBKR"
    assert kwargs["equity"] == 120_000.0
    assert kwargs["realized_pnl"] == 10.0
    assert kwargs["unrealized_pnl"] == 250.0
    assert kwargs["source"] == "executor"


def test_record_one_cycle_skips_zero_nav_to_avoid_overwrite():
    """During an IBKR gateway reconnect ib_insync briefly reports zero NAV.
    Writing it would clobber the day's good equity (upsert overwrites).
    Skip and let the next cycle reclaim the real value."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    w = ExecutorEquityWriter(
        exp_id="EXP-V8A-IBKR", adapter=_adapter_returning(nav=0.0),
    )
    with patch("execution.executor_equity_writer.upsert_equity_point") as mock_up:
        wrote = w.record_one_cycle()
    assert wrote is False
    mock_up.assert_not_called()


def test_record_one_cycle_silent_on_fetch_failure():
    """The trading loop must never be blocked by equity persistence.
    ``fetch_snapshot`` raising ⇒ log + skip; no exception bubbles up."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    adapter = MagicMock()
    adapter.fetch_snapshot.side_effect = RuntimeError("408 timeout")
    w = ExecutorEquityWriter(exp_id="EXP-V8A-IBKR", adapter=adapter)
    with patch("execution.executor_equity_writer.upsert_equity_point") as mock_up:
        wrote = w.record_one_cycle()
    assert wrote is False
    mock_up.assert_not_called()


def test_record_one_cycle_silent_on_db_failure():
    """A locked DB / disk full must not bubble up either — same rationale."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    w = ExecutorEquityWriter(
        exp_id="EXP-V8A-IBKR", adapter=_adapter_returning(nav=120_000.0),
    )
    with patch(
        "execution.executor_equity_writer.upsert_equity_point",
        side_effect=RuntimeError("database is locked"),
    ):
        wrote = w.record_one_cycle()
    assert wrote is False


def test_record_one_cycle_uses_utc_today():
    """The day key is UTC — same convention as PositionMonitor — so a
    21:00 ET (next-day-UTC) snapshot still files under the right date."""
    from execution.executor_equity_writer import ExecutorEquityWriter
    w = ExecutorEquityWriter(
        exp_id="EXP-V8A-IBKR", adapter=_adapter_returning(nav=120_000.0),
    )
    with patch("execution.executor_equity_writer.upsert_equity_point") as mock_up:
        w.record_one_cycle()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert mock_up.call_args.kwargs["as_of_date"] == today
