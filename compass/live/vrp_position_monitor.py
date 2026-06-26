"""compass/live/vrp_position_monitor.py — VRP-aware exit monitor (build-plan PR-H).

The champion-style ``execution.position_monitor.PositionMonitor`` reads from the
``trades``/``trade_legs`` DB. VRP places spreads via :mod:`compass.live.vrp_sinks`
which does not write to that DB, so the legacy monitor either misses VRP exits
entirely (its current state — ``risk.auto_close_orphan_longs: false`` on V8A) or
mis-attributes VRP legs as orphan longs (the bug that disabled it; see PR #84
and the V8A safety note in ``configs/paper_expv8a.yaml``).

PR-H closes that gap with a **VRP-only** monitor that knows it's looking at
credit spreads it placed, evaluates four exit triggers per cycle, and issues
matching close orders through the same sink that opened them. State is held in
a per-experiment JSON registry so we can tell *our* positions apart from any
other strategy sharing the same broker account.

Four triggers, evaluated in priority order:

  1. **Crisis (VIX > ``crisis_vix``)** — close every open VRP spread immediately.
     Crisis wins over every other condition.
  2. **DTE roll (DTE ≤ ``roll_dte``)** — close at/under the cutoff; the next
     :func:`compass.live.vrp_runner.run_vrp_cycle` will open a new ~30-DTE
     position. PR-H itself does not place the re-open.
  3. **Profit take (``cost_to_close ≤ profit_target_pct × credit``)** — at 50%
     by default, i.e. the spread has decayed by half.
  4. **Stop loss (``cost_to_close ≥ (1 + stop_loss_mult) × credit``)** — at 2×
     by default (loss = 2× initial credit). Math: unrealized PnL/contract =
     credit − cost_to_close; SL fires when PnL = −2× credit → cost_to_close =
     3× credit.

Three pieces glue together:

  * :class:`VRPPositionRegistry` — JSON-backed open-spreads store.
  * :class:`TrackingOrderSink` — wraps the live sink so each successful
    :meth:`OrderSink.submit` records the new spread in the registry.
  * :class:`VRPPositionMonitor` — the exit-decision engine. ``run_cycle()``
    pulls live broker positions, computes per-spread close cost, picks an
    action per spread, and dispatches the close order.

ADDITIVE + INERT BY DEFAULT. Scheduler hook is guarded on
``vrp_position_monitor.enabled``, which is ``false`` in both shipped EXP-V8A
configs. Flipping the flag on is the operational cutover.

Coordination note (PR-H scope): the Executor (IBKR) close path is intentionally
narrow — it raises :class:`ExecutorCloseNotSupportedError` and the monitor logs
+ alerts rather than placing a half-baked close. The IBKR sleeve is already
``dry_run: true`` until the credit-check / cooldown / delta-picker / persistence
PRs land (see ``configs/paper_expv8a_ibkr.yaml`` comment), so this gap blocks
nothing today.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from compass.live.vrp_contracts import OrderIntent
from compass.live.vrp_sinks import stream_client_order_id

logger = logging.getLogger(__name__)


# ── defaults (overridable via vrp_position_monitor.* in experiment config) ────

DEFAULT_PROFIT_TARGET_PCT = 0.50      # close when cost_to_close ≤ 50% of credit
DEFAULT_STOP_LOSS_MULT = 2.0          # close when loss ≥ 2× credit (cost ≥ 3× credit)
DEFAULT_ROLL_DTE = 7                  # close at/under 7 DTE
DEFAULT_CRISIS_VIX = 45.0             # close ALL on VIX strictly greater than this


# Trigger labels — also shown in alerts / dashboards.
TRIGGER_CRISIS = "crisis_vix"
TRIGGER_ROLL = "dte_roll"
TRIGGER_PROFIT = "profit_take"
TRIGGER_STOP = "stop_loss"


class ExecutorCloseNotSupportedError(NotImplementedError):
    """Raised when an Executor-routed VRP spread would need to be closed.

    The Executor sink currently exposes open-only ``submit_spread``; closing
    requires the inverse-side payload that lands in a follow-up PR. The monitor
    catches this, logs an actionable alert, and leaves the spread on the books
    so an operator can act manually.
    """


# ── registry ──────────────────────────────────────────────────────────────────


@dataclass
class OpenSpread:
    """Immutable view of one open VRP spread. Persisted to the registry JSON
    file with ``status`` mutable across the lifecycle ``open → pending_close →
    closed``."""

    spread_id: str               # = stream_client_order_id at open
    stream: str
    symbol: str
    structure: str               # "bull_put" | "bear_call"
    short_strike: float
    long_strike: float
    expiration: str              # "YYYY-MM-DD"
    contracts: int
    credit_per_contract: float   # = est_credit (per-contract; positive number)
    opened_at: str               # ISO-8601 UTC
    order_id: Optional[str] = None
    status: str = "open"         # open | pending_close | closed
    close_reason: Optional[str] = None
    close_order_id: Optional[str] = None
    closed_at: Optional[str] = None


class VRPPositionRegistry:
    """JSON-backed store of open VRP spreads, one file per experiment.

    Lock-free single-writer (the runner). Multiple readers are fine — each
    :meth:`list_open` re-reads from disk so a freshly-recorded entry shows up
    on the next monitor tick.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        # Parent dir is the experiment's data/ — created by init_db elsewhere.
        # Don't create here; let the first write do it so test isolation is
        # explicit (we use tmp_path in tests).

    # ---- factories -----------------------------------------------------------

    @classmethod
    def default_for(cls, config: Dict[str, Any]) -> "VRPPositionRegistry":
        """Pick a registry path from ``vrp_position_monitor.registry_path``, then
        ``$VRP_POSITIONS_PATH``, else derive ``<ATTIX_DB_PATH>.vrp_positions.json``
        from the experiment DB path, else ``data/vrp_positions.json``."""
        cfg = (config.get("vrp_position_monitor") or {}) if config else {}
        explicit = cfg.get("registry_path") or os.environ.get("VRP_POSITIONS_PATH")
        if explicit:
            return cls(str(explicit))
        db_path = os.environ.get("ATTIX_DB_PATH") or config.get("db_path") or ""
        if db_path:
            return cls(f"{db_path}.vrp_positions.json")
        return cls(os.path.join("data", "vrp_positions.json"))

    # ---- I/O -----------------------------------------------------------------

    def _read(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("[vrp_pm] registry %s unreadable (%s) — treating as empty", self.path, exc)
            return {}
        return (blob.get("spreads") or {}) if isinstance(blob, dict) else {}

    def _write(self, spreads: Dict[str, Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # Atomic write: temp file in same dir, then os.replace. Avoids partial
        # writes on crash — readers always see a complete snapshot.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".vrp_positions.", suffix=".json.tmp",
            dir=os.path.dirname(self.path) or ".",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"spreads": spreads, "schema_version": 1}, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ---- mutations -----------------------------------------------------------

    def record_open(self, intent: OrderIntent, *, order_id: Optional[str] = None) -> Optional[OpenSpread]:
        """Record a new open spread. Returns the stored row, or None if the
        intent isn't a 2-leg credit spread we know how to track (the engine only
        emits those today, but be defensive — PR-D's cross_vol won't fit)."""
        if intent.structure not in ("bull_put", "bear_call"):
            logger.debug("[vrp_pm] skip-track non-credit-spread structure=%s", intent.structure)
            return None
        short_strike = _leg_strike(intent, "sell")
        long_strike = _leg_strike(intent, "buy")
        expiration = next((leg_.expiration for leg_ in intent.legs if leg_.expiration), None)
        if short_strike is None or long_strike is None or expiration is None or intent.contracts <= 0:
            logger.warning("[vrp_pm] skip-track intent missing strikes/exp/contracts: %r", intent)
            return None
        if intent.est_credit is None or intent.est_credit <= 0:
            # Without a credit anchor we can't compute PT/SL — refuse to record
            # rather than silently drift to "infinite cost-to-close trigger".
            logger.warning(
                "[vrp_pm] skip-track %s %s — missing est_credit; PT/SL would be undefined",
                intent.stream, intent.symbol,
            )
            return None
        spread_id = stream_client_order_id(intent)
        row = OpenSpread(
            spread_id=spread_id,
            stream=intent.stream,
            symbol=intent.symbol,
            structure=intent.structure,
            short_strike=float(short_strike),
            long_strike=float(long_strike),
            expiration=expiration,
            contracts=int(intent.contracts),
            credit_per_contract=float(intent.est_credit) / int(intent.contracts),
            opened_at=datetime.now(timezone.utc).isoformat(),
            order_id=order_id,
            status="open",
        )
        all_spreads = self._read()
        # Idempotent: re-record (same client_order_id) keeps the original opened_at
        # but refreshes the order_id (Alpaca dedupes; we may see a new attempt).
        if spread_id in all_spreads:
            prior = all_spreads[spread_id]
            prior.update({"order_id": order_id or prior.get("order_id"), "status": "open"})
            all_spreads[spread_id] = prior
        else:
            all_spreads[spread_id] = asdict(row)
        self._write(all_spreads)
        return row

    def mark_pending_close(self, spread_id: str, *, reason: str, close_order_id: Optional[str]) -> None:
        all_spreads = self._read()
        row = all_spreads.get(spread_id)
        if row is None:
            logger.warning("[vrp_pm] mark_pending_close: %s not in registry", spread_id)
            return
        row["status"] = "pending_close"
        row["close_reason"] = reason
        row["close_order_id"] = close_order_id
        all_spreads[spread_id] = row
        self._write(all_spreads)

    def mark_closed(self, spread_id: str, *, reason: Optional[str] = None) -> None:
        all_spreads = self._read()
        row = all_spreads.get(spread_id)
        if row is None:
            return
        row["status"] = "closed"
        if reason and not row.get("close_reason"):
            row["close_reason"] = reason
        row["closed_at"] = datetime.now(timezone.utc).isoformat()
        all_spreads[spread_id] = row
        self._write(all_spreads)

    # ---- reads ---------------------------------------------------------------

    def list_open(self) -> List[OpenSpread]:
        """All rows in status 'open' or 'pending_close'. Pending-close rows are
        returned so the monitor can re-confirm the close filled / re-issue."""
        out: List[OpenSpread] = []
        for raw in self._read().values():
            if raw.get("status") in ("open", "pending_close"):
                # Backfill defaults so older registry files still load.
                out.append(OpenSpread(**{**_DEFAULT_ROW, **raw}))
        return out

    def list_all(self) -> List[OpenSpread]:
        return [OpenSpread(**{**_DEFAULT_ROW, **raw}) for raw in self._read().values()]


_DEFAULT_ROW: Dict[str, Any] = {
    "order_id": None,
    "status": "open",
    "close_reason": None,
    "close_order_id": None,
    "closed_at": None,
}


# ── tracking sink (wraps any OrderSink) ──────────────────────────────────────


class TrackingOrderSink:
    """Decorator around any :class:`~compass.live.vrp_contracts.OrderSink` that
    records each successful :meth:`submit` into a :class:`VRPPositionRegistry`.

    A submit is "successful" when the inner sink returns a dict whose ``status``
    is one of ``submitted`` / ``accepted`` / ``filled`` (and not ``error``). The
    registry update never raises into the caller — a bad disk write logs and
    proceeds; the worst case is the next monitor cycle doesn't see the new row.
    """

    _SUCCESS_STATES = frozenset({"submitted", "accepted", "filled", "partially_filled"})

    def __init__(self, inner, registry: VRPPositionRegistry) -> None:
        self._inner = inner
        self._registry = registry

    def submit(self, intent: OrderIntent) -> Dict[str, object]:
        result = self._inner.submit(intent)
        if not isinstance(result, dict):
            return result
        status = str(result.get("status") or "").lower()
        if status in self._SUCCESS_STATES:
            try:
                self._registry.record_open(intent, order_id=str(result.get("order_id") or "") or None)
            except Exception as exc:  # noqa: BLE001 — never crash the runner over tracking
                logger.error("[vrp_pm] registry record_open failed: %s", exc, exc_info=True)
        return result

    # ---- delegation for helper methods (executor sink exposes these) --------
    def __getattr__(self, name: str) -> Any:  # noqa: D401 — passthrough
        return getattr(self._inner, name)


# ── monitor ───────────────────────────────────────────────────────────────────


@dataclass
class TriggerDecision:
    """One spread's evaluation for this cycle."""

    spread: OpenSpread
    trigger: Optional[str]                       # None = no action
    cost_to_close: Optional[float]               # per-contract, in dollars per share
    dte: Optional[int]
    detail: str = ""


@dataclass
class MonitorReport:
    """Result of one VRP monitor cycle — used by tests + the runner log line."""

    as_of: str
    vix: Optional[float]
    crisis: bool
    decisions: List[TriggerDecision] = field(default_factory=list)
    closes_submitted: List[Dict[str, Any]] = field(default_factory=list)
    skipped_executor: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class VRPPositionMonitor:
    """Evaluate exit triggers for every open VRP spread and dispatch closes.

    Construction is dependency-injected so unit tests pass fakes for everything
    network-shaped. The :func:`run_vrp_monitor_cycle` factory at module level
    handles the production wiring.
    """

    def __init__(
        self,
        registry: VRPPositionRegistry,
        *,
        alpaca_provider=None,
        executor_sink=None,
        vix_source: Optional[Callable[[], Optional[float]]] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT,
        stop_loss_mult: float = DEFAULT_STOP_LOSS_MULT,
        roll_dte: int = DEFAULT_ROLL_DTE,
        crisis_vix: float = DEFAULT_CRISIS_VIX,
    ) -> None:
        if alpaca_provider is None and executor_sink is None:
            raise ValueError("VRPPositionMonitor needs either alpaca_provider or executor_sink")
        self._registry = registry
        self._alpaca = alpaca_provider
        self._executor = executor_sink
        self._vix_source = vix_source
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._pt_pct = float(profit_target_pct)
        self._sl_mult = float(stop_loss_mult)
        self._roll_dte = int(roll_dte)
        self._crisis_vix = float(crisis_vix)

    # ---- the cycle ----------------------------------------------------------

    def run_cycle(self) -> MonitorReport:
        now = self._now()
        report = MonitorReport(as_of=now.isoformat(), vix=None, crisis=False)

        open_spreads = self._registry.list_open()
        if not open_spreads:
            report.notes.append("no_open_spreads")
            logger.info("[vrp_pm] no open VRP spreads — cycle no-op")
            return report

        # VIX gate (one call per cycle). Failure → degraded (no crisis trigger).
        vix = self._fetch_vix()
        report.vix = vix
        report.crisis = vix is not None and vix > self._crisis_vix

        # Snapshot broker positions once per cycle (per leg).
        leg_positions = self._fetch_leg_positions()

        for spread in open_spreads:
            if spread.status == "pending_close":
                # We already issued a close on a prior cycle. Skip re-firing.
                report.decisions.append(TriggerDecision(
                    spread=spread, trigger=None, cost_to_close=None, dte=_dte_days(spread, now),
                    detail="awaiting close fill",
                ))
                continue

            decision = self._evaluate(spread, leg_positions, vix=vix, now=now)
            report.decisions.append(decision)

            if decision.trigger is None:
                continue

            close_result = self._dispatch_close(spread, decision.trigger)
            if close_result is None:
                report.skipped_executor.append(spread.spread_id)
                continue
            report.closes_submitted.append(close_result)

        self._log_summary(report)
        return report

    # ---- evaluation ---------------------------------------------------------

    def _evaluate(
        self,
        spread: OpenSpread,
        leg_positions: Dict[str, Dict[str, Any]],
        *,
        vix: Optional[float],
        now: datetime,
    ) -> TriggerDecision:
        """Pick the first matching trigger for one spread, in priority order:
        crisis → roll → profit → stop. No match → trigger=None."""
        dte = _dte_days(spread, now)

        # Crisis wins over everything — close even if we can't price the spread.
        if vix is not None and vix > self._crisis_vix:
            return TriggerDecision(
                spread=spread, trigger=TRIGGER_CRISIS, cost_to_close=None, dte=dte,
                detail=f"VIX {vix:.2f} > {self._crisis_vix:.2f}",
            )

        # DTE roll next — independent of price; lets us trim near-expiry tail risk.
        if dte is not None and dte <= self._roll_dte:
            return TriggerDecision(
                spread=spread, trigger=TRIGGER_ROLL, cost_to_close=None, dte=dte,
                detail=f"DTE {dte} ≤ {self._roll_dte}",
            )

        # Price-based triggers need both legs marked.
        cost = _compute_cost_to_close(spread, leg_positions)
        if cost is None:
            return TriggerDecision(
                spread=spread, trigger=None, cost_to_close=None, dte=dte,
                detail="legs missing from broker positions",
            )

        credit = spread.credit_per_contract
        if cost <= self._pt_pct * credit:
            return TriggerDecision(
                spread=spread, trigger=TRIGGER_PROFIT, cost_to_close=cost, dte=dte,
                detail=f"cost ${cost:.2f} ≤ {self._pt_pct:.0%} × credit ${credit:.2f}",
            )
        if cost >= (1.0 + self._sl_mult) * credit:
            return TriggerDecision(
                spread=spread, trigger=TRIGGER_STOP, cost_to_close=cost, dte=dte,
                detail=f"cost ${cost:.2f} ≥ (1 + {self._sl_mult:.1f}) × credit ${credit:.2f}",
            )
        return TriggerDecision(
            spread=spread, trigger=None, cost_to_close=cost, dte=dte,
            detail=f"cost ${cost:.2f} within [{self._pt_pct:.0%}, {1 + self._sl_mult:.1f}×] × credit",
        )

    # ---- close dispatch -----------------------------------------------------

    def _dispatch_close(self, spread: OpenSpread, reason: str) -> Optional[Dict[str, Any]]:
        """Send the close order via the broker that opened it. Returns the
        broker response dict on submit, or None when the Executor close path
        is unsupported (in which case we log + alert, but don't crash)."""
        if self._alpaca is not None:
            return self._close_via_alpaca(spread, reason)
        # Executor path — explicit gap (see ExecutorCloseNotSupportedError).
        logger.error(
            "[vrp_pm] EXECUTOR-CLOSE-GAP %s %s (%s): close path not yet wired — "
            "operator action required (close via executor REST manually)",
            spread.spread_id, reason, spread.stream,
        )
        return None

    def _close_via_alpaca(self, spread: OpenSpread, reason: str) -> Optional[Dict[str, Any]]:
        try:
            result = self._alpaca.close_spread(
                ticker=spread.symbol,
                short_strike=spread.short_strike,
                long_strike=spread.long_strike,
                expiration=spread.expiration,
                spread_type=spread.structure,
                contracts=spread.contracts,
                limit_price=None,           # market close — speed > price for SL/crisis
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[vrp_pm] alpaca close_spread raised for %s: %s",
                         spread.spread_id, exc, exc_info=True)
            return {"spread_id": spread.spread_id, "reason": reason, "status": "error", "error": str(exc)}

        status = (result or {}).get("status") if isinstance(result, dict) else None
        close_order_id = (result or {}).get("order_id") if isinstance(result, dict) else None
        if status == "submitted":
            self._registry.mark_pending_close(
                spread.spread_id, reason=reason, close_order_id=close_order_id,
            )
        else:
            logger.warning(
                "[vrp_pm] alpaca close_spread non-success for %s: %r",
                spread.spread_id, result,
            )
        logger.info(
            "[vrp_pm] CLOSE %s spread=%s stream=%s reason=%s result_status=%s",
            spread.structure, spread.spread_id, spread.stream, reason, status,
        )
        return {
            "spread_id": spread.spread_id,
            "stream": spread.stream,
            "reason": reason,
            "status": status,
            "close_order_id": close_order_id,
        }

    # ---- broker reads -------------------------------------------------------

    def _fetch_vix(self) -> Optional[float]:
        if self._vix_source is None:
            return None
        try:
            v = self._vix_source()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vrp_pm] vix source failed: %s", exc)
            return None
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _fetch_leg_positions(self) -> Dict[str, Dict[str, Any]]:
        """Snapshot the broker's option positions keyed by OCC symbol. Returns
        ``{}`` on any error — the per-spread evaluator handles the empty case
        gracefully (it just doesn't fire PT/SL; crisis + roll still work)."""
        if self._alpaca is not None:
            try:
                rows = self._alpaca.get_positions()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[vrp_pm] alpaca.get_positions failed: %s", exc)
                return {}
            return _index_by_occ(rows)
        if self._executor is not None:
            try:
                rows = self._executor.get_positions()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[vrp_pm] executor.get_positions failed: %s", exc)
                return {}
            return _index_by_occ(rows)
        return {}

    # ---- logging ------------------------------------------------------------

    def _log_summary(self, report: MonitorReport) -> None:
        triggers: Dict[str, int] = {}
        for d in report.decisions:
            if d.trigger:
                triggers[d.trigger] = triggers.get(d.trigger, 0) + 1
        trig_str = ",".join(f"{k}={v}" for k, v in sorted(triggers.items())) or "-"
        logger.info(
            "[vrp_pm] cycle open=%d vix=%s crisis=%s triggers=%s closes_submitted=%d "
            "executor_skipped=%d",
            len(report.decisions),
            f"{report.vix:.2f}" if report.vix is not None else "n/a",
            report.crisis, trig_str, len(report.closes_submitted),
            len(report.skipped_executor),
        )


# ── helpers ───────────────────────────────────────────────────────────────────


def _leg_strike(intent: OrderIntent, side: str) -> Optional[float]:
    for leg_ in intent.legs:
        if leg_.side == side and leg_.strike is not None:
            return float(leg_.strike)
    return None


def _dte_days(spread: OpenSpread, now: datetime) -> Optional[int]:
    """Days from ``now`` to the expiration date. Uses the ET trading-day end
    convention is overkill for a 7-day cutoff — calendar days are fine."""
    try:
        exp_dt = datetime.strptime(spread.expiration, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (exp_dt.date() - now.date()).days


def _build_occ_symbol(ticker: str, expiration: str, strike: float, opt_type: str) -> str:
    """OCC symbol: ``TICKER + YYMMDD + C/P + 8-digit strike×1000``.

    Mirror :meth:`strategy.alpaca_provider.AlpacaProvider._build_occ_symbol` so
    the keys we use to look up legs in the broker snapshot match what was placed.
    """
    yymmdd = expiration.replace("-", "")[2:]
    cp = "C" if opt_type.startswith("c") else "P"
    strike_int = int(round(strike * 1000))
    return f"{ticker}{yymmdd}{cp}{strike_int:08d}"


def _index_by_occ(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a broker positions list by OCC symbol, keeping only option rows."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        asset_class = str(r.get("asset_class") or "").lower()
        # Alpaca asset_class is e.g. "us_option"; executor positions don't always
        # set asset_class — fall back to OCC-shape heuristic (length ≥ 16, ends
        # in 8-digit strike).
        looks_option = "option" in asset_class or (len(sym) >= 16 and sym[-8:].isdigit())
        if looks_option:
            out[sym] = r
    return out


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_cost_to_close(
    spread: OpenSpread,
    leg_positions: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    """Cost-to-close per contract (in $ per share, same units as credit).

    For a bull put (short higher-K, long lower-K): cost = short_mark − long_mark.
    For a bear call (short lower-K, long higher-K): same formula — the "short"
    leg is the one that was sold-to-open in either case. We read each leg's
    current mark from the broker's position mark (``current_price`` on Alpaca,
    ``mark_price`` / ``current_price`` on the executor — try both)."""
    opt_type = "put" if spread.structure == "bull_put" else "call"
    short_sym = _build_occ_symbol(spread.symbol, spread.expiration, spread.short_strike, opt_type)
    long_sym = _build_occ_symbol(spread.symbol, spread.expiration, spread.long_strike, opt_type)
    short_pos = leg_positions.get(short_sym)
    long_pos = leg_positions.get(long_sym)
    if short_pos is None or long_pos is None:
        return None
    short_mark = _leg_mark(short_pos)
    long_mark = _leg_mark(long_pos)
    if short_mark is None or long_mark is None:
        return None
    return short_mark - long_mark


def _leg_mark(pos_row: Dict[str, Any]) -> Optional[float]:
    """Pick the per-share mark for one leg. Tries ``current_price`` then
    ``mark_price``, falling back to derive from ``market_value`` and ``qty``."""
    for key in ("current_price", "mark_price", "mark"):
        v = _to_float(pos_row.get(key))
        if v is not None:
            return v
    mv = _to_float(pos_row.get("market_value"))
    qty = _to_float(pos_row.get("qty"))
    if mv is not None and qty is not None and qty != 0:
        # Option contract multiplier is 100; we want per-share = per-contract / 100.
        return abs(mv / (qty * 100.0))
    return None


# ── module-level entry: production wiring (called from main.py) ──────────────


def vrp_monitor_enabled(config: Dict[str, Any]) -> bool:
    """True iff the experiment opts into the VRP monitor.

    Mirrors :func:`compass.live.vrp_runner.vrp_enabled` — absent/false for every
    non-V8A experiment, so the scheduler hook is inert by default.
    """
    return bool((config.get("vrp_position_monitor") or {}).get("enabled", False))


def vrp_monitor_track_opens(config: Dict[str, Any]) -> bool:
    """True iff the runner should wrap its live sink with :class:`TrackingOrderSink`.

    Separate from :func:`vrp_monitor_enabled` so an operator can start *tracking*
    opens (filling the registry) before flipping the actual exit dispatcher on
    — useful for a one-cycle dry-run where the monitor just observes.
    """
    cfg = config.get("vrp_position_monitor") or {}
    # Track-opens implicitly required when monitor is enabled. Tracking on its
    # own is a separately-toggleable knob for the observation-only mode above.
    if cfg.get("enabled"):
        return True
    return bool(cfg.get("track_opens", False))


def run_vrp_monitor_cycle(system) -> MonitorReport:
    """One monitor cycle for the scheduler. Mirrors
    :func:`compass.live.vrp_runner.run_vrp_cycle` — call once per scan slot
    after the runner.

    Picks the sink type the runner is using (Alpaca by default, executor when
    ``vrp_engine.sink_type == 'executor'``) so closes go through the same
    broker that opened the position.
    """
    config = system.config
    registry = VRPPositionRegistry.default_for(config)

    cfg = config.get("vrp_position_monitor") or {}
    pt = float(cfg.get("profit_target_pct", DEFAULT_PROFIT_TARGET_PCT))
    sl = float(cfg.get("stop_loss_mult", DEFAULT_STOP_LOSS_MULT))
    roll = int(cfg.get("roll_dte", DEFAULT_ROLL_DTE))
    crisis = float(cfg.get("crisis_vix", DEFAULT_CRISIS_VIX))

    # Pick broker arm to use (alpaca | executor). Reuses vrp_runner's resolver
    # so monitor + runner agree on which sink to talk to per cycle.
    from compass.live.vrp_runner import _resolve_sink_type

    sink_type = _resolve_sink_type(config)

    alpaca_provider = None
    executor_sink = None
    if sink_type == "executor":
        try:
            from compass.live.executor_order_sink import ExecutorOrderSink
            executor_sink = ExecutorOrderSink.from_env()
        except Exception as exc:  # noqa: BLE001
            logger.error("[vrp_pm] executor sink unavailable (%s) — monitor degraded", exc)
            return MonitorReport(as_of=datetime.now(timezone.utc).isoformat(), vix=None, crisis=False,
                                 notes=[f"executor_sink_unavailable: {exc}"])
    else:
        alpaca_provider = getattr(system, "alpaca_provider", None)
        if alpaca_provider is None:
            logger.error("[vrp_pm] alpaca provider missing — monitor degraded")
            return MonitorReport(as_of=datetime.now(timezone.utc).isoformat(), vix=None, crisis=False,
                                 notes=["alpaca_provider_missing"])

    # VIX source — reuse cc2's live feed. Lazy + memoized via the default feed
    # singleton so the monitor doesn't open a second data session.
    def _vix() -> Optional[float]:
        try:
            from compass.live.vrp_data import get_default_feed
            return get_default_feed().get_vix_realtime()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[vrp_pm] get_vix_realtime failed: %s", exc)
            return None

    monitor = VRPPositionMonitor(
        registry,
        alpaca_provider=alpaca_provider,
        executor_sink=executor_sink,
        vix_source=_vix,
        profit_target_pct=pt,
        stop_loss_mult=sl,
        roll_dte=roll,
        crisis_vix=crisis,
    )
    return monitor.run_cycle()
