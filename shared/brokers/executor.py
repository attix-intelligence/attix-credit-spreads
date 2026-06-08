"""``ExecutorBrokerAdapter`` — broker-agnostic facade for an IBKR account
routed through the ``attix-intelligence/executor`` REST service.

Like the Alpaca adapter this is a thin wrapper over the existing
``web_dashboard.executor_live`` module: it re-projects the existing
Alpaca-shaped dict (the legacy shape ``html.py`` reads) into the new
broker-agnostic dataclasses. The data path is unchanged; the executor
keeps its ~60 s in-process cache. This module exists so the new
``ExecutorEquityWriter`` (and any future cross-broker rollup) can call
into one uniform interface.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from .models import AccountSnapshot, Position

logger = logging.getLogger(__name__)


class ExecutorBrokerAdapter:
    """Adapter for an IBKR experiment fronted by the executor service."""

    broker_name = "IBKR"

    def __init__(
        self,
        normalized_id: str,
        api_key: str,
        base_url: str,
        account_id: str,
    ) -> None:
        """``normalized_id`` is the env-var suffix (e.g. ``"EXPV8AIBKR"``).
        ``account_id`` is the executor's identifier for the IBKR account
        the experiment is bound to (e.g. ``"ibkr_tafintech-p11-paper"``)
        — passed as a query parameter on every executor REST call."""
        self.normalized_id = normalized_id
        self._api_key = api_key
        self._base_url = base_url
        self._account_id = account_id

    # ------------------------------------------------------------------
    # BrokerAdapter Protocol
    # ------------------------------------------------------------------

    def fetch_snapshot(self) -> AccountSnapshot:
        from web_dashboard import executor_live

        raw = executor_live.fetch_live_data(
            self.normalized_id, self._api_key, self._base_url, self._account_id,
        )
        if raw.get("error"):
            raise RuntimeError(f"executor {self.normalized_id}: {raw['error']}")
        equity = raw.get("equity")
        if equity is None:
            raise RuntimeError(
                f"executor {self.normalized_id}: balance read returned no equity"
            )
        return AccountSnapshot(
            broker="ibkr_executor",
            nav=float(equity),
            cash=float(raw.get("cash") or 0.0),
            buying_power=float(raw.get("buying_power") or 0.0),
            unrealized_pnl=float(raw.get("unrealized_pl") or 0.0),
            realized_pnl_today=float(raw.get("day_pl") or 0.0),
            as_of=_parse_iso(raw.get("fetched_at")) or datetime.now(timezone.utc),
            raw=raw,
        )

    def fetch_positions(self) -> List[Position]:
        from web_dashboard import executor_live

        raw = executor_live.fetch_live_data(
            self.normalized_id, self._api_key, self._base_url, self._account_id,
        )
        if raw.get("error"):
            return []
        return [_adapt_executor_position(p) for p in (raw.get("positions") or [])]

    def fetch_equity_history(
        self, start: Optional[date] = None, end: Optional[date] = None
    ) -> List[dict]:
        """The executor exposes no native equity-history endpoint; the
        ``ExecutorEquityWriter`` fills the dashboard's ``equity_history``
        table from snapshot polls and the chart reads from there."""
        return []


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------

def _adapt_executor_position(p: dict) -> Position:
    """Re-project an ``executor_live._adapt_position`` dict (which is the
    legacy Alpaca dict shape) into the broker-agnostic dataclass.

    The executor IBKR backend (PR companion in attix-intelligence/executor)
    populates ``symbol`` with the OCC code, ``strike`` / ``expiration`` /
    ``option_type`` as structured fields. When those are absent (older
    executor build) we fall back to underlying-only rendering."""
    sym = str(p.get("symbol") or "")
    sec_type = (
        "option"
        if (p.get("option_type") is not None
            or (len(sym) > 6 and any(c.isdigit() for c in sym[6:])))
        else "stock"
    )
    qty = int(float(p.get("qty") or 0))

    raw_opt = p.get("option_type")
    opt: Optional[str] = None
    if raw_opt in ("call", "put"):
        opt = raw_opt

    exp = p.get("expiration")
    if isinstance(exp, str):
        try:
            exp = date.fromisoformat(exp)
        except ValueError:
            exp = None

    strike = p.get("strike")
    try:
        strike = float(strike) if strike is not None else None
    except (TypeError, ValueError):
        strike = None

    underlying = sym if sec_type == "stock" else _occ_root(sym)
    return Position(
        occ_symbol=sym,
        underlying=underlying,
        security_type=sec_type,
        qty=qty,
        avg_cost=float(p.get("avg_entry_price") or 0.0),
        market_value=float(p.get("market_value") or 0.0),
        current_price=float(p.get("current_price") or 0.0),
        unrealized_pnl=float(p.get("unrealized_pl") or 0.0),
        side=("short" if (p.get("side") == "short" or qty < 0) else "long"),
        option_type=opt,
        strike=strike,
        expiration=exp if isinstance(exp, date) else None,
        opened_at=_parse_iso(p.get("opened_at")),
    )


def _occ_root(occ: str) -> str:
    return occ[:6].rstrip() if len(occ) >= 6 else occ


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
