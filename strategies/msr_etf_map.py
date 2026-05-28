"""Resolve LLM theme name → tradeable vehicle (ETF or stock basket).

Driven by ``strategies/msr_etf_map.yaml``. The matching rule is::

    for entry in vehicles (in YAML order):
        if any of entry.match_any (case-insensitive substring) hits the
        theme name: return entry.vehicle (or entry.secondary if the
        liquidity check on primary fails — handled at fill time).

When no entry matches, ``resolve_vehicle`` returns a fallback basket of
the theme's first N tickers (default 3, from the YAML ``fallback``
section). Themes with fewer than ``min_tickers_required`` tickers and no
map hit return ``None``.

Public surface
--------------
* :func:`load_map(path=None)` — parse the YAML (cached by path).
* :func:`resolve_vehicle(theme_name, theme_tickers, mapping)` →
  :class:`VehicleResolution` | None
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Sequence

import yaml

DEFAULT_MAP_PATH = Path(__file__).resolve().parent / "msr_etf_map.yaml"


@dataclass(frozen=True)
class VehicleResolution:
    """Result of mapping a theme to a tradeable vehicle.

    Either ``primary`` is set (ETF / stock from the YAML) or
    ``basket`` is non-empty (fallback). Exactly one of those two is
    populated; callers branch on ``is_basket``.
    """
    theme_id: Optional[str]      # YAML theme_id, or None for basket
    primary: Optional[str]
    secondary: Optional[str]
    basket: tuple[str, ...]
    is_basket: bool

    @property
    def primary_ticker(self) -> str:
        """Convenience: the first ticker to attempt for execution."""
        if self.primary:
            return self.primary
        return self.basket[0] if self.basket else ""


@dataclass(frozen=True)
class _Entry:
    theme_id: str
    patterns: tuple[re.Pattern, ...]
    vehicle: str
    secondary: Optional[str]


@dataclass(frozen=True)
class ThemeMap:
    entries: tuple[_Entry, ...]
    basket_top_n: int
    min_tickers_required: int


def _compile_patterns(match_any: Sequence[str]) -> tuple[re.Pattern, ...]:
    out: list[re.Pattern] = []
    for needle in match_any:
        # word-boundary on substring match — case insensitive
        out.append(re.compile(re.escape(needle), re.IGNORECASE))
    return tuple(out)


@lru_cache(maxsize=8)
def load_map(path: str | Path | None = None) -> ThemeMap:
    """Parse the YAML map file (cached by absolute path)."""
    p = Path(path) if path else DEFAULT_MAP_PATH
    p = p.resolve()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"map YAML at {p} did not parse to a dict")

    entries: list[_Entry] = []
    for i, item in enumerate(raw.get("vehicles") or []):
        if not isinstance(item, dict):
            raise ValueError(f"vehicles[{i}] is not a mapping in {p}")
        theme_id = str(item.get("theme_id") or f"unnamed_{i}")
        match_any = item.get("match_any") or []
        # Future: also support match_regex; not used yet.
        if not isinstance(match_any, list) or not match_any:
            raise ValueError(f"vehicles[{i}] '{theme_id}' has empty match_any in {p}")
        vehicle = item.get("vehicle")
        if not vehicle:
            raise ValueError(f"vehicles[{i}] '{theme_id}' missing vehicle in {p}")
        secondary = item.get("secondary")
        entries.append(_Entry(
            theme_id=theme_id,
            patterns=_compile_patterns(match_any),
            vehicle=str(vehicle).upper(),
            secondary=str(secondary).upper() if secondary else None,
        ))

    fb = raw.get("fallback") or {}
    return ThemeMap(
        entries=tuple(entries),
        basket_top_n=int(fb.get("basket_top_n", 3)),
        min_tickers_required=int(fb.get("min_tickers_required", 2)),
    )


def resolve_vehicle(
    theme_name: str,
    theme_tickers: Iterable[str],
    mapping: Optional[ThemeMap] = None,
) -> Optional[VehicleResolution]:
    """Resolve one theme to a vehicle.

    Returns ``None`` if no pattern matched AND the fallback basket has
    fewer than ``min_tickers_required`` valid tickers.
    """
    if mapping is None:
        mapping = load_map()

    for entry in mapping.entries:
        for pat in entry.patterns:
            if pat.search(theme_name):
                return VehicleResolution(
                    theme_id=entry.theme_id,
                    primary=entry.vehicle,
                    secondary=entry.secondary,
                    basket=(),
                    is_basket=False,
                )

    # Fallback basket
    tickers = tuple(t.upper() for t in theme_tickers if t)
    if len(tickers) < mapping.min_tickers_required:
        return None
    basket = tickers[: mapping.basket_top_n]
    return VehicleResolution(
        theme_id=None,
        primary=None,
        secondary=None,
        basket=basket,
        is_basket=True,
    )


__all__ = [
    "DEFAULT_MAP_PATH",
    "ThemeMap",
    "VehicleResolution",
    "load_map",
    "resolve_vehicle",
]
