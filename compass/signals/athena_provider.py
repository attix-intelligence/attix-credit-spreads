"""Athena-backed signal data provider for historical signal reconstruction.

Mirrors the public interface of :class:`compass.signals._data.PolygonSignalDataProvider`
so the pure feature-computation functions in ``compass.signals.flow_proxy``,
``compass.signals.sentiment_proxy``, and ``compass.signals.momentum`` can be
reused unchanged against historical CBOE Athena option candles.

Why a separate provider?
------------------------
Polygon's ``/v3/snapshot/options/{ticker}`` endpoint is live-only — it has
no per-date history. CBOE 60-min option candles ARE historical (14+ years of
partitioned 60-minute bars per contract) and are already wired up via
``backtest/spx_athena_chain.py``. This module reuses the same boto3 +
partition-pruning pattern, but generalised to any underlying and shaped to
the :class:`OptionContract` dataclass that the signal modules consume.

Interface compatibility
-----------------------
The following methods mirror ``PolygonSignalDataProvider`` exactly so they
can be swapped via dependency injection:

* ``options_snapshot(underlying, *, expiration_lte=None, expiration_gte=None,
  limit=250, max_pages=20)`` — returns ``list[OptionContract]``.
* ``stock_trades(ticker, date, *, min_size=100, limit=50000)`` — returns
  ``[]``. CBOE Athena does not store stock prints; the ``large_prints_$``
  feature drops out of ``flow_z`` via the existing fail-closed logic
  (``components_z[fname] = None`` when the feature is missing — see
  ``flow_proxy._features_from_chain_and_trades``). flow_z still has 4 valid
  components (oi_total / vol_total / put_call_ratio / vol_oi_ratio).
* ``stock_daily_bars(ticker, from_date, to_date)`` — delegates to
  :func:`backtest.market_history.load_market_history` and reshapes the
  yfinance-style DataFrame to the Polygon list[dict] schema
  (``[{"t":..., "o":..., "h":..., "l":..., "c":..., "v":...}, ...]``).

State: ``as_of``
----------------
Polygon's ``options_snapshot`` is implicitly "now". Athena needs a date.
Rather than break the interface, this provider exposes a mutable ``as_of``
attribute that the orchestrator sets per date BEFORE each call::

    provider = AthenaSignalDataProvider()
    for d in trading_dates:
        provider.as_of = d.isoformat()      # ← MUST be set
        result = compute_flow_signal("SPY", d.isoformat(), provider)

Calling ``options_snapshot`` with ``as_of`` unset raises ``RuntimeError``.

Rule Zero
---------
* No fabricated data. Every contract row originates from a CBOE Athena bar.
* No look-ahead. The partition filter restricts scans to ``year/month/day ==
  as_of``; no rows from later dates can leak in.
* Stock prints: we return ``[]`` HONESTLY rather than mocking — the
  large_prints feature degrades to None for that day, and the composite
  z-score averages over the remaining valid components.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Union

import boto3
import pandas as pd

from compass.signals._data import OptionContract

logger = logging.getLogger(__name__)

ATHENA_TABLE_60MIN = "cboe_60min_option_candles"

# 16:00 ET close-of-session — match the bar timing used elsewhere in the
# backtest pipeline. CBOE 60-min candles publish a bar starting at 15:00 ET
# covering 15:00-16:00, which is the canonical "EOD" snapshot for daily
# signal reconstruction.
DEFAULT_TARGET_HOUR = 15


class AthenaSignalDataProvider:
    """Historical equivalent of :class:`PolygonSignalDataProvider`.

    Pulls a per-date options chain snapshot from CBOE Athena and exposes
    it via the same method shape that the live Polygon provider uses, so
    the pure feature functions in ``compass.signals.*`` are reusable.
    """

    def __init__(
        self,
        database: Optional[str] = None,
        output_bucket: Optional[str] = None,
        region: Optional[str] = None,
        table: str = ATHENA_TABLE_60MIN,
        target_hour: int = DEFAULT_TARGET_HOUR,
    ) -> None:
        self.database = database or os.environ["ATHENA_DATABASE"]
        self.output_bucket = output_bucket or os.environ["ATHENA_OUTPUT_BUCKET"]
        self.region = region or os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1")
        self.client = boto3.client("athena", region_name=self.region)
        self.table = table
        self.target_hour = target_hour

        # Set by the orchestrator before each date's signal computation.
        # We deliberately do NOT default this to today() — that would
        # invite silent look-ahead. Better to fail loudly.
        self.as_of: Optional[str] = None

        # Diagnostics — reset externally if you want per-batch totals.
        self._bytes_scanned = 0
        self._queries = 0

    # ------------------------------------------------------------------
    # Live HTTP equivalents
    # ------------------------------------------------------------------

    def options_snapshot(
        self,
        underlying: str,
        *,
        expiration_lte: Optional[str] = None,
        expiration_gte: Optional[str] = None,
        limit: int = 250,             # accepted for interface compat; unused
        max_pages: int = 20,          # accepted for interface compat; unused
    ) -> List[OptionContract]:
        """Return the historical EOD options-chain snapshot for ``underlying``.

        Requires ``self.as_of`` to be set to an ISO date. Returns ``[]``
        when no rows exist for the date/underlying.

        ``expiration_lte`` / ``expiration_gte``: ISO dates limiting the
        expiration window. By default the SQL also filters
        ``expiration >= as_of`` so already-expired contracts (i.e. rows
        from a 0DTE that already settled at the morning open) don't
        appear with stale-looking IVs.
        """
        del limit, max_pages  # interface compat
        if not self.as_of:
            raise RuntimeError(
                "AthenaSignalDataProvider.options_snapshot called before "
                "as_of was set. Set provider.as_of = '<YYYY-MM-DD>' before "
                "each per-date signal computation."
            )

        as_of = self.as_of
        y, m, d = as_of.split("-")
        upper = underlying.upper()

        # The expiration column in CBOE candles is DATE. Use DATE literals
        # for safe comparison. Default lower bound is as_of so already-
        # settled contracts are excluded.
        exp_floor = expiration_gte or as_of
        exp_clauses = [f"expiration >= DATE '{exp_floor}'"]
        if expiration_lte:
            exp_clauses.append(f"expiration <= DATE '{expiration_lte}'")
        exp_sql = " AND ".join(exp_clauses)

        sql = f"""
            SELECT strike, option_type, quote_timestamp, expiration,
                   bid_close, ask_close, close_px,
                   implied_volatility, delta,
                   open_interest, trade_volume
            FROM {self.table}
            WHERE year='{y}' AND month='{m}' AND day='{d}'
              AND symbol='{upper}'
              AND {exp_sql}
        """
        df = self._execute(sql)
        if df.empty:
            return []

        # Coerce numerics; quote_timestamp → datetime.
        for col in ("strike", "bid_close", "ask_close", "close_px",
                    "implied_volatility", "delta"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("open_interest", "trade_volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
        df["quote_timestamp"] = pd.to_datetime(df["quote_timestamp"])

        # Per-(strike, option_type, expiration) keep the row whose hour is
        # closest to (but not after) target_hour. Falls back to the latest
        # available bar when target_hour is past the last bar of the day.
        df["_hour"] = df["quote_timestamp"].dt.hour
        eligible = df[df["_hour"] <= self.target_hour]
        if eligible.empty:
            eligible = df
        snapshot = (
            eligible
            .sort_values("_hour", ascending=False)
            .drop_duplicates(subset=["strike", "option_type", "expiration"], keep="first")
            .reset_index(drop=True)
        )

        return [
            _row_to_contract(row, upper)
            for _, row in snapshot.iterrows()
            if _row_to_contract(row, upper) is not None
        ]

    def stock_trades(
        self,
        ticker: str,
        date: str,
        *,
        min_size: int = 100,
        limit: int = 50000,
    ) -> List[Dict]:
        """Return ``[]`` honestly. CBOE Athena does not store stock prints.

        The ``large_prints_$`` feature degrades to ``None`` in
        ``flow_proxy._features_from_chain_and_trades`` (sum is 0 → caller
        treats as missing component). Composite ``flow_z`` averages over
        the remaining valid components.
        """
        del ticker, date, min_size, limit
        return []

    def stock_daily_bars(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
    ) -> List[Dict]:
        """Daily OHLCV bars reshaped to Polygon list[dict] format.

        Delegates to :func:`backtest.market_history.load_market_history`
        (Polygon stock aggregates + SQLite indices bootstrap). Returns
        ``[]`` on empty result.
        """
        from backtest.market_history import load_market_history

        df = load_market_history(ticker, from_date, to_date)
        if df.empty:
            return []
        out: List[Dict] = []
        for ts, row in df.iterrows():
            # millisecond epoch — matches Polygon's "t" semantics
            t_ms = int(pd.Timestamp(ts).value // 1_000_000)
            out.append({
                "t": t_ms,
                "o": float(row.get("Open"))   if pd.notna(row.get("Open"))   else None,
                "h": float(row.get("High"))   if pd.notna(row.get("High"))   else None,
                "l": float(row.get("Low"))    if pd.notna(row.get("Low"))    else None,
                "c": float(row.get("Close"))  if pd.notna(row.get("Close"))  else None,
                "v": float(row.get("Volume")) if pd.notna(row.get("Volume")) else None,
            })
        return out

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def bytes_scanned_mb(self) -> float:
        return self._bytes_scanned / 1e6

    @property
    def queries_issued(self) -> int:
        return self._queries

    def reset_counters(self) -> None:
        self._bytes_scanned = 0
        self._queries = 0

    # ------------------------------------------------------------------
    # Athena execution (mirrors backtest/spx_athena_chain.py)
    # ------------------------------------------------------------------

    def _execute(self, query: str, max_wait_s: int = 120) -> pd.DataFrame:
        resp = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.database},
            ResultConfiguration={"OutputLocation": self.output_bucket},
        )
        qid = resp["QueryExecutionId"]
        for _ in range(max_wait_s):
            info = self.client.get_query_execution(QueryExecutionId=qid)
            state = info["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            if state in ("FAILED", "CANCELLED"):
                reason = info["QueryExecution"]["Status"].get("StateChangeReason", "")
                raise RuntimeError(f"Athena {state}: {reason}\nSQL: {query[:200]}")
            time.sleep(1)
        else:
            raise TimeoutError(f"Athena query {qid} timed out")

        stats = info["QueryExecution"].get("Statistics", {})
        self._bytes_scanned += stats.get("DataScannedInBytes", 0)
        self._queries += 1

        rows: list[list[str]] = []
        paginator = self.client.get_paginator("get_query_results")
        for page in paginator.paginate(QueryExecutionId=qid):
            for r in page["ResultSet"]["Rows"]:
                rows.append([col.get("VarCharValue") for col in r["Data"]])
        if not rows:
            return pd.DataFrame()
        cols = rows[0]
        return pd.DataFrame(rows[1:], columns=cols)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

_OPT_TYPE_MAP = {
    "C": "call", "CALL": "call", "call": "call",
    "P": "put",  "PUT":  "put",  "put":  "put",
}


def _row_to_contract(row: pd.Series, underlying: str) -> Optional[OptionContract]:
    """Map a single Athena candle row → :class:`OptionContract`.

    Returns ``None`` when essential identifiers (strike, expiration, type)
    are unparseable. ``bid``/``ask``/``iv``/``delta``/``open_interest``/
    ``day_volume`` are allowed to be missing — downstream signal modules
    handle ``None`` gracefully.
    """
    strike = row.get("strike")
    if pd.isna(strike):
        return None
    raw_type = str(row.get("option_type") or "").strip()
    opt_type = _OPT_TYPE_MAP.get(raw_type) or _OPT_TYPE_MAP.get(raw_type.upper())
    if opt_type is None:
        return None
    expiration = row.get("expiration")
    if expiration is None or (isinstance(expiration, float) and pd.isna(expiration)):
        return None
    exp_str = str(expiration)[:10]  # already ISO-shaped from Athena DATE

    # Synthesize a contract symbol in OCC-style (used only for traceability;
    # downstream signal modules don't parse this).
    exp_compact = exp_str.replace("-", "")[2:]  # YYMMDD
    cp = "C" if opt_type == "call" else "P"
    strike_int = int(round(float(strike) * 1000))
    contract_sym = f"O:{underlying}{exp_compact}{cp}{strike_int:08d}"

    bid = _to_float(row.get("bid_close"))
    ask = _to_float(row.get("ask_close"))
    last = _to_float(row.get("close_px"))
    iv = _to_float(row.get("implied_volatility"))
    delta = _to_float(row.get("delta"))
    oi_raw = row.get("open_interest")
    vol_raw = row.get("trade_volume")
    oi = int(oi_raw) if oi_raw is not None and not pd.isna(oi_raw) else None
    vol = int(vol_raw) if vol_raw is not None and not pd.isna(vol_raw) else None

    return OptionContract(
        contract_symbol=contract_sym,
        underlying=underlying,
        expiration=exp_str,
        strike=float(strike),
        option_type=opt_type,
        bid=bid,
        ask=ask,
        last=last,
        iv=iv,
        delta=delta,
        open_interest=oi,
        day_volume=vol,
    )


def _to_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "ATHENA_TABLE_60MIN",
    "DEFAULT_TARGET_HOUR",
    "AthenaSignalDataProvider",
]
