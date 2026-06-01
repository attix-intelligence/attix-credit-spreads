"""
executor_live.py — Live IBKR-via-executor data for the dashboard.

A sibling to ``alpaca_live`` for experiments that route to the standalone
``attix-intelligence/executor`` service (IBKR paper today; live IBKR later).
The card on the dashboard expects the same dict shape under ``r["alpaca"]``
regardless of broker, so this module fetches from the executor's REST API
and re-shapes the response into that shape.

Reads per-experiment credentials from env vars:

    EXECUTOR_API_KEY_<SUFFIX>      — user API key registered via /auth/register
    EXECUTOR_BASE_URL_<SUFFIX>     — e.g. https://executor-production-1f58.up.railway.app
    EXECUTOR_ACCOUNT_ID_<SUFFIX>   — e.g. ibkr_tafintech-p11-paper

Suffix mirrors how attix-worker discovers per-experiment routing vars
(``railway_worker.py`` translates ``EXECUTOR_*_EXPV8AIBKR`` → ``EXECUTOR_*``
for the EXP-V8A-IBKR subprocess); the dashboard reads the same names so a
single Railway env-var change drives both processes.

Fetches:
    GET /v1/portfolio/balance?account_id=...
    GET /v1/portfolio/positions?account_id=...

Cached 60 s to match alpaca_live and avoid per-render round-trips. Graceful
degradation: any error returns ``{"error": "..."}``-style dict so callers
fall back to pushed-data / local-DB the same way.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import httpx

from .env_helpers import getenv_or_default

logger = logging.getLogger(__name__)

CACHE_TTL = 60.0  # seconds, matches alpaca_live

# {normalized_id: (timestamp, data_dict)}
_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# Key discovery
# ---------------------------------------------------------------------------

def discover_experiment_keys() -> dict[str, tuple[str, str, str]]:
    """
    Scan environment for ``EXECUTOR_API_KEY_EXP*`` triples.

    Returns ``{normalized_id: (api_key, base_url, account_id)}``.
    A triple is included only when ALL THREE of API_KEY / BASE_URL / ACCOUNT_ID
    are present and non-blank — a missing or empty value at any position would
    silently disable live data for that experiment, so we log a warning
    instead and skip the row.
    """
    keys: dict[str, tuple[str, str, str]] = {}
    for var, val in os.environ.items():
        # `not val` filters the empty-string footgun — a present-but-blank
        # ``EXECUTOR_API_KEY_*`` must not register as configured.
        if not var.startswith("EXECUTOR_API_KEY_EXP") or not (val and val.strip()):
            continue
        suffix = var[len("EXECUTOR_API_KEY_"):]   # e.g. "EXPV8AIBKR"
        base_url = getenv_or_default(f"EXECUTOR_BASE_URL_{suffix}", "")
        account_id = getenv_or_default(f"EXECUTOR_ACCOUNT_ID_{suffix}", "")
        if base_url and account_id:
            keys[suffix] = (val, base_url, account_id)
        else:
            missing = [
                name for name, v in (
                    (f"EXECUTOR_BASE_URL_{suffix}", base_url),
                    (f"EXECUTOR_ACCOUNT_ID_{suffix}", account_id),
                ) if not v
            ]
            logger.warning(
                "[executor_live] %s has an API key but %s missing/empty — "
                "skipping (no live executor data for this experiment)",
                suffix, " + ".join(missing),
            )
    return keys


def _normalize(exp_id: str) -> str:
    """``EXP-V8A-IBKR`` → ``EXPV8AIBKR``"""
    return exp_id.upper().replace("-", "")


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(base_url: str, api_key: str, path: str, params: dict | None = None):
    """Single executor REST GET. Raises httpx.HTTPStatusError on bad status."""
    resp = httpx.get(
        f"{base_url.rstrip('/')}{path}",
        headers={"X-API-Key": api_key},
        params=params or {},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Shape adapter
# ---------------------------------------------------------------------------

def _adapt_position(p: dict) -> dict:
    """
    Adapt an executor /v1/portfolio/positions entry into the Alpaca-shaped dict
    that ``html.py`` renders. Fields the renderer reads (per alpaca_live):

        symbol, qty, side, market_value, unrealized_pl, opened_at,
        avg_entry_price, current_price

    Executor → Alpaca mapping (the Alpaca names are kept for the renderer):

        quantity          → qty (str — Alpaca returns string, renderer parses)
        sign(quantity)    → side ("long" / "short")
        market_value      → market_value
        unrealized_pnl    → unrealized_pl
        average_cost      → avg_entry_price
        current_price     → current_price
        — no opening-fill timestamp available from the executor read APIs;
          set to None so the renderer can fall back to "—".

    Option-leg fields (``option_type``, ``strike``, ``expiration``) are passed
    through unchanged for option positions; the renderer ignores them on stock
    rows.
    """
    qty_int = int(p.get("quantity") or 0)
    out = {
        "symbol":           p.get("symbol"),
        "qty":              str(qty_int),
        "side":             "long" if qty_int >= 0 else "short",
        "market_value":     str(p.get("market_value") or 0),
        "unrealized_pl":    str(p.get("unrealized_pnl") or 0),
        "avg_entry_price":  str(p.get("average_cost") or 0),
        "current_price":    str(p.get("current_price") or 0),
        "opened_at":        None,
    }
    # Pass option-leg fields straight through for option positions.
    for k in ("option_type", "strike", "expiration", "security_type"):
        if p.get(k) is not None:
            out[k] = p[k]
    return out


# ---------------------------------------------------------------------------
# Per-experiment fetch
# ---------------------------------------------------------------------------

def fetch_live_data(
    normalized_id: str,
    api_key: str,
    base_url: str,
    account_id: str,
) -> dict:
    """
    Fetch executor balance + positions for one experiment and shape the result
    to match the dict alpaca_live returns, so the renderer needs no branching.

    The dict the renderer expects under ``s["alpaca"]``:
      equity, buying_power, cash, unrealized_pl, day_pl,
      positions (list of Alpaca-shaped dicts), orders (list),
      error, fetched_at
    """
    result: dict = {
        "equity":        None,
        "buying_power":  None,
        "cash":          None,
        "unrealized_pl": None,
        "day_pl":        None,
        "positions":     [],
        "orders":        [],
        "error":         None,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
        # Provenance hint for debugging; not rendered.
        "broker":        "ibkr_executor",
    }

    # --- Balance (required; abort on failure) --------------------------------
    try:
        bal = _get(
            base_url, api_key, "/v1/portfolio/balance",
            params={"account_id": account_id},
        )
        result["equity"]        = float(bal.get("total_equity")       or 0)
        result["cash"]          = float(bal.get("cash")               or 0)
        result["buying_power"]  = float(bal.get("buying_power")       or 0)
        result["unrealized_pl"] = float(bal.get("unrealized_pnl")     or 0)
        # Closest available proxy for Alpaca's day_pl. Executor's
        # ``realized_pnl_today`` covers closed legs only — pair it with the
        # change in unrealized to get an analogue. When the executor exposes a
        # true day-PL field we'll swap this out.
        result["day_pl"]        = float(bal.get("realized_pnl_today") or 0)
    except Exception as exc:
        result["error"] = f"balance: {exc}"
        logger.warning("[executor_live] %s balance error: %s", normalized_id, exc)
        return result

    # --- Positions (non-fatal) -----------------------------------------------
    try:
        raw = _get(
            base_url, api_key, "/v1/portfolio/positions",
            params={"account_id": account_id},
        )
        positions = raw if isinstance(raw, list) else []
        result["positions"] = [_adapt_position(p) for p in positions if isinstance(p, dict)]
        # Executor balance includes positions_count; the renderer uses
        # ``len(positions)`` so we don't need to expose it separately.
    except Exception as exc:
        logger.warning("[executor_live] %s positions error: %s", normalized_id, exc)

    return result


# ---------------------------------------------------------------------------
# Public API — with caching
# ---------------------------------------------------------------------------

def get_live_executor(exp_id: str) -> Optional[dict]:
    """
    Live executor data for one experiment (60 s cache). ``exp_id`` may be
    ``"EXP-V8A-IBKR"`` or ``"EXPV8AIBKR"``. Returns ``None`` when no creds
    configured for this experiment.
    """
    norm = _normalize(exp_id)
    keys = discover_experiment_keys()
    creds = keys.get(norm)
    if not creds:
        return None

    cached = _cache.get(norm)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    api_key, base_url, account_id = creds
    data = fetch_live_data(norm, api_key, base_url, account_id)
    _cache[norm] = (time.time(), data)
    return data


def get_all_live_executor() -> dict[str, dict]:
    """
    Fetch live executor data for ALL configured experiments in parallel.
    Returns ``{normalized_id: data_dict}``. Only experiments with full
    creds (API_KEY + BASE_URL + ACCOUNT_ID) appear.
    """
    all_keys = discover_experiment_keys()
    if not all_keys:
        # Quiet at INFO — most deployments won't have executor-routed experiments.
        logger.info(
            "[executor_live] no EXECUTOR_API_KEY_EXP* env vars found — "
            "no live executor data fetched this cycle"
        )
        return {}

    results: dict[str, dict] = {}
    uncached: dict[str, tuple[str, str, str]] = {}

    for norm, creds in all_keys.items():
        cached = _cache.get(norm)
        if cached and (time.time() - cached[0]) < CACHE_TTL:
            results[norm] = cached[1]
        else:
            uncached[norm] = creds

    if uncached:
        with ThreadPoolExecutor(max_workers=min(len(uncached), 8)) as pool:
            futures = {
                pool.submit(fetch_live_data, norm, api_key, base_url, acct_id): norm
                for norm, (api_key, base_url, acct_id) in uncached.items()
            }
            for future in as_completed(futures):
                norm = futures[future]
                try:
                    data = future.result()
                    _cache[norm] = (time.time(), data)
                    results[norm] = data
                except Exception as exc:
                    # Keep going — one broken experiment shouldn't blank the
                    # whole dashboard row set.
                    logger.warning(
                        "[executor_live] %s fetch raised %s: %s",
                        norm, type(exc).__name__, exc,
                    )
                    results[norm] = {
                        "equity": None, "buying_power": None, "cash": None,
                        "unrealized_pl": None, "day_pl": None,
                        "positions": [], "orders": [],
                        "error": f"fetch: {exc}",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "broker": "ibkr_executor",
                    }
    return results
