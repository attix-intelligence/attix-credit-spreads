"""Broker-agnostic account / position models.

Concrete brokers — Alpaca, the IBKR-via-executor service, and any future
addition — report account state in their own native shapes. The dashboard
and the equity-history writer should never have to read those shapes
directly. These dataclasses are the lingua franca every adapter normalises
into.

``AccountSnapshot`` captures everything a dashboard card needs to render
NAV, cash, day P&L, and the equity-history aggregate. ``Position`` carries
an OCC-encoded option symbol so IBKR option spreads render identically to
Alpaca option spreads in the positions table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal, Optional


@dataclass
class AccountSnapshot:
    """One read of an account: NAV plus the P&L cuts the dashboard surfaces.

    ``broker`` is the literal name the dashboard renders ("Alpaca",
    "IBKR") so the card never has to guess. ``as_of`` is the time of the
    read at the dashboard side (the broker's clock-skew is rarely worth
    showing the user — the round-trip latency is the dominant uncertainty).
    """

    broker: Literal["alpaca", "ibkr_executor"]
    nav: float
    cash: float
    buying_power: float
    unrealized_pnl: float
    realized_pnl_today: float
    margin_balance: float = 0.0
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Provenance hint — populated by adapters that wrap the existing
    # ``alpaca_live`` / ``executor_live`` modules so the legacy dict shape
    # remains accessible to call sites mid-migration.
    raw: Optional[dict] = None


@dataclass
class Position:
    """A single position. ``occ_symbol`` is set for options (and is what the
    dashboard renders as the row's symbol); ``underlying`` always carries
    the bare ticker for routing.

    For stock positions ``occ_symbol == underlying``; the option fields are
    None. That symmetry lets the renderer read one column and not branch.
    """

    occ_symbol: str
    underlying: str
    security_type: Literal["stock", "option"]
    qty: int
    avg_cost: float
    market_value: float
    current_price: float
    unrealized_pnl: float
    side: Literal["long", "short"]
    option_type: Optional[Literal["call", "put"]] = None
    strike: Optional[float] = None
    expiration: Optional[date] = None
    opened_at: Optional[datetime] = None
