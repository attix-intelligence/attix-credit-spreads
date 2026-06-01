"""compass/live/vrp_risk_caps.py — VRP-native capital-protection risk caps.

Why this exists
---------------
The ``risk:`` block in ``configs/paper_expv8a.yaml`` / ``..._ibkr.yaml``
(``max_positions``, ``profit_target``, ``stop_loss_multiplier``,
``max_same_expiration`` etc.) is wired to the **champion** credit-spread strategy
— ``main.py`` reads it; the VRP engine in ``compass/live`` does not. With the
champion path retired for V8A, those caps were dead config and the VRP engine
had no portfolio-level brakes.

This module adds VRP-native equivalents (plus a new aggregate-max-loss cap), read
from a fresh ``vrp_risk:`` YAML block — separate namespace so VRP and any future
champion-style experiment can live side-by-side without overloaded semantics.

Contract
--------
:func:`apply_caps` runs once per cycle, AFTER the per-stream generators have
emitted :class:`OrderIntent` objects and BEFORE they hit the sink. It folds in
already-open positions (via an injected position source), filters the new
intents in stable arrival order, and returns:

    (kept_intents, dropped)   # dropped: list[dict] for plan.notes / telemetry

A cap of ``None`` (the YAML key absent or null) is treated as "no limit". This
keeps the module additive: an experiment that doesn't define ``vrp_risk:`` runs
exactly as it does today.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from compass.live.vrp_contracts import OrderIntent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExistingPosition:
    """The minimum surface ``apply_caps`` needs about an open position.

    Built from whatever truth source the caller has (the worker DB's open
    ``trades`` rows, or Alpaca's positions endpoint grouped into spreads).
    """

    ticker: str
    expiration: str                  # ``YYYY-MM-DD``
    est_max_loss: Optional[float] = None  # absolute $; None => not counted in aggregate cap


@dataclass(frozen=True)
class VRPRiskCaps:
    """Portfolio-level limits for the VRP engine.

    Attributes mirror the champion ``risk:`` keys the operator is used to, with
    one VRP-specific addition (``max_aggregate_max_loss_pct``):

    - ``max_positions_per_ticker``: hard cap on concurrent open positions for
      any one ticker (existing + this cycle's intents). Counted PER SPREAD
      (one ``OrderIntent`` / one open trade row = one position).
    - ``max_same_expiration``: hard cap on concurrent open positions sharing a
      single expiration date (across all tickers). Mitigates expiry clustering.
    - ``max_aggregate_max_loss_pct``: hard cap on the sum of estimated max
      losses across existing + this cycle's intents, as a fraction of account
      equity. THE capital-protection brake. ``0.30`` = "never risk more than
      30% of equity at once".
    """

    max_positions_per_ticker: Optional[int] = None
    max_same_expiration: Optional[int] = None
    max_aggregate_max_loss_pct: Optional[float] = None

    @classmethod
    def from_config(cls, vrp_risk_block: Optional[Mapping]) -> "VRPRiskCaps":
        """Build from a YAML ``vrp_risk:`` mapping. Missing keys → ``None`` (no cap).

        Validates that numeric caps are non-negative and finite; rejects with a
        ``ValueError`` so a config typo cannot silently disarm the brakes.
        """
        if not vrp_risk_block:
            return cls()
        block = dict(vrp_risk_block)

        def _int_or_none(key: str) -> Optional[int]:
            v = block.get(key)
            if v is None:
                return None
            iv = int(v)
            if iv < 0:
                raise ValueError(f"vrp_risk.{key} must be >= 0, got {v}")
            return iv

        def _pct_or_none(key: str) -> Optional[float]:
            v = block.get(key)
            if v is None:
                return None
            fv = float(v)
            if not (0.0 <= fv <= 1.0):
                raise ValueError(f"vrp_risk.{key} must be in [0,1] (fraction of equity), got {v}")
            return fv

        return cls(
            max_positions_per_ticker=_int_or_none("max_positions_per_ticker"),
            max_same_expiration=_int_or_none("max_same_expiration"),
            max_aggregate_max_loss_pct=_pct_or_none("max_aggregate_max_loss_pct"),
        )

    def is_inert(self) -> bool:
        """True iff every cap is ``None`` (the block is effectively absent)."""
        return all(
            v is None for v in (
                self.max_positions_per_ticker,
                self.max_same_expiration,
                self.max_aggregate_max_loss_pct,
            )
        )


def _intent_ticker(intent: OrderIntent) -> str:
    """Best-effort ticker for an intent. Falls back to the first leg's symbol
    head if ``symbol`` is missing — defensive, never raises."""
    if getattr(intent, "symbol", None):
        return str(intent.symbol)
    legs = getattr(intent, "legs", ()) or ()
    if legs:
        first = legs[0].symbol or ""
        # OCC option symbols start with the underlying ticker letters.
        head = "".join(c for c in first[:6] if c.isalpha())
        return head or first
    return ""


def _intent_expiration(intent: OrderIntent) -> str:
    """Best-effort YYYY-MM-DD expiration from the first option leg, else empty."""
    for leg in getattr(intent, "legs", ()) or ():
        if getattr(leg, "expiration", None):
            return str(leg.expiration)
    return ""


def apply_caps(
    intents: Sequence[OrderIntent],
    existing_positions: Iterable[ExistingPosition],
    equity: float,
    caps: VRPRiskCaps,
) -> Tuple[List[OrderIntent], List[dict]]:
    """Filter ``intents`` so no cap in ``caps`` is breached.

    Counts existing positions and intents together, ticker-by-ticker / expiry-by-
    expiry, and accumulates aggregate max loss. Drops intents in stable arrival
    order — i.e. the first N that fit are kept, later ones that would breach are
    dropped with a reason. Caps set to ``None`` are skipped.

    Returns ``(kept, dropped)`` where ``dropped`` is ``[{"stream", "symbol",
    "reason"}]`` — wire it into ``CyclePlan.notes`` for telemetry.

    Defensive on bad inputs: if ``equity`` is non-positive and an aggregate-pct
    cap is set, ALL intents are dropped (no equity → no risk budget). Intents
    with no ``est_max_loss`` contribute 0 to the aggregate (logged at DEBUG).
    """
    intents = list(intents)
    if not intents:
        return [], []
    if caps.is_inert():
        return intents, []

    # ── Seed counters from already-open positions ─────────────────────────────
    per_ticker: dict[str, int] = {}
    per_expiry: dict[str, int] = {}
    aggregate_max_loss = 0.0
    for pos in existing_positions or ():
        tkr = (pos.ticker or "").strip()
        exp = (pos.expiration or "").strip()
        if tkr:
            per_ticker[tkr] = per_ticker.get(tkr, 0) + 1
        if exp:
            per_expiry[exp] = per_expiry.get(exp, 0) + 1
        if pos.est_max_loss is not None:
            try:
                aggregate_max_loss += float(pos.est_max_loss)
            except (TypeError, ValueError):
                pass

    # Aggregate budget. equity ≤ 0 + a pct cap set → drop everything.
    agg_budget: Optional[float] = None
    if caps.max_aggregate_max_loss_pct is not None:
        if equity is None or equity <= 0:
            dropped = [
                {"stream": i.stream, "symbol": i.symbol,
                 "reason": "vrp_risk: equity<=0 with max_aggregate_max_loss_pct set"}
                for i in intents
            ]
            return [], dropped
        agg_budget = float(equity) * float(caps.max_aggregate_max_loss_pct)

    kept: List[OrderIntent] = []
    dropped: List[dict] = []
    for intent in intents:
        tkr = _intent_ticker(intent)
        exp = _intent_expiration(intent)
        ml = float(intent.est_max_loss) if intent.est_max_loss is not None else 0.0

        # max_positions_per_ticker
        if caps.max_positions_per_ticker is not None and tkr:
            if per_ticker.get(tkr, 0) + 1 > caps.max_positions_per_ticker:
                dropped.append({
                    "stream": intent.stream, "symbol": intent.symbol,
                    "reason": f"vrp_risk: max_positions_per_ticker={caps.max_positions_per_ticker} reached for {tkr}",
                })
                continue

        # max_same_expiration
        if caps.max_same_expiration is not None and exp:
            if per_expiry.get(exp, 0) + 1 > caps.max_same_expiration:
                dropped.append({
                    "stream": intent.stream, "symbol": intent.symbol,
                    "reason": f"vrp_risk: max_same_expiration={caps.max_same_expiration} reached for {exp}",
                })
                continue

        # max_aggregate_max_loss_pct
        if agg_budget is not None and aggregate_max_loss + ml > agg_budget:
            dropped.append({
                "stream": intent.stream, "symbol": intent.symbol,
                "reason": (
                    f"vrp_risk: max_aggregate_max_loss_pct={caps.max_aggregate_max_loss_pct:.2%} "
                    f"would breach (running ${aggregate_max_loss:.0f} + new ${ml:.0f} > "
                    f"budget ${agg_budget:.0f})"
                ),
            })
            continue

        # Accept — update running counters.
        kept.append(intent)
        if tkr:
            per_ticker[tkr] = per_ticker.get(tkr, 0) + 1
        if exp:
            per_expiry[exp] = per_expiry.get(exp, 0) + 1
        aggregate_max_loss += ml

    if dropped:
        logger.info("[vrp_risk_caps] kept=%d dropped=%d (reasons=%s)",
                    len(kept), len(dropped),
                    ", ".join(sorted({d['reason'].split(' (')[0] for d in dropped})))
    return kept, dropped


# ── Helper: build ExistingPosition list from the worker DB's open trades ──────

def existing_positions_from_db(
    exp_id: str,
    db_path: Optional[str] = None,
) -> List[ExistingPosition]:
    """Best-effort: read open spreads from the ``trades`` table.

    Returns ``[ExistingPosition(ticker, expiration, est_max_loss)]`` for rows
    where ``status='open'``. ``est_max_loss`` is derived from the row's
    ``credit`` + ``contracts`` (×100 multiplier for options) when both are
    present and a width can be inferred from ``short_strike``/``long_strike``.
    Never raises — returns ``[]`` on any error so the engine never crashes.
    """
    from shared.database import get_db

    out: List[ExistingPosition] = []
    try:
        conn = get_db(db_path) if db_path else get_db()
    except Exception:  # noqa: BLE001
        return out
    try:
        cur = conn.execute(
            """
            SELECT ticker, expiration, credit, contracts, short_strike, long_strike
            FROM trades
            WHERE status = 'open'
              AND (json_extract(metadata, '$.experiment_id') = ?
                   OR json_extract(metadata, '$.exp_id')     = ?
                   OR ? = '')
            """,
            (exp_id or "", exp_id or "", exp_id or ""),
        )
        rows = cur.fetchall()
    except Exception:  # noqa: BLE001 — schema drift, missing table, etc.
        try:
            conn.close()
        except Exception:
            pass
        return out
    conn.close()

    for r in rows:
        ticker = (r["ticker"] or "").strip() if "ticker" in r.keys() else ""
        expiration = (r["expiration"] or "").strip() if "expiration" in r.keys() else ""
        est_max_loss: Optional[float] = None
        try:
            credit = float(r["credit"]) if r["credit"] is not None else None
            contracts = int(r["contracts"]) if r["contracts"] is not None else None
            short_k = float(r["short_strike"]) if r["short_strike"] is not None else None
            long_k = float(r["long_strike"]) if r["long_strike"] is not None else None
            if credit is not None and contracts and short_k is not None and long_k is not None:
                width = abs(short_k - long_k)
                est_max_loss = max(0.0, (width - credit) * contracts * 100.0)
        except (TypeError, ValueError):
            est_max_loss = None
        if ticker or expiration:
            out.append(ExistingPosition(ticker=ticker, expiration=expiration, est_max_loss=est_max_loss))
    return out
