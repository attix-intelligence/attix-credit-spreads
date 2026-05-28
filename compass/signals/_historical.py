"""Per-date historical tilt-signal builder.

Drives the existing ``compute_tilt_score`` pipeline (momentum + flow +
sentiment) over a universe of tickers against the historical
:class:`AthenaSignalDataProvider`. Produces one row per ticker with the
three family z-scores, the composite tilt_score, and metadata.

Architecture
------------
This module is intentionally thin — it only orchestrates. All feature
math lives in:

* ``compass.signals.momentum.compute_momentum_signal``
* ``compass.signals.flow_proxy.compute_flow_signal``
* ``compass.signals.sentiment_proxy.compute_sentiment_signal``
* ``compass.signals.tilt_score.compute_tilt_score``

The orchestrator's job is:

1. For each ticker in the universe, set ``provider.as_of = as_of`` (the
   Athena provider needs this — Polygon's live one doesn't).
2. Call ``compute_tilt_score(ticker, as_of, provider)``.
3. Collect per-ticker results into a DataFrame.

Output schema
-------------
Returned DataFrame columns::

    ticker         (str)   — uppercase
    kind           (str)   — "etf" | "stock" (from universe)
    sector         (str)   — universe metadata
    industry       (str)   — universe metadata
    momentum_z     (float) — None when insufficient history
    flow_z         (float) — None when chain unavailable
    sentiment_z    (float) — None when no front/back ATM contracts
    dark_flow_z    (float) — ALWAYS None for historical runs (no TradeAlgo
                             history endpoint; gate this off in backtester)
    tilt_score     (float) — weighted composite; None when < 2 families
    failed         (bool)  — True when tilt_score is None
    error          (str)   — short reason when failed=True; "" otherwise

Rule Zero
---------
* dark_flow_z is set to None (NOT 0.0) so downstream code sees the
  absence honestly. The backtest must gate dark-flow filtering off for
  historical dates.
* Any exception during per-ticker signal computation is caught and the
  ticker is emitted with ``failed=True`` and a short error string. No
  fabricated z-scores ever appear in the output.
* The orchestrator does NOT touch provider.as_of for any side-effect
  other than scoping the options_snapshot query to a single partition.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from typing import Any, Dict, List, Optional

import pandas as pd

from compass.signals.athena_provider import AthenaSignalDataProvider
from compass.signals.tilt_score import compute_tilt_score
from strategies.msr_universe import Universe, UniverseEntry

logger = logging.getLogger(__name__)

# Columns in the canonical output order — also enforced when emitting
# an empty DataFrame so downstream Parquet schemas are stable.
COLUMNS = (
    "ticker", "kind", "sector", "industry",
    "momentum_z", "flow_z", "sentiment_z", "dark_flow_z", "tilt_score",
    "failed", "error",
)


@dataclass(frozen=True)
class TickerResult:
    ticker: str
    kind: str
    sector: str
    industry: str
    momentum_z: Optional[float]
    flow_z: Optional[float]
    sentiment_z: Optional[float]
    dark_flow_z: Optional[float]  # always None for historical
    tilt_score: Optional[float]
    failed: bool
    error: str


def build_tilt_for_date(
    as_of: str | date_cls,
    universe: Universe,
    provider: AthenaSignalDataProvider,
    *,
    weights: Optional[Dict[str, float]] = None,
    on_progress: Optional[Any] = None,
) -> pd.DataFrame:
    """Compute the tilt-signal row for every ticker in ``universe`` at ``as_of``.

    Args:
        as_of:     ISO date string or ``date`` — the historical day to score.
        universe:  parsed :class:`Universe` from ``strategies/msr_universe.py``.
        provider:  Athena-backed provider; this function MUTATES
            ``provider.as_of`` to the given date.
        weights:   optional override of tilt-score family weights.
        on_progress: optional ``callable(ticker, idx, total)`` — invoked
            after each ticker (useful for CLI progress bars).

    Returns:
        DataFrame with one row per ticker (in universe order), columns
        as documented in the module docstring. Tickers whose signal
        computation raised are emitted with ``failed=True`` and a short
        ``error`` string.
    """
    as_of_str = as_of.isoformat() if isinstance(as_of, date_cls) else str(as_of)

    # Set ONCE — the options_snapshot query uses this as its date partition.
    # We leave it set throughout the universe pass; momentum/flow baseline
    # daily-bar calls don't consume provider.as_of (they get as_of via arg).
    provider.as_of = as_of_str

    entries: List[UniverseEntry] = [*universe.etfs, *universe.stocks]
    total = len(entries)
    rows: List[TickerResult] = []

    for idx, entry in enumerate(entries, start=1):
        result = _compute_one(entry, as_of_str, provider, weights=weights)
        rows.append(result)
        if on_progress is not None:
            try:
                on_progress(entry.ticker, idx, total)
            except Exception:  # pragma: no cover — progress callback errors must not abort run
                logger.exception("on_progress callback raised for %s", entry.ticker)

    return _to_dataframe(rows)


def _compute_one(
    entry: UniverseEntry,
    as_of: str,
    provider: AthenaSignalDataProvider,
    *,
    weights: Optional[Dict[str, float]],
) -> TickerResult:
    base = dict(
        ticker=entry.ticker,
        kind=entry.kind,
        sector=entry.sector,
        industry=entry.industry,
        dark_flow_z=None,   # historical: no TradeAlgo bundle endpoint
    )
    try:
        tilt = compute_tilt_score(
            entry.ticker, as_of, provider, weights=weights,
        )
    except Exception as e:
        logger.warning(
            "tilt failure %s @ %s: %s", entry.ticker, as_of, e,
        )
        return TickerResult(
            **base,
            momentum_z=None, flow_z=None, sentiment_z=None, tilt_score=None,
            failed=True, error=_short_err(e),
        )

    if tilt is None:
        # Sub-signals returned, but fewer than 2 families were available —
        # legitimate insufficient-data path, not an error.
        return TickerResult(
            **base,
            momentum_z=None, flow_z=None, sentiment_z=None, tilt_score=None,
            failed=True, error="insufficient_families",
        )

    return TickerResult(
        **base,
        momentum_z=_as_opt_float(tilt.get("momentum_z")),
        flow_z=_as_opt_float(tilt.get("flow_z")),
        sentiment_z=_as_opt_float(tilt.get("sentiment_z")),
        tilt_score=_as_opt_float(tilt.get("tilt_score")),
        failed=False, error="",
    )


def _to_dataframe(rows: List[TickerResult]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(COLUMNS))
    df = pd.DataFrame([r.__dict__ for r in rows], columns=list(COLUMNS))
    return df


def _as_opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _short_err(e: BaseException, *, max_len: int = 160) -> str:
    s = f"{type(e).__name__}: {e}"
    return s[:max_len]


__all__ = [
    "COLUMNS",
    "TickerResult",
    "build_tilt_for_date",
]
