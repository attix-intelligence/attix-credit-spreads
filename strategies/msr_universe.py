"""Load the MSR signal-backfill universe from ``strategies/msr_universe.yaml``.

The universe drives the historical reconstruction of momentum_z / flow_z /
sentiment_z over the backfill window (see ``compass/signals/athena_provider.py``
and ``scripts/msr200_build_signals.py``).

Public surface
--------------
* :func:`load_universe(path=None)` → :class:`Universe`
* :class:`Universe` exposes ``tickers``, ``etfs``, ``stocks``, ``by_ticker``,
  and ``meta``.

Rule Zero
---------
This module reads a static YAML file. It does not infer, fabricate, or fill
in missing fields. ``market_cap_bn`` is a static rough tag (see YAML header
comment) and is never consumed by signal computation — it exists only as
LLM context for the categorizer.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_UNIVERSE_PATH = Path(__file__).resolve().parent / "msr_universe.yaml"


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    kind: str                 # "etf" | "stock"
    sector: str
    industry: str
    market_cap_bn: Optional[float]


@dataclass(frozen=True)
class Universe:
    etfs: tuple[UniverseEntry, ...]
    stocks: tuple[UniverseEntry, ...]
    by_ticker: dict[str, UniverseEntry]
    meta: dict

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(self.by_ticker.keys())

    def __len__(self) -> int:
        return len(self.by_ticker)


def _parse_entry(item: dict, where: str) -> UniverseEntry:
    if not isinstance(item, dict):
        raise ValueError(f"{where}: entry is not a mapping")
    ticker = item.get("ticker")
    if not ticker or not isinstance(ticker, str):
        raise ValueError(f"{where}: missing/invalid 'ticker'")
    kind = item.get("kind")
    if kind not in ("etf", "stock"):
        raise ValueError(f"{where} ({ticker}): kind must be 'etf' or 'stock'")
    sector = str(item.get("sector") or "")
    industry = str(item.get("industry") or "")
    mc = item.get("market_cap_bn")
    if mc is not None:
        mc = float(mc)
    return UniverseEntry(
        ticker=ticker.upper(),
        kind=kind,
        sector=sector,
        industry=industry,
        market_cap_bn=mc,
    )


@lru_cache(maxsize=4)
def load_universe(path: str | Path | None = None) -> Universe:
    """Parse the universe YAML (cached by absolute path)."""
    p = Path(path) if path else DEFAULT_UNIVERSE_PATH
    p = p.resolve()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"universe YAML at {p} did not parse to a dict")

    etfs_raw = raw.get("etfs") or []
    stocks_raw = raw.get("stocks") or []
    if not etfs_raw and not stocks_raw:
        raise ValueError(f"universe YAML at {p} has no etfs or stocks")

    etfs = tuple(_parse_entry(e, f"etfs[{i}]") for i, e in enumerate(etfs_raw))
    stocks = tuple(_parse_entry(e, f"stocks[{i}]") for i, e in enumerate(stocks_raw))

    by_ticker: dict[str, UniverseEntry] = {}
    for entry in (*etfs, *stocks):
        if entry.ticker in by_ticker:
            raise ValueError(f"duplicate ticker in universe: {entry.ticker}")
        by_ticker[entry.ticker] = entry

    meta = raw.get("meta") or {}
    if not isinstance(meta, dict):
        raise ValueError(f"universe YAML at {p} has non-mapping 'meta'")

    return Universe(etfs=etfs, stocks=stocks, by_ticker=by_ticker, meta=meta)


__all__ = [
    "DEFAULT_UNIVERSE_PATH",
    "Universe",
    "UniverseEntry",
    "load_universe",
]
