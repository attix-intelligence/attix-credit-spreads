"""Thin client for TradeAlgo's Daily Snapshot endpoint.

Endpoint:  ``https://presentation.tradealgo.com/reports/snapshot``
Auth:      headers ``x-api-key`` + ``x-auth-provider: apikey``

Two HTTP verbs are supported by the upstream service:

* ``GET`` returns the **current bundle** as a single JSON object whose keys
  are paths like ``"movement/darkflow-large.json"`` and values are the
  parsed JSON content of that module. Despite the API doc claiming a
  ``application/zip`` stream, the prod endpoint returns flat JSON
  (``content-type: application/json``). This client codes against the
  observed wire format.
* ``POST`` returns a small ack object — ``{"status":"ok","files":N,
  "sizeBytes":N}`` — and appears to trigger regeneration. Exposed here
  as :meth:`TradeAlgoClient.trigger_refresh`.

Local cache layout::

    data/tradealgo/
        2026-05-27/snapshot.json    (the full GET response, ~3 MB)
        2026-05-28/snapshot.json

The snapshot date is taken from the bundle's own ``live-options/snapshot.json``
or ``movement/darkflow-*`` ``options.date`` field when present, falling back
to today's UTC date otherwise.

Failure semantics: raise :class:`shared.exceptions.DataFetchError` after
:data:`_MAX_RETRIES` retries on 429 / 5xx / transport errors. The trading
path must fail closed — callers should treat absence of a snapshot the same
as absence of the dark-flow signal (fail-closed; never fabricate values).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from shared.exceptions import DataFetchError

logger = logging.getLogger(__name__)

_ENDPOINT = "https://presentation.tradealgo.com/reports/snapshot"
_REQUEST_TIMEOUT = 60  # GET payload is ~3 MB; allow time
_MAX_RETRIES = 3
_BACKOFF_SECONDS = (1, 2, 4)
_DEFAULT_USER_AGENT = "Mozilla/5.0 (Attix Credit Spreads / TradeAlgo client)"
_DEFAULT_CACHE_DIR = Path("data/tradealgo")


class TradeAlgoClient:
    """REST client for the Daily Snapshot endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.getenv("TRADEALGO_API_KEY", "")
        if not self._api_key:
            logger.warning(
                "TRADEALGO_API_KEY not set; live fetch will raise. "
                "Use from_cache() for offline reads.",
            )
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._user_agent = user_agent or _DEFAULT_USER_AGENT
        self._session = requests.Session()

    # ---- HTTP -------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "x-auth-provider": "apikey",
            "user-agent": self._user_agent,
        }

    def _request(self, method: str) -> requests.Response:
        if not self._api_key:
            raise DataFetchError("TRADEALGO_API_KEY is not configured")

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._session.request(
                    method=method,
                    url=_ENDPOINT,
                    headers=self._headers(),
                    timeout=_REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    logger.warning(
                        "TradeAlgo %s %s (attempt %d/%d) — retrying",
                        method, resp.status_code, attempt + 1, _MAX_RETRIES,
                    )
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(_BACKOFF_SECONDS[attempt])
                        continue
                raise DataFetchError(
                    f"TradeAlgo HTTP {resp.status_code} on {method}: "
                    f"{resp.text[:200]}"
                )
            except requests.RequestException as e:
                last_exc = e
                logger.warning(
                    "TradeAlgo transport error (attempt %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, e,
                )
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_SECONDS[attempt])
                    continue
                raise DataFetchError(
                    f"TradeAlgo request failed after {_MAX_RETRIES} attempts: {e}"
                ) from e

        raise DataFetchError(
            f"TradeAlgo request failed after {_MAX_RETRIES} attempts: {last_exc}"
        )

    # ---- Public API -------------------------------------------------------

    def fetch_snapshot(
        self,
        *,
        force_refresh: bool = False,
        write_cache: bool = True,
    ) -> Dict[str, Any]:
        """Fetch the current bundle as a parsed JSON dict.

        If ``force_refresh`` is False (the default) and today's snapshot is
        already cached on disk, the cached copy is returned without making
        a network call. Set ``force_refresh=True`` for an explicit refresh.

        On a successful network fetch, writes the raw JSON to
        ``{cache_dir}/{snapshot_date}/snapshot.json`` when
        ``write_cache=True``.

        Returns the parsed dict ``{"<path>.json": <parsed_content>, ...}``.
        Raises :class:`DataFetchError` on permanent failure.
        """
        if not force_refresh:
            today_cached = self._cache_path(_today_utc())
            if today_cached.exists():
                logger.info("TradeAlgo: using cached snapshot %s", today_cached)
                return _read_json(today_cached)

        resp = self._request("GET")
        try:
            data = resp.json()
        except ValueError as e:
            raise DataFetchError(
                f"TradeAlgo response was not JSON (got {resp.headers.get('content-type')})"
            ) from e

        if not isinstance(data, dict):
            raise DataFetchError(
                f"TradeAlgo response had unexpected top-level type "
                f"{type(data).__name__} (expected dict)"
            )

        snap_date = _infer_snapshot_date(data) or _today_utc()
        if write_cache:
            self._write_cache(snap_date, data)
        return data

    def trigger_refresh(self) -> Dict[str, Any]:
        """POST the endpoint to ask upstream to regenerate the bundle.

        Returns the ack dict (e.g. ``{"status":"ok","files":31,"sizeBytes":...}``).
        Does NOT return the snapshot data — call :meth:`fetch_snapshot`
        afterwards. Raises :class:`DataFetchError` on permanent failure.
        """
        resp = self._request("POST")
        try:
            return resp.json()
        except ValueError as e:
            raise DataFetchError(
                f"TradeAlgo POST response was not JSON: {resp.text[:200]}"
            ) from e

    @classmethod
    def from_cache(
        cls,
        snapshot_date: date | str,
        cache_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Read a cached snapshot from disk without any network call.

        ``snapshot_date`` may be a ``date`` or ISO ``YYYY-MM-DD`` string.
        Raises :class:`FileNotFoundError` if the cache file is missing.
        """
        cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        if isinstance(snapshot_date, str):
            snapshot_date = date.fromisoformat(snapshot_date)
        path = cache_dir / snapshot_date.isoformat() / "snapshot.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No TradeAlgo snapshot cached at {path}"
            )
        return _read_json(path)

    # ---- Cache ------------------------------------------------------------

    def _cache_path(self, snapshot_date: date) -> Path:
        return self._cache_dir / snapshot_date.isoformat() / "snapshot.json"

    def _write_cache(self, snapshot_date: date, data: Dict[str, Any]) -> None:
        path = self._cache_path(snapshot_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically: tmp + rename, so a partial write never poisons cache.
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(path)
        logger.info("TradeAlgo: wrote snapshot %s (%d bytes)", path, path.stat().st_size)


# ----- helpers ------------------------------------------------------------

def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _infer_snapshot_date(data: Dict[str, Any]) -> Optional[date]:
    """Try to read the bundle's intrinsic snapshot date.

    Looks at ``live-options/snapshot.json`` (preferred — single object with
    a ``date`` field) and falls back to ``movement/darkflow-large.json``'s
    ``options.date`` on the first ticker. Returns ``None`` if neither path
    yields a parseable date.
    """
    snap = data.get("live-options/snapshot.json")
    if isinstance(snap, dict):
        ds = snap.get("date")
        d = _parse_iso_date(ds)
        if d is not None:
            return d

    movement = data.get("movement/darkflow-large.json")
    if isinstance(movement, dict):
        up = movement.get("trending_up") or []
        if up:
            ds = (up[0].get("options") or {}).get("date")
            d = _parse_iso_date(ds)
            if d is not None:
                return d

    return None


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        # Accept either "YYYY-MM-DD" or full ISO with time/zone.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
