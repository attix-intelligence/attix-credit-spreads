"""The ``BrokerAdapter`` Protocol — every broker integration the dashboard
reads from must implement these three methods.

A broker that doesn't expose historical equity (the executor today) returns
an empty list from ``fetch_equity_history``; the dashboard's
``equity_history`` table is the source of truth so the missing history
isn't lost — the writer fills it from the snapshot it polls.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Protocol, runtime_checkable

from .models import AccountSnapshot, Position


@runtime_checkable
class BrokerAdapter(Protocol):
    """Read-only adapter — the dashboard never executes through this
    layer. Order-routing stays in the concrete strategy code (Alpaca
    direct, ``OrderSink`` -> executor, …)."""

    #: Human-readable broker name for diagnostics and error rendering.
    broker_name: str

    def fetch_snapshot(self) -> AccountSnapshot:
        """Current NAV / cash / unrealized P&L for this experiment's account.

        Adapters MUST raise (not return None) on transport failure so the
        caller can log + fall back. The 60-second cache lives in the
        underlying live-data module — repeated calls within that window
        return the same data without a network round-trip.
        """
        ...

    def fetch_positions(self) -> List[Position]:
        """Currently open positions, in broker-agnostic form."""
        ...

    def fetch_equity_history(
        self, start: Optional[date] = None, end: Optional[date] = None
    ) -> List[dict]:
        """Historical equity points, ascending by date.

        Brokers that don't expose history natively return ``[]``. The
        dashboard's equity_history DB table backfills from the
        ``ExecutorEquityWriter`` poll cadence so the chart still renders.
        """
        ...
