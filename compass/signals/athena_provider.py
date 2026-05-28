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
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple, Union

import boto3
import pandas as pd

from compass.signals._data import OptionContract

# Validation for symbols going into a SQL IN-clause. CBOE symbols are
# upper-case letters, may have a leading ^ (for indices like ^SPX), and
# can include digits or "." in rare cases (e.g. BRK.B). We exclude
# quote characters defensively even though the universe YAML doesn't
# contain any.
_SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.]{0,9}$")

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

        # Batched-chain cache (MSR-200f). Key:
        #     (as_of, expiration_lte_or_None, expiration_gte_or_None)
        # Value: dict of symbol_upper → list[OptionContract] for that prefetch.
        # options_snapshot consults this BEFORE issuing a per-symbol query.
        # A cache miss falls back to the existing per-symbol query so the
        # interface stays compatible with tests that don't prefetch.
        self._chain_cache: Dict[
            Tuple[str, Optional[str], Optional[str]],
            Dict[str, List[OptionContract]],
        ] = {}

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

        Cache (MSR-200f)
        ----------------
        If :meth:`prefetch_chains` has populated the cache with a
        matching ``(as_of, expiration_lte, expiration_gte)`` key, the
        cached list is returned without issuing any Athena query. A
        cache miss falls back to a single-symbol query so unit tests
        and live calls work without prefetching.
        """
        del limit, max_pages  # interface compat
        if not self.as_of:
            raise RuntimeError(
                "AthenaSignalDataProvider.options_snapshot called before "
                "as_of was set. Set provider.as_of = '<YYYY-MM-DD>' before "
                "each per-date signal computation."
            )
        upper = underlying.upper()

        # Cache-first lookup — MSR-200f optimization.
        cache_key = (self.as_of, expiration_lte, expiration_gte)
        cached = self._chain_cache.get(cache_key)
        if cached is not None:
            # A prefetch covered this (as_of, window). Return the symbol's
            # list (possibly empty) — the absence of the symbol from the
            # cache dict is identical to "no rows for this symbol".
            return list(cached.get(upper, ()))

        # Cache miss → per-symbol query (legacy path; preserved for tests
        # and ad-hoc calls).
        df = self._fetch_chain_df(
            symbols=[upper],
            exp_floor=expiration_gte or self.as_of,
            exp_lte=expiration_lte,
            include_symbol_column=False,
        )
        return self._snapshot_for_symbol(df, upper)

    def prefetch_chains(
        self,
        symbols: Iterable[str],
        *,
        expiration_lte: Optional[str] = None,
        expiration_gte: Optional[str] = None,
    ) -> int:
        """Pre-fetch chains for a batch of symbols in a SINGLE Athena query.

        MSR-200f optimization. Issues one query with ``symbol IN (…)`` over
        the year/month/day partition for ``self.as_of`` (~55 MB scanned
        regardless of symbol count, vs ~55 MB × N for the per-symbol path).

        Args:
            symbols: iterable of underlying symbols (upper-case A-Z plus
                optional ``^`` prefix for indices; validated against
                :data:`_SYMBOL_RE`).
            expiration_lte / expiration_gte: ISO dates — same semantics
                as :meth:`options_snapshot`. ``expiration_gte`` defaults
                to ``self.as_of`` so already-settled contracts are
                excluded.

        Returns:
            The number of symbols populated in the cache (i.e. symbols
            for which at least one row was returned).

        Subsequent :meth:`options_snapshot` calls with the same
        ``(expiration_lte, expiration_gte)`` window will read from the
        cache without issuing additional queries.
        """
        if not self.as_of:
            raise RuntimeError(
                "AthenaSignalDataProvider.prefetch_chains called before "
                "as_of was set."
            )

        clean = self._clean_symbols(symbols)
        if not clean:
            return 0

        df = self._fetch_chain_df(
            symbols=clean,
            exp_floor=expiration_gte or self.as_of,
            exp_lte=expiration_lte,
            include_symbol_column=True,
        )

        # Pre-create empty entries for every requested symbol — so a
        # later options_snapshot lookup distinguishes "prefetched and
        # symbol had no rows" from "prefetch never happened" (the latter
        # falls through to per-symbol query).
        per_symbol: Dict[str, List[OptionContract]] = {s: [] for s in clean}
        if not df.empty:
            for sym, sub in df.groupby("symbol"):
                sym_upper = str(sym).upper()
                per_symbol[sym_upper] = self._snapshot_for_symbol(
                    sub.drop(columns=["symbol"]), sym_upper,
                )

        cache_key = (self.as_of, expiration_lte, expiration_gte)
        self._chain_cache[cache_key] = per_symbol
        return sum(1 for v in per_symbol.values() if v)

    def clear_chain_cache(self) -> None:
        """Drop all prefetched chains. Called between dates by the orchestrator
        when you want to bound peak memory."""
        self._chain_cache.clear()

    # ---- private helpers (shared by per-symbol + batched paths) ---------

    def _fetch_chain_df(
        self,
        *,
        symbols: List[str],
        exp_floor: str,
        exp_lte: Optional[str],
        include_symbol_column: bool,
    ) -> pd.DataFrame:
        """Issue ONE Athena query for ``symbols`` and return the raw DataFrame.

        Coerces numeric columns + ``quote_timestamp``. Does NOT do the
        per-(strike, option_type, expiration) dedup — callers handle
        that via :meth:`_snapshot_for_symbol` on a per-symbol slice.
        """
        if not symbols:
            return pd.DataFrame()
        y, m, d = self.as_of.split("-")  # type: ignore[union-attr]

        exp_clauses = [f"expiration >= DATE '{exp_floor}'"]
        if exp_lte:
            exp_clauses.append(f"expiration <= DATE '{exp_lte}'")
        exp_sql = " AND ".join(exp_clauses)

        if len(symbols) == 1:
            sym_sql = f"symbol = '{symbols[0]}'"
        else:
            sym_sql = "symbol IN (" + ", ".join(f"'{s}'" for s in symbols) + ")"

        select_cols = (
            "symbol, " if include_symbol_column else ""
        ) + (
            "strike, option_type, quote_timestamp, expiration, "
            "bid_close, ask_close, close_px, "
            "implied_volatility, delta, "
            "open_interest, trade_volume"
        )

        sql = f"""
            SELECT {select_cols}
            FROM {self.table}
            WHERE year='{y}' AND month='{m}' AND day='{d}'
              AND {sym_sql}
              AND {exp_sql}
        """
        df = self._execute(sql)
        if df.empty:
            return df

        for col in ("strike", "bid_close", "ask_close", "close_px",
                    "implied_volatility", "delta"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("open_interest", "trade_volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
        df["quote_timestamp"] = pd.to_datetime(df["quote_timestamp"])
        return df

    def _snapshot_for_symbol(
        self, df: pd.DataFrame, underlying_upper: str,
    ) -> List[OptionContract]:
        """Apply the per-(strike, option_type, expiration) EOD dedup to one
        symbol's rows and return the OptionContract list."""
        if df.empty:
            return []
        df = df.copy()
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
            _row_to_contract(row, underlying_upper)
            for _, row in snapshot.iterrows()
            if _row_to_contract(row, underlying_upper) is not None
        ]

    @staticmethod
    def _clean_symbols(symbols: Iterable[str]) -> List[str]:
        """Validate + uppercase + de-duplicate the symbol list (preserves order)."""
        seen: set[str] = set()
        out: List[str] = []
        for s in symbols:
            if s is None:
                continue
            up = str(s).strip().upper()
            if not up or up in seen:
                continue
            if not _SYMBOL_RE.match(up):
                raise ValueError(
                    f"Symbol {up!r} does not match expected pattern; refusing "
                    "to interpolate into Athena SQL."
                )
            seen.add(up)
            out.append(up)
        return out

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
