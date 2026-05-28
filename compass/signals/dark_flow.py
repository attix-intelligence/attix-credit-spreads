"""Dark-flow signal — cross-sectional intensity z-score per ticker.

Thin adapter over :mod:`shared.tradealgo_darkflow`. The heavy lifting
(parsing the TradeAlgo bundle and computing the composite z-score) lives
in ``shared/`` because it is also consumed by the live trading path. This
module exposes a clean, per-ticker API that mirrors the shape of the
other ``compass.signals`` modules so the tilt-score / LLM-categorizer
pipeline can call it uniformly.

Inputs
------
* A TradeAlgo Daily Snapshot bundle — fetched via
  :class:`shared.tradealgo_client.TradeAlgoClient` or loaded from the
  on-disk cache (``data/tradealgo/{date}/snapshot.json``).

Outputs
-------
Per ticker::

    {
      "ticker":         "NVDA",
      "as_of":          "2026-05-27",
      "dark_flow_z":    1.83,         # None if < 2 valid sub-z components
      "side":           "up",         # "up" | "down"
      "cap_bucket":     "large",      # "small" | "medium" | "large"
      "multiplier":     4.21,
      "dollar_value":   89_400_000.0,
      "ats_dollar_volume_pct": 142.3,
    }

Returns ``None`` for tickers that do not appear in the bundle, so the
caller can apply the spec's ``dark_flow_z > 0`` entry gate fail-closed.

Rule Zero
---------
Z-scores are computed across the population of tickers **inside the
bundle**. No values are fabricated. When fewer than two components have
valid inputs, the composite is ``None`` (never a default).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from shared.tradealgo_darkflow import (
    DarkFlowRecord,
    darkflow_zscores,
    parse_movement_darkflow,
)

logger = logging.getLogger(__name__)


def _records_and_z(
    snapshot: Dict[str, Any],
) -> tuple[Dict[str, DarkFlowRecord], Dict[str, Optional[float]]]:
    records = parse_movement_darkflow(snapshot)
    z = darkflow_zscores(records)
    return records, z


def compute_dark_flow_signal(
    ticker: str,
    as_of: str | date,
    snapshot: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Single-ticker view over the cross-sectional dark-flow z-score.

    Returns ``None`` if ``ticker`` is not in the bundle.

    Note: building the z-score population requires scanning every ticker
    in the bundle, so calling this in a loop over many tickers wastes
    work. For batch use, call :func:`compute_dark_flow_batch` instead.
    """
    records, z = _records_and_z(snapshot)
    return _ticker_view(ticker, as_of, records, z)


def compute_dark_flow_batch(
    as_of: str | date,
    snapshot: Dict[str, Any],
    tickers: Optional[list[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute dark-flow signals for every ticker in the bundle.

    Args:
        as_of: ISO date string or ``date`` — copied verbatim to outputs.
        snapshot: parsed TradeAlgo bundle (``TradeAlgoClient.fetch_snapshot``).
        tickers: optional whitelist; tickers outside the bundle are
            simply omitted from the result (fail-closed).

    Returns:
        ``{ticker_upper: signal_dict}``. Tickers not in the bundle do
        NOT appear as keys — the absence is the signal.
    """
    records, z = _records_and_z(snapshot)
    out: Dict[str, Dict[str, Any]] = {}
    requested: Optional[set[str]] = None
    if tickers is not None:
        requested = {t.upper() for t in tickers}

    for sym in records:
        if requested is not None and sym not in requested:
            continue
        view = _ticker_view(sym, as_of, records, z)
        if view is not None:
            out[sym] = view
    return out


def _ticker_view(
    ticker: str,
    as_of: str | date,
    records: Dict[str, DarkFlowRecord],
    z_by_ticker: Dict[str, Optional[float]],
) -> Optional[Dict[str, Any]]:
    sym = ticker.upper()
    rec = records.get(sym)
    if rec is None:
        return None

    as_of_str = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
    return {
        "ticker":               sym,
        "as_of":                as_of_str,
        "dark_flow_z":          z_by_ticker.get(sym),
        "side":                 rec.side,
        "cap_bucket":           rec.cap_bucket,
        "multiplier":           rec.multiplier,
        "dollar_value":         rec.dollar_value,
        "ats_dollar_volume_pct": rec.ats_dollar_volume_pct,
    }


__all__ = [
    "compute_dark_flow_signal",
    "compute_dark_flow_batch",
]
