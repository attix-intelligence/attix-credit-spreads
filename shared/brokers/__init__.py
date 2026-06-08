"""Broker-agnostic adapter layer.

The dashboard's existing ``alpaca_live`` and ``executor_live`` modules
remain the live-data path — adapters here re-project their output into
the ``AccountSnapshot`` / ``Position`` dataclasses so the new
aggregate-equity rollup and the ``ExecutorEquityWriter`` aren't coupled
to Alpaca's response shape.

Usage:

    from shared.brokers import get_adapter
    adapter = get_adapter(exp_id="EXP-V8A-IBKR", registry=registry_dict)
    if adapter:
        snap = adapter.fetch_snapshot()       # raises on transport failure
        positions = adapter.fetch_positions() # never raises

``get_adapter`` returns ``None`` when an experiment has no broker creds
configured for the running process — same diagnostic as the existing
``discover_experiment_keys`` pattern.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .alpaca import AlpacaBrokerAdapter
from .executor import ExecutorBrokerAdapter
from .models import AccountSnapshot, Position
from .protocol import BrokerAdapter

__all__ = [
    "AccountSnapshot",
    "AlpacaBrokerAdapter",
    "BrokerAdapter",
    "ExecutorBrokerAdapter",
    "Position",
    "get_adapter",
]

logger = logging.getLogger(__name__)


def _normalize(exp_id: str) -> str:
    return exp_id.upper().replace("-", "")


def get_adapter(
    exp_id: str, registry_entry: Optional[dict] = None
) -> Optional[BrokerAdapter]:
    """Build a ``BrokerAdapter`` for ``exp_id`` by dispatching on its
    registry ``broker`` field (and falling back to env-var discovery for
    legacy entries that pre-date the field).

    Returns ``None`` when no broker creds are configured for this
    experiment in the running process — the caller decides whether that's
    a render warning or just absence.
    """
    norm = _normalize(exp_id)
    broker_field = (registry_entry or {}).get("broker", "alpaca")

    # Executor-routed brokers all dispatch through the same adapter — the
    # account_id discriminates which IBKR account on the executor side.
    if str(broker_field).startswith("ibkr"):
        api_key = os.environ.get(f"EXECUTOR_API_KEY_{norm}", "").strip()
        base_url = os.environ.get(f"EXECUTOR_BASE_URL_{norm}", "").strip()
        account_id = (
            (registry_entry or {}).get("executor_account_id")
            or os.environ.get(f"EXECUTOR_ACCOUNT_ID_{norm}", "").strip()
        )
        if api_key and base_url and account_id:
            return ExecutorBrokerAdapter(norm, api_key, base_url, account_id)
        logger.debug(
            "[brokers] %s broker=%s but creds incomplete "
            "(api_key=%s base_url=%s account_id=%s) — no adapter",
            exp_id, broker_field,
            "set" if api_key else "missing",
            "set" if base_url else "missing",
            "set" if account_id else "missing",
        )
        return None

    # Default + explicit "alpaca": env-var-discovered keys.
    api_key = os.environ.get(f"ALPACA_API_KEY_{norm}", "").strip()
    api_secret = os.environ.get(f"ALPACA_API_SECRET_{norm}", "").strip()
    if api_key and api_secret:
        return AlpacaBrokerAdapter(norm, api_key, api_secret)
    return None
