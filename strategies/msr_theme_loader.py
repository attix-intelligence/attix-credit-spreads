"""Read the cached LLM theme analysis files into ``ThemeRecord`` rows.

Companion to ``strategies/msr_theme_rotation.py``. This module owns *all*
disk reads for the strategy so the rotation logic stays pure.

Layout consumed (see ``data/llm_analysis/README.md``)::

    data/llm_analysis/{YYYY-MM-DD}.json        — CategoryAnalysis payload
    data/llm_analysis/{YYYY-MM-DD}.meta.json   — prompt_hash / model / generated_at_utc

Rule Zero guard
---------------
``load_themes(asof_date)`` verifies that the cache file was produced no
later than ``asof_date + 1 day`` (UTC). This prevents the backtest from
silently consuming a theme analysis that was regenerated after the trade
date — a subtle look-ahead bug. Violation → :class:`LookaheadError`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from strategies.msr_theme_rotation import ThemeRecord

DEFAULT_CACHE_DIR = Path("data/llm_analysis")
MAX_LAG_DAYS = 1  # cache may be written up to 1 day after the trade date


class CacheMissError(FileNotFoundError):
    """Raised when a date has no cached theme analysis."""


class LookaheadError(ValueError):
    """Raised when a cache file's generated_at_utc is after the allowed lag."""


@dataclass(frozen=True)
class CachedThemeDay:
    """Validated theme cache entry for a single trade date."""
    asof_date: date
    generated_at_utc: datetime
    model: str
    prompt_hash: str
    themes: tuple[ThemeRecord, ...]


def _payload_path(cache_dir: Path, asof_date: date) -> Path:
    return cache_dir / f"{asof_date.isoformat()}.json"


def _meta_path(cache_dir: Path, asof_date: date) -> Path:
    return cache_dir / f"{asof_date.isoformat()}.meta.json"


def _to_theme_record(raw: dict) -> ThemeRecord:
    return ThemeRecord(
        name=str(raw["name"]),
        direction=raw["direction"],
        confidence=float(raw["confidence"]),
        tickers=tuple(str(t).upper() for t in raw["tickers"]),
        supporting_signals=tuple(str(s) for s in raw.get("supporting_signals", ())),
        narrative=str(raw.get("narrative", "")),
    )


def load_themes(
    asof_date: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    *,
    max_lag_days: int = MAX_LAG_DAYS,
) -> CachedThemeDay:
    """Load one trade-date's themes.

    Raises:
        CacheMissError: payload or meta file missing.
        LookaheadError: cache was generated more than ``max_lag_days`` after
            ``asof_date``.
        ValueError: payload fails structural validation.
    """
    payload_p = _payload_path(cache_dir, asof_date)
    meta_p = _meta_path(cache_dir, asof_date)
    if not payload_p.exists():
        raise CacheMissError(f"no theme payload for {asof_date} at {payload_p}")
    if not meta_p.exists():
        raise CacheMissError(f"no theme meta for {asof_date} at {meta_p}")

    payload = json.loads(payload_p.read_text(encoding="utf-8"))
    meta = json.loads(meta_p.read_text(encoding="utf-8"))

    if payload.get("asof_date") != asof_date.isoformat():
        raise ValueError(
            f"payload asof_date={payload.get('asof_date')!r} "
            f"does not match filename {asof_date.isoformat()!r}"
        )

    gen_at_str = payload.get("generated_at_utc") or meta.get("generated_at_utc")
    if not gen_at_str:
        raise ValueError(f"missing generated_at_utc for {asof_date}")
    generated_at_utc = datetime.fromisoformat(gen_at_str)
    if generated_at_utc.tzinfo is None:
        generated_at_utc = generated_at_utc.replace(tzinfo=timezone.utc)

    deadline = datetime.combine(
        asof_date + timedelta(days=max_lag_days),
        datetime.max.time(),
        tzinfo=timezone.utc,
    )
    if generated_at_utc > deadline:
        raise LookaheadError(
            f"theme cache for {asof_date} was generated at "
            f"{generated_at_utc.isoformat()} — more than {max_lag_days} day(s) "
            f"after the trade date (look-ahead)"
        )

    raw_categories = payload.get("categories")
    if not isinstance(raw_categories, list):
        raise ValueError(f"categories missing or wrong type for {asof_date}")
    themes = tuple(_to_theme_record(c) for c in raw_categories)

    return CachedThemeDay(
        asof_date=asof_date,
        generated_at_utc=generated_at_utc,
        model=str(payload.get("model", meta.get("model", ""))),
        prompt_hash=str(payload.get("prompt_hash", meta.get("prompt_hash", ""))),
        themes=themes,
    )


def iter_cached_dates(
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Iterator[date]:
    """Yield every date with a cached payload, in ascending order.

    Skips ``.meta.json`` files and the ``raw/`` subdir. Filenames that do
    not parse as ISO dates are skipped silently — callers that need
    strict validation should inspect the returned set.
    """
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        stem = path.stem
        try:
            yield date.fromisoformat(stem)
        except ValueError:
            continue


def load_themes_safe(
    asof_date: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Optional[CachedThemeDay]:
    """Like :func:`load_themes` but returns ``None`` on cache miss.

    Look-ahead and parse errors still raise — they are correctness bugs.
    """
    try:
        return load_themes(asof_date, cache_dir)
    except CacheMissError:
        return None


__all__ = [
    "DEFAULT_CACHE_DIR",
    "MAX_LAG_DAYS",
    "CacheMissError",
    "LookaheadError",
    "CachedThemeDay",
    "load_themes",
    "load_themes_safe",
    "iter_cached_dates",
]
