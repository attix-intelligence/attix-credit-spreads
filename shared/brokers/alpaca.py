"""``AlpacaBrokerAdapter`` — thin wrapper around the existing
``web_dashboard.alpaca_live`` module.

This adapter doesn't change the Alpaca data path. It re-projects the
existing dict shape into the broker-agnostic ``AccountSnapshot`` /
``Position`` dataclasses so that anything reading through the Protocol
layer sees the same fields whether the underlying broker is Alpaca or
the IBKR-via-executor service.

Existing call sites in ``data.py`` / ``html.py`` continue to read
``s["alpaca"]`` directly; nothing forces them to migrate at the same
time. The adapter exists for the new aggregate-equity and equity-writer
code paths that don't have to inherit the legacy dict shape.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from .models import AccountSnapshot, Position

logger = logging.getLogger(__name__)


class AlpacaBrokerAdapter:
    """Adapter for an Alpaca-routed experiment."""

    broker_name = "Alpaca"

    def __init__(self, normalized_id: str, api_key: str, api_secret: str) -> None:
        """``normalized_id`` is ``"EXP400"`` (no dashes, upper) — matches the
        env-var suffix the existing ``discover_experiment_keys`` returns."""
        self.normalized_id = normalized_id
        self._api_key = api_key
        self._api_secret = api_secret

    # ------------------------------------------------------------------
    # BrokerAdapter Protocol
    # ------------------------------------------------------------------

    def fetch_snapshot(self) -> AccountSnapshot:
        """Cached 60-second read of ``/v2/account``. Errors raise so callers
        can route to the fallback path; the underlying module surfaces the
        error string in ``raw["error"]`` for diagnostics."""
        from web_dashboard import alpaca_live

        raw = alpaca_live.fetch_live_data(
            self.normalized_id, self._api_key, self._api_secret
        )
        if raw.get("error"):
            raise RuntimeError(f"alpaca {self.normalized_id}: {raw['error']}")
        equity = raw.get("equity")
        if equity is None:
            raise RuntimeError(
                f"alpaca {self.normalized_id}: account read returned no equity"
            )
        return AccountSnapshot(
            broker="alpaca",
            nav=float(equity),
            cash=float(raw.get("cash") or 0.0),
            buying_power=float(raw.get("buying_power") or 0.0),
            unrealized_pnl=float(raw.get("unrealized_pl") or 0.0),
            realized_pnl_today=float(raw.get("day_pl") or 0.0),
            as_of=_parse_iso(raw.get("fetched_at")) or datetime.now(timezone.utc),
            raw=raw,
        )

    def fetch_positions(self) -> List[Position]:
        from web_dashboard import alpaca_live

        raw = alpaca_live.fetch_live_data(
            self.normalized_id, self._api_key, self._api_secret
        )
        if raw.get("error"):
            return []
        return [_adapt_alpaca_position(p) for p in (raw.get("positions") or [])]

    def fetch_equity_history(
        self, start: Optional[date] = None, end: Optional[date] = None
    ) -> List[dict]:
        """Alpaca exposes ``/v2/account/portfolio/history``; the existing
        ``shared.equity_backfill`` module owns that path. This adapter is a
        read-only seam — backfill stays where the heavy lifting lives."""
        return []


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------

def _adapt_alpaca_position(p: dict) -> Position:
    """Project the Alpaca dict into the broker-agnostic dataclass. The
    ``symbol`` field on /v2/positions IS the OCC-encoded option symbol for
    options and the bare ticker for stocks, so it doubles as
    ``occ_symbol`` / ``underlying`` respectively. Strike + expiration
    aren't parsed out today — when a consumer wants them we'll decode the
    OCC string here."""
    sym = str(p.get("symbol") or "")
    sec_type = "option" if len(sym) > 6 and any(c.isdigit() for c in sym[6:]) else "stock"
    qty = int(float(p.get("qty") or 0))
    return Position(
        occ_symbol=sym,
        underlying=sym if sec_type == "stock" else _occ_root(sym),
        security_type=sec_type,
        qty=qty,
        avg_cost=float(p.get("avg_entry_price") or 0.0),
        market_value=float(p.get("market_value") or 0.0),
        current_price=float(p.get("current_price") or 0.0),
        unrealized_pnl=float(p.get("unrealized_pl") or 0.0),
        side=("short" if (p.get("side") == "short" or qty < 0) else "long"),
        opened_at=_parse_iso(p.get("opened_at")),
    )


def _occ_root(occ: str) -> str:
    """OCC encoding right-pads the root to 6 chars. Strip the pad to
    recover the underlying ticker (e.g. ``"SPY   "`` → ``"SPY"``)."""
    return occ[:6].rstrip() if len(occ) >= 6 else occ


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
