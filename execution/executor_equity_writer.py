"""``ExecutorEquityWriter`` — equity-history writer for IBKR-via-executor
experiments.

Mirrors ``PositionMonitor._record_equity_point()`` for accounts that route
through the standalone executor service (no Alpaca client → the existing
PositionMonitor path can't read them). One canonical equity point per
(experiment, day) is upserted on every cycle; the last write of the day
wins. The dashboard's chart reads from the same ``equity_history`` table
regardless of source.

Wired into the scheduler tick alongside ``run_vrp_cycle()`` so writes
happen on the same ~60 s cadence the strategy runs at. Failure-silent by
design — equity persistence must never block the trading loop.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from shared.brokers import ExecutorBrokerAdapter
from shared.database import upsert_equity_point

logger = logging.getLogger(__name__)


class ExecutorEquityWriter:
    """Writes one equity_history point per cycle from the executor balance
    endpoint.

    The writer is initialised from environment variables — the same
    ``EXECUTOR_API_KEY_<SUFFIX>`` / ``EXECUTOR_BASE_URL_<SUFFIX>`` /
    ``EXECUTOR_ACCOUNT_ID_<SUFFIX>`` triple the dashboard uses. A
    subprocess for ``EXP-V8A-IBKR`` sees these as the un-suffixed
    ``EXECUTOR_*`` names after ``railway_worker.py`` strips the suffix, so
    this writer reads the un-suffixed form too.
    """

    def __init__(
        self,
        exp_id: str,
        db_path: Optional[str] = None,
        adapter: Optional[ExecutorBrokerAdapter] = None,
    ) -> None:
        self.exp_id = exp_id
        self.db_path = db_path
        # Dependency injection for the test seam; the prod path builds from
        # env vars in ``from_env``.
        self._adapter = adapter

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls, exp_id: str, db_path: Optional[str] = None
    ) -> Optional["ExecutorEquityWriter"]:
        """Build a writer from un-suffixed ``EXECUTOR_*`` env vars (the
        subprocess view after ``railway_worker.py`` translation). Returns
        ``None`` when any of the three required variables is missing —
        callers treat that as "no executor for this experiment, skip the
        write" rather than an error."""
        api_key = os.environ.get("EXECUTOR_API_KEY", "").strip()
        base_url = os.environ.get("EXECUTOR_BASE_URL", "").strip()
        account_id = os.environ.get("EXECUTOR_ACCOUNT_ID", "").strip()
        if not (api_key and base_url and account_id):
            return None
        normalized = exp_id.upper().replace("-", "")
        adapter = ExecutorBrokerAdapter(normalized, api_key, base_url, account_id)
        return cls(exp_id=exp_id, db_path=db_path, adapter=adapter)

    # ------------------------------------------------------------------
    # Cycle hook
    # ------------------------------------------------------------------

    def record_one_cycle(self) -> bool:
        """Poll the executor for current balance and upsert today's equity
        point. Returns ``True`` if a point was written, ``False`` on any
        skip/error (the caller logs at debug level — repeated transient
        failures shouldn't spam the trading log)."""
        if not self._adapter:
            return False
        try:
            snap = self._adapter.fetch_snapshot()
        except Exception as exc:
            logger.warning(
                "[exec-equity] %s snapshot failed (%s) — skipping write",
                self.exp_id, exc,
            )
            return False

        if snap.nav <= 0:
            # An IBKR account briefly reporting 0 during a gateway reconnect
            # would clobber the day's equity if we wrote it — skip instead.
            return False

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            upsert_equity_point(
                exp_id=self.exp_id,
                as_of_date=today,
                equity=snap.nav,
                realized_pnl=snap.realized_pnl_today,
                unrealized_pnl=snap.unrealized_pnl,
                source="executor",
                path=self.db_path,
            )
        except Exception as exc:
            logger.warning(
                "[exec-equity] %s upsert failed: %s", self.exp_id, exc,
            )
            return False

        logger.info(
            "[exec-equity] exp=%s date=%s equity=%.2f source=executor action=wrote",
            self.exp_id, today, snap.nav,
        )
        return True
