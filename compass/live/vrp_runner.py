"""compass/live/vrp_runner.py — PR-E cutover wiring for EXP-V8A.

Composes the live VRP dependencies into a runnable cycle and exposes the seam
the scheduler calls when ``vrp_engine.enabled`` is set in an experiment's config:

    cc2 PR-A  VRPDataFeed            (live multi-symbol chains + VIX)
    cc3 PR-C  compute_weights        (LW risk-parity, via the engine)
    cc4 PR-D  resolve_vix_ladder_signal  (wrapped by Cc4VixExposure → multiplier)
    PR-B      VRPMultiStreamStrategy (the engine, merged #77)
              <OrderSink>            (Alpaca | Executor-REST — only when not dry-run)

Two sinks are wired (selected per-cycle, ADDITIVE):

  * :class:`compass.live.vrp_sinks.AlpacaOrderSink` — DEFAULT. The Railway live
    worker already trades V8A through Alpaca via this path.
  * :class:`compass.live.executor_order_sink.ExecutorOrderSink` — opt-in via
    ``SINK_TYPE=executor`` env var (or ``vrp_engine.sink_type: executor`` in the
    experiment config). Routes the same intents through the standalone Executor
    REST service (IBKR paper, today). Inert for every existing experiment.

ADDITIVE + INERT BY DEFAULT. The scheduler hook is guarded on
``config['vrp_engine']['enabled']`` (absent for every other experiment), and the
shipped EXP-V8A config sets ``enabled: false`` / ``dry_run: true``. The actual
Champion→VRP cutover is a one-line config toggle performed only AFTER the legacy
positions are flat (the flush — see docs/V8A_VRP_RECON_FLUSH_PLAN.md).
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Dict, List, Optional

from compass.live.vrp_contracts import OrderIntent, STREAM_SPECS, StreamStatus
from compass.live.vrp_returns_provider import PersistedReturnsProvider
from compass.live.vrp_risk_caps import (
    VRPRiskCaps,
    existing_positions_from_db,
)
from compass.live.vrp_stream_gates import (
    StreamGateConfig,
    StreamStateStore,
    apply_stream_gates,
    build_state_store,
    submission_was_live,
)

logger = logging.getLogger(__name__)


def _active_stream_ids() -> list[str]:
    """The streams whose generators can actually place orders today (TRADEABLE).

    Computed from :data:`STREAM_SPECS` so it stays in sync as new streams flip
    from DEFERRED → TRADEABLE without touching this module.
    """
    return [sid for sid, spec in STREAM_SPECS.items() if spec.status is StreamStatus.TRADEABLE]


def _resolve_db_path(config: dict) -> Optional[str]:
    """Per-experiment SQLite path the worker uses for this experiment.

    Precedence: ``ATTIX_DB_PATH`` env (worker exports this per-experiment via
    ``railway_worker``) > config ``db_path`` > ``None`` (fall back to the default
    in :func:`shared.database.get_db_path`).
    """
    env = os.environ.get("ATTIX_DB_PATH")
    if env:
        return env
    p = config.get("db_path") if config else None
    return str(p) if p else None


def _default_vix_signal() -> Dict:
    """Call cc4's PR-D live ladder. Lazy import (avoids feed/state side effects
    until actually used)."""
    from compass.live.vrp_vix_ladder import resolve_vix_ladder_signal
    return resolve_vix_ladder_signal()


class Cc4VixExposure:
    """Adapts cc4's PR-D ``resolve_vix_ladder_signal() -> Dict`` to PR-B's
    ``VixExposureProvider`` protocol (``current_exposure_multiplier() -> float``).

    Returns the signal's ``sizing_multiplier``, but **halts (0.0) when cc4's
    ``entry_gate`` is False** — i.e. the live circuit-breaker block (VIX ≥ 35)
    overrides the soft ladder multiplier (CB > ladder; recon cc4 §3.2). When cc4
    ships the ``current_exposure_multiplier()`` convenience, this adapter can call
    it directly; until then it reads the dict it already returns.
    """

    def __init__(self, signal_fn: Optional[Callable[[], Dict]] = None) -> None:
        self._signal_fn = signal_fn or _default_vix_signal

    def current_exposure_multiplier(self) -> float:
        try:
            sig = self._signal_fn()
        except Exception as exc:  # noqa: BLE001 — fail flat, never crash sizing
            logger.error("[vrp_runner] vix signal failed: %s — halting new entries", exc)
            return 0.0
        if not sig.get("entry_gate", True):
            return 0.0
        try:
            return float(sig.get("sizing_multiplier", 0.0))
        except (TypeError, ValueError):
            return 0.0


def _resolve_sink_type(config: dict) -> str:
    """Return ``"alpaca"`` (default) or ``"executor"``.

    Precedence: env var ``SINK_TYPE`` > ``vrp_engine.sink_type`` config key >
    ``"alpaca"``. Unknown values warn and fall back to ``"alpaca"`` to keep the
    Alpaca path the failsafe default for the existing Railway worker.
    """
    cfg = (config.get("vrp_engine") or {}) if config else {}
    raw = (os.environ.get("SINK_TYPE") or cfg.get("sink_type") or "alpaca").strip().lower()
    if raw not in ("alpaca", "executor"):
        logger.warning("[vrp_runner] unknown SINK_TYPE=%r — defaulting to 'alpaca'", raw)
        return "alpaca"
    return raw


def _equity_from_executor(sink) -> float:
    """Read account equity from the executor balance endpoint, with a 0.0 fallback."""
    try:
        bal = sink.get_balance()
        return float(bal.get("total_equity", 0.0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[vrp_runner] executor balance fetch failed: %s", exc)
        return 0.0


def build_vrp_strategy(
    config: dict,
    alpaca_provider,
    *,
    data_feed=None,
    vix_provider=None,
    equity_source: Optional[Callable[[], float]] = None,
):
    """Construct a configured ``VRPMultiStreamStrategy`` for the live worker.

    Account equity defaults to live Alpaca each cycle (falls back to 0 → no
    allocation if unavailable). ``equity_source`` overrides that — used to feed
    equity from the executor balance endpoint when ``SINK_TYPE=executor``.
    ``data_feed``/``vix_provider`` are injectable for tests; defaults are cc2's
    process-global feed and the cc4 adapter.
    """
    from compass.live.vrp_data import get_default_feed
    from compass.live.vrp_strategy import VRPMultiStreamStrategy

    cfg = config.get("vrp_engine", {}) or {}
    feed = data_feed if data_feed is not None else get_default_feed()
    vix = vix_provider if vix_provider is not None else Cc4VixExposure()

    if equity_source is not None:
        _equity = equity_source
    else:
        def _equity() -> float:
            if alpaca_provider is None:
                return 0.0
            try:
                return float(alpaca_provider.get_account().get("equity", 0.0))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[vrp_runner] equity fetch failed: %s", exc)
                return 0.0

    dte = cfg.get("dte_range", [25, 50])

    # ── PR-I: per-stream returns persistence (replaces StaticReturnsProvider) ─
    exp_id = (config.get("experiment_id") or "").strip()
    db_path = _resolve_db_path(config)
    returns_provider = None
    if exp_id:
        try:
            returns_provider = PersistedReturnsProvider(
                exp_id=exp_id,
                stream_columns=_active_stream_ids(),
                db_path=db_path,
            )
        except Exception as exc:  # noqa: BLE001 — fall back to stub on misconfig
            logger.warning("[vrp_runner] PersistedReturnsProvider init failed (%s) "
                           "— falling back to StaticReturnsProvider", exc)
            returns_provider = None
    else:
        logger.warning("[vrp_runner] no experiment_id in config — using stub returns "
                       "provider (cold-start prior forever)")

    # ── VRP-native risk caps (vrp_risk: block) ────────────────────────────────
    try:
        risk_caps = VRPRiskCaps.from_config(config.get("vrp_risk") if config else None)
    except ValueError as exc:
        logger.error("[vrp_runner] invalid vrp_risk config: %s — caps DISABLED for safety review",
                     exc)
        risk_caps = VRPRiskCaps()

    # Position source for the cap filter: open trades for this experiment from
    # the worker DB. None when no exp_id — caps then only see this cycle's intents.
    if exp_id and not risk_caps.is_inert():
        def _position_source():
            return existing_positions_from_db(exp_id, db_path=db_path)
    else:
        _position_source = None

    return VRPMultiStreamStrategy(
        feed,
        account_equity=_equity,
        vix_provider=vix,
        returns_provider=returns_provider,
        vol_target=float(cfg.get("vol_target", 0.12)),
        dte_range=(int(dte[0]), int(dte[1])),
        risk_caps=risk_caps,
        position_source=_position_source,
    )


def vrp_enabled(config: dict) -> bool:
    """True only when the experiment's config opts into the VRP engine.

    Guard for the shared scheduler: absent/false for every non-VRP experiment, so
    the legacy scan path is completely unaffected.
    """
    return bool((config.get("vrp_engine") or {}).get("enabled", False))


def run_vrp_cycle(system, *, strategy=None, state_store: Optional[StreamStateStore] = None):
    """One VRP scan cycle for the scheduler. Plans intents; filters them through
    the per-stream gates (cooldown + dup-expiration + max-open); places only
    survivors when ``vrp_engine.dry_run`` is false AND a live sink is wired.

    The sink is selected per-cycle by :func:`_resolve_sink_type`. The default
    ``alpaca`` path is byte-for-byte unchanged for non-VRP experiments — they
    never enter this function. The gates run for every VRP cycle (live OR
    dry-run); the state file is updated only when the cycle actually placed an
    order with the broker (so dry-runs never pollute live state).

    ``state_store`` is injectable for tests; production uses
    :func:`vrp_stream_gates.build_state_store` keyed by the experiment id.

    Returns the :class:`CyclePlan` (also when dry-run) for logging/telemetry.
    Blocked intents are removed from ``plan.intents`` and surfaced in
    ``plan.stream_status`` so the existing per-stream log lines explain why.
    """
    cfg = system.config.get("vrp_engine", {}) or {}
    provider = getattr(system, "alpaca_provider", None)
    sink_type = _resolve_sink_type(system.config)

    # Build the live sink (and equity source) BEFORE the strategy so executor
    # mode can swap its balance endpoint in for sizing.
    live_sink = None
    equity_source: Optional[Callable[[], float]] = None
    if sink_type == "executor":
        try:
            from compass.live.executor_order_sink import ExecutorOrderSink
            live_sink = ExecutorOrderSink.from_env()
            equity_source = lambda s=live_sink: _equity_from_executor(s)
        except Exception as exc:  # noqa: BLE001 — degrade to dry-run, never crash
            logger.error("[vrp_runner] executor sink unavailable (%s) — forcing dry-run", exc)
            live_sink = None

    strat = strategy or build_vrp_strategy(
        system.config, provider, equity_source=equity_source,
    )

    # Dry-run if the experiment is configured for it, OR no live sink is wired.
    if sink_type == "executor":
        dry_run = bool(cfg.get("dry_run", True)) or live_sink is None
    else:
        dry_run = bool(cfg.get("dry_run", True)) or provider is None

    # Plan first; gate; then submit the survivors. Strategy stays pure — the
    # runner owns live-trading state.
    plan = strat.plan_cycle()

    gate_cfg = StreamGateConfig.from_config(system.config)
    store = state_store if state_store is not None else build_state_store(system.config)

    # Hygiene: drop stale entries older than the cooldown window so the file
    # doesn't grow unbounded across long-running workers.
    try:
        pruned = store.prune_older_than(max(gate_cfg.cooldown_days, 1))
        if pruned:
            logger.info("[vrp_runner] pruned %d stale stream-state entries", pruned)
    except Exception as exc:  # noqa: BLE001 — never crash the cycle on store IO
        logger.warning("[vrp_runner] state-store prune failed: %s", exc)

    try:
        gate_result = apply_stream_gates(plan.intents, store, gate_cfg)
    except Exception as exc:  # noqa: BLE001 — gate failure must not stop trading; log loudly
        logger.error("[vrp_runner] gate evaluation failed (%s) — passing all intents through", exc)
        from compass.live.vrp_stream_gates import GateResult  # local import on the rare error path
        gate_result = GateResult(kept=list(plan.intents), blocked=[])

    # Surface gate decisions on the plan so downstream logs/telemetry see them.
    plan.intents = list(gate_result.kept)
    if gate_result.blocked:
        for intent, reason in gate_result.blocked:
            prior = plan.stream_status.get(intent.stream, "")
            tag = f"gate_blocked: {reason}"
            plan.stream_status[intent.stream] = f"{prior} | {tag}" if prior else tag
        plan.notes.append(
            f"stream-gates blocked {len(gate_result.blocked)} intent(s) "
            f"across {len(gate_result.block_reasons_by_stream)} stream(s)"
        )

    # Submit the survivors. Recording (state-store writes) only happens on a
    # real broker placement, not a dry-run "recorded" status.
    results: List[dict] = []
    if dry_run or not plan.intents:
        # Dry-run path leaves plan.intents in place for telemetry; nothing placed.
        pass
    else:
        # PR-H seam: when the VRP-aware PositionMonitor is enabled (or
        # ``vrp_monitor.track_opens`` is explicitly set), wrap the live sink
        # with TrackingOrderSink so each successful submit also writes to the
        # per-experiment VRPPositionRegistry the monitor reads to evaluate
        # PT/SL/DTE-roll exits.
        from compass.live.vrp_position_monitor import vrp_monitor_track_opens

        if sink_type == "executor":
            sink_to_use = live_sink
        else:
            from compass.live.vrp_sinks import AlpacaOrderSink
            sink_to_use = AlpacaOrderSink(provider)

        if vrp_monitor_track_opens(system.config):
            from compass.live.vrp_position_monitor import (
                TrackingOrderSink, VRPPositionRegistry,
            )
            registry = VRPPositionRegistry.default_for(system.config)
            sink_to_use = TrackingOrderSink(sink_to_use, registry)

        results = _submit_through_sink(plan.intents, sink_to_use, store)

    # Per-stream visibility, incl. the deferred futures sleeves.
    for sid, status in plan.stream_status.items():
        if STREAM_SPECS.get(sid) and STREAM_SPECS[sid].status is StreamStatus.BLOCKED:
            logger.info("[vrp_runner] %s: futures venue pending (deferred)", sid)
        else:
            logger.info("[vrp_runner] %s: %s", sid, status)

    logger.info(
        "[vrp_runner] cycle %s sink=%s equity=$%.0f vix_mult=%.3f intents_kept=%d gate_blocked=%d placed=%d streams=%s%s",
        "DRY-RUN" if dry_run else "LIVE",
        sink_type,
        plan.account_equity, plan.vix_exposure,
        len(plan.intents), len(gate_result.blocked), len(results),
        ",".join(plan.traded_streams) or "-",
        f" notes={plan.notes}" if plan.notes else "",
    )
    return plan


def _submit_through_sink(
    intents: List[OrderIntent], sink, store: StreamStateStore,
) -> List[dict]:
    """Submit each intent through ``sink``, recording state ONLY on broker
    placements (so dry-run / recording sinks never write to the live state).
    """
    results: List[dict] = []
    for intent in intents:
        result = sink.submit(intent)
        results.append(result)
        if not submission_was_live(result):
            continue
        try:
            coid = ""
            if isinstance(result, dict):
                coid = str(result.get("client_order_id") or result.get("order_id") or "")
            store.record_submission(intent, client_order_id=coid)
        except Exception as exc:  # noqa: BLE001 — never crash on persistence error
            logger.warning(
                "[vrp_runner] failed to record stream-state for %s: %s — gate may re-fire next cycle",
                intent.stream, exc,
            )
    return results
