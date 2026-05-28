"""Dark-flow feature extraction from a TradeAlgo Daily Snapshot bundle.

Inputs come from :func:`shared.tradealgo_client.TradeAlgoClient.fetch_snapshot`
(or its on-disk cache). The bundle exposes dark-flow movers across three cap
sizes in ``movement/darkflow-{small,medium,large}.json`` and a rolling
history in ``historical-darkflow/daily-darkflow-{up,down}.json``.

Public surface
--------------
* :func:`parse_movement_darkflow` — flatten the 3 movement files into a
  ``{ticker: DarkFlowRecord}`` map, deduping if a ticker appears in
  multiple cap sizes (keeps highest ``multiplier``).
* :func:`darkflow_zscores` — cross-sectional z-score per ticker, averaging
  ``multiplier``, ``log(dollar_value)``, and ``ats.compared.day_dollar_volume``.
  The result is an intensity z-score (unsigned by side) suitable for
  feeding into :func:`compass.signals.flow_proxy.compute_flow_signal` as
  an additional component. Direction (trending_up vs trending_down) is
  preserved on the :class:`DarkFlowRecord` for callers that want to fold
  side into their own composite — this module deliberately does not pick
  a sign-aware formula because the right way to combine intensity + side
  + options sentiment is strategy-dependent.
* :func:`parse_historical_darkflow` — flatten the rolling history file
  into a list of flagging events (raw, no aggregation).
* :func:`top_darkflow` — top-N tickers by chosen feature for ad-hoc
  inspection / dashboards.

Design notes
------------
* The schema is documented in ``docs/tradealgo_api.md``. ``multiplier``,
  ``dollar_value``, and ``market_cap`` arrive as **strings** in the JSON
  and must be coerced to float by the parser.
* The cross-sectional z-score uses the distribution of values **within
  the current bundle** (all tickers, both trending_up and trending_down,
  across all three cap sizes — typically ~60 records). It is NOT a
  historical baseline.
* Z-scores use sample stddev (``ddof=1``). If fewer than 2 valid values
  exist or stddev is zero, the function returns ``None`` for that
  feature — fail-closed, never fabricated.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Module paths inside the snapshot bundle.
_MOVEMENT_PATHS = (
    "movement/darkflow-small.json",
    "movement/darkflow-medium.json",
    "movement/darkflow-large.json",
)
_HIST_UP_PATH = "historical-darkflow/daily-darkflow-up.json"
_HIST_DOWN_PATH = "historical-darkflow/daily-darkflow-down.json"


@dataclass(frozen=True)
class DarkFlowRecord:
    """Per-ticker dark-flow features from a movement/darkflow-*.json file."""

    ticker: str
    side: str                 # "up" | "down"
    cap_bucket: str           # "small" | "medium" | "large"
    multiplier: float
    dollar_value: float
    perf: Optional[float]
    market_cap: Optional[float]
    last_price: Optional[float]
    # options sub-object — None if has_options=False or sub-dict missing
    flow_sentiment: Optional[float]
    call_flow: Optional[float]
    put_to_call: Optional[float]
    call_total_prem: Optional[float]
    put_total_prem: Optional[float]
    # ats.compared.day_dollar_volume — % of trailing avg (e.g. 67.32)
    ats_dollar_volume_pct: Optional[float]


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_from_entry(
    entry: Dict[str, Any],
    *,
    side: str,
    cap_bucket: str,
) -> Optional[DarkFlowRecord]:
    ticker = entry.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None

    multiplier = _coerce_float(entry.get("multiplier"))
    dollar_value = _coerce_float(entry.get("dollar_value"))
    if multiplier is None or dollar_value is None:
        return None  # parser contract: drop records that fail core coercion

    options = entry.get("options") or {}
    ats = entry.get("ats") or {}
    compared = ats.get("compared") or {}

    return DarkFlowRecord(
        ticker=ticker.upper(),
        side=side,
        cap_bucket=cap_bucket,
        multiplier=multiplier,
        dollar_value=dollar_value,
        perf=_coerce_float(entry.get("perf")),
        market_cap=_coerce_float(entry.get("market_cap")),
        last_price=_coerce_float(entry.get("last_price")),
        flow_sentiment=_coerce_float(options.get("flow_sentiment")),
        call_flow=_coerce_float(options.get("call_flow")),
        put_to_call=_coerce_float(options.get("put_to_call")),
        call_total_prem=_coerce_float(options.get("call_total_prem")),
        put_total_prem=_coerce_float(options.get("put_total_prem")),
        ats_dollar_volume_pct=_coerce_float(compared.get("day_dollar_volume")),
    )


def parse_movement_darkflow(snapshot: Dict[str, Any]) -> Dict[str, DarkFlowRecord]:
    """Flatten all 3 movement/darkflow-*.json files into a ticker map.

    When the same ticker appears in multiple cap-size buckets (rare but
    possible during the small↔medium boundary), the record with the
    highest ``multiplier`` wins.
    """
    records: Dict[str, DarkFlowRecord] = {}
    for path in _MOVEMENT_PATHS:
        cap_bucket = path.split("-")[-1].replace(".json", "")
        module = snapshot.get(path)
        if not isinstance(module, dict):
            continue
        for side_key, side_value in (("trending_up", "up"), ("trending_down", "down")):
            entries = module.get(side_key) or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                rec = _record_from_entry(entry, side=side_value, cap_bucket=cap_bucket)
                if rec is None:
                    continue
                prev = records.get(rec.ticker)
                if prev is None or rec.multiplier > prev.multiplier:
                    records[rec.ticker] = rec
    return records


# ----- z-score machinery --------------------------------------------------

def _zscore(value: float, population: Iterable[float]) -> Optional[float]:
    pop = [p for p in population if p is not None and math.isfinite(p)]
    if len(pop) < 2:
        return None
    mu = mean(pop)
    sd = stdev(pop)  # sample stddev, ddof=1
    if sd == 0:
        return None
    return (value - mu) / sd


def darkflow_zscores(
    records: Dict[str, DarkFlowRecord],
) -> Dict[str, Optional[float]]:
    """Cross-sectional intensity z-score per ticker.

    The composite averages the z-scores of:
      * ``multiplier``                      (DarkFlow algo strength)
      * ``log(dollar_value)``               (heavy-tailed → log-transform)
      * ``ats_dollar_volume_pct``           (% of trailing-avg ATS volume)

    Returns ``{ticker: composite_z or None}``. ``None`` when fewer than 2
    components had valid z-scores for that ticker.
    """
    if not records:
        return {}

    multipliers = [r.multiplier for r in records.values()]
    log_dollars = [math.log(r.dollar_value) for r in records.values() if r.dollar_value > 0]
    ats_pcts = [r.ats_dollar_volume_pct for r in records.values()
                if r.ats_dollar_volume_pct is not None and math.isfinite(r.ats_dollar_volume_pct)]

    out: Dict[str, Optional[float]] = {}
    for ticker, rec in records.items():
        components: List[float] = []

        z_mult = _zscore(rec.multiplier, multipliers)
        if z_mult is not None:
            components.append(z_mult)

        if rec.dollar_value > 0:
            z_dol = _zscore(math.log(rec.dollar_value), log_dollars)
            if z_dol is not None:
                components.append(z_dol)

        if rec.ats_dollar_volume_pct is not None and math.isfinite(rec.ats_dollar_volume_pct):
            z_ats = _zscore(rec.ats_dollar_volume_pct, ats_pcts)
            if z_ats is not None:
                components.append(z_ats)

        out[ticker] = float(mean(components)) if len(components) >= 2 else None
    return out


# ----- historical pass-through --------------------------------------------

def parse_historical_darkflow(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the rolling daily-darkflow history as a flat list.

    Each entry has at minimum::

        ticker, company_name, date_added, added_price,
        date_remove, removed_price, performance, trending_status

    Returns the union of ``daily-darkflow-up.json`` and
    ``daily-darkflow-down.json`` in source order. Performs no aggregation
    — callers can group by ticker, filter by date, etc.
    """
    out: List[Dict[str, Any]] = []
    for path in (_HIST_UP_PATH, _HIST_DOWN_PATH):
        module = snapshot.get(path) or []
        if isinstance(module, list):
            out.extend(e for e in module if isinstance(e, dict))
    return out


# ----- inspection helpers -------------------------------------------------

def top_darkflow(
    records: Dict[str, DarkFlowRecord],
    *,
    n: int = 10,
    side: Optional[str] = "up",
    sort_by: str = "dollar_value",
) -> List[DarkFlowRecord]:
    """Top-N records by ``sort_by`` (one of: dollar_value, multiplier, perf).

    ``side`` filters to ``"up"`` / ``"down"`` / ``None`` (both).
    """
    if sort_by not in {"dollar_value", "multiplier", "perf"}:
        raise ValueError(f"sort_by must be one of dollar_value|multiplier|perf, got {sort_by}")

    candidates: List[DarkFlowRecord] = []
    for rec in records.values():
        if side is not None and rec.side != side:
            continue
        key_val = getattr(rec, sort_by)
        if key_val is None:
            continue
        candidates.append(rec)

    candidates.sort(key=lambda r: getattr(r, sort_by) or 0.0, reverse=True)
    return candidates[:n]
