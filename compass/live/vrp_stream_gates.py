"""compass/live/vrp_stream_gates.py — per-stream entry gates for the VRP runner.

Three pure-logic gates that filter :class:`OrderIntent` objects produced by the
strategy BEFORE they reach the order sink. They exist because the VRP cycle
fires every ~5 min during market hours and the strategy itself is stateless: it
will happily emit the same xli_cs bull-put intent every cycle until the position
expires, stacking spreads on top of losing positions. The gates are:

  1. **Per-stream cooldown** — block new entry on a stream while any prior open
     spread is younger than ``cooldown_days`` (default 7). The "OR prior is closed"
     half is implicit: closes are recorded by pruning the state store; an absent
     entry means no cooldown blocks. Live close detection (broker reconciliation)
     is build-plan PR-H scope, not this PR.

  2. **Duplicate-expiration suppression** — block a new entry on stream X with
     the same option expiration date as any already-open spread on stream X.

  3. **Max-open-spreads per stream** — refuse new entries on stream X once it
     already has ``max_open_per_stream`` (default 1, matches the EXP-2850
     backtest assumption).

A small :class:`StreamStateStore` protocol decouples the gates from persistence;
the runner uses a :class:`JsonStreamStateStore` backed by an experiment-isolated
file (``data/vrp_stream_state_<experiment_id>.json``) so the state survives
worker restarts. Tests use :class:`InMemoryStreamStateStore`.

ADDITIVE: nothing here is wired into the legacy champion path. The runner is
guarded on ``vrp_engine.enabled``, and the gate block itself has a master
``enabled`` switch (default true) so it can be flipped off without removing
config keys.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from compass.live.vrp_contracts import OrderIntent

logger = logging.getLogger(__name__)


# ── dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OpenSpread:
    """A single recorded open-spread entry (one per successful sink submission).

    ``opened_at`` is the time of the submission (NOT the broker fill time); the
    cooldown clock starts then. ``expiration`` is the option-expiration date of
    the spread (used by the dup-expiration gate). ``client_order_id`` is the
    deterministic id emitted by :func:`vrp_sinks.stream_client_order_id` and is
    handy for cross-referencing the broker side during debugging.
    """

    stream_id: str
    opened_at: datetime
    expiration: date
    contracts: int
    client_order_id: str = ""


@dataclass(frozen=True)
class StreamGateConfig:
    """Configurable knobs for the three gates.

    Read from ``vrp_engine.stream_gates`` in the experiment YAML via
    :meth:`from_config`. With ``enabled=False`` the gates pass every intent
    through unchanged — a safe kill-switch without removing the config block.
    """

    enabled: bool = True
    cooldown_days: int = 7
    max_open_per_stream: int = 1
    deduplicate_expirations: bool = True

    @classmethod
    def from_config(cls, config: dict) -> "StreamGateConfig":
        cfg = (config.get("vrp_engine") or {}).get("stream_gates") or {}
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            cooldown_days=int(cfg.get("cooldown_days", 7)),
            max_open_per_stream=int(cfg.get("max_open_per_stream", 1)),
            deduplicate_expirations=bool(cfg.get("deduplicate_expirations", True)),
        )


@dataclass
class GateResult:
    """Outcome of one filter pass: which intents survive, which were dropped."""

    kept: List[OrderIntent] = field(default_factory=list)
    blocked: List[Tuple[OrderIntent, str]] = field(default_factory=list)

    @property
    def block_reasons_by_stream(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for intent, reason in self.blocked:
            out.setdefault(intent.stream, []).append(reason)
        return out


# ── state-store protocol + two implementations ───────────────────────────────


@runtime_checkable
class StreamStateStore(Protocol):
    """Persistence seam for open-spread records the gates read.

    Implementations are free to back this with a file, the experiment SQLite
    DB, or a memory dict (tests). The runner only calls these four methods.
    """

    def list_open(self, stream_id: str) -> List[OpenSpread]: ...

    def record_submission(
        self, intent: OrderIntent, *, now: Optional[datetime] = None, client_order_id: str = ""
    ) -> OpenSpread: ...

    def prune_older_than(self, days: int, *, now: Optional[datetime] = None) -> int: ...

    def all_open(self) -> List[OpenSpread]: ...


class InMemoryStreamStateStore:
    """Volatile state store for tests + dry-run cycles."""

    def __init__(self, entries: Optional[Sequence[OpenSpread]] = None) -> None:
        self._entries: List[OpenSpread] = list(entries or [])

    def list_open(self, stream_id: str) -> List[OpenSpread]:
        return [e for e in self._entries if e.stream_id == stream_id]

    def all_open(self) -> List[OpenSpread]:
        return list(self._entries)

    def record_submission(
        self, intent: OrderIntent, *, now: Optional[datetime] = None, client_order_id: str = ""
    ) -> OpenSpread:
        ts = now or _utcnow()
        expiration = _intent_expiration(intent)
        entry = OpenSpread(
            stream_id=intent.stream, opened_at=ts, expiration=expiration,
            contracts=int(intent.contracts), client_order_id=client_order_id,
        )
        self._entries.append(entry)
        return entry

    def prune_older_than(self, days: int, *, now: Optional[datetime] = None) -> int:
        if days <= 0:
            return 0
        cutoff = (now or _utcnow()) - timedelta(days=days)
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.opened_at >= cutoff]
        return before - len(self._entries)


class JsonStreamStateStore:
    """File-backed store. Atomic writes (tmpfile + rename), no concurrent writers.

    The on-disk shape is a JSON list of ``{stream_id, opened_at, expiration,
    contracts, client_order_id}`` objects. Missing/corrupt files are treated as
    empty — we never crash the cycle on store IO and instead log + degrade to a
    blank state (the per-stream VIX gate at the strategy layer still applies).
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    # — internal IO —

    def _read(self) -> List[OpenSpread]:
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text()
            data = json.loads(raw) if raw.strip() else []
        except Exception as exc:  # noqa: BLE001 — never crash the runner on store IO
            logger.warning("[vrp_gates] state read failed at %s: %s — treating as empty", self._path, exc)
            return []
        out: List[OpenSpread] = []
        for row in data:
            try:
                out.append(OpenSpread(
                    stream_id=str(row["stream_id"]),
                    opened_at=_parse_dt(row["opened_at"]),
                    expiration=_parse_date(row["expiration"]),
                    contracts=int(row.get("contracts", 0)),
                    client_order_id=str(row.get("client_order_id", "")),
                ))
            except Exception as exc:  # noqa: BLE001 — skip malformed rows individually
                logger.warning("[vrp_gates] skipping malformed state row %r: %s", row, exc)
        return out

    def _write(self, entries: Sequence[OpenSpread]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "stream_id": e.stream_id,
                "opened_at": e.opened_at.astimezone(timezone.utc).isoformat(),
                "expiration": e.expiration.isoformat(),
                "contracts": int(e.contracts),
                "client_order_id": e.client_order_id,
            }
            for e in entries
        ]
        # Atomic rename to avoid partial writes if the worker is killed mid-flush.
        fd, tmp_name = tempfile.mkstemp(prefix=".vrp_gates_", dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_name, self._path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # — public API —

    def list_open(self, stream_id: str) -> List[OpenSpread]:
        return [e for e in self._read() if e.stream_id == stream_id]

    def all_open(self) -> List[OpenSpread]:
        return self._read()

    def record_submission(
        self, intent: OrderIntent, *, now: Optional[datetime] = None, client_order_id: str = ""
    ) -> OpenSpread:
        ts = now or _utcnow()
        expiration = _intent_expiration(intent)
        entry = OpenSpread(
            stream_id=intent.stream, opened_at=ts, expiration=expiration,
            contracts=int(intent.contracts), client_order_id=client_order_id,
        )
        existing = self._read()
        existing.append(entry)
        self._write(existing)
        return entry

    def prune_older_than(self, days: int, *, now: Optional[datetime] = None) -> int:
        if days <= 0:
            return 0
        cutoff = (now or _utcnow()) - timedelta(days=days)
        before_entries = self._read()
        kept = [e for e in before_entries if e.opened_at >= cutoff]
        removed = len(before_entries) - len(kept)
        if removed:
            self._write(kept)
        return removed


# ── the gate logic (pure function) ────────────────────────────────────────────


def apply_stream_gates(
    intents: Sequence[OrderIntent],
    store: StreamStateStore,
    config: StreamGateConfig,
    *,
    now: Optional[datetime] = None,
) -> GateResult:
    """Filter ``intents`` through cooldown + dup-expiration + max-open gates.

    Order of evaluation per intent:

      1. ``max_open_per_stream`` (cheapest, counts only).
      2. ``deduplicate_expirations`` (same exp on same stream blocks).
      3. ``cooldown_days`` (any open entry younger than the cutoff blocks).

    If the same cycle emits multiple intents for the same stream, they are
    evaluated sequentially against a running "pending" set so a single cycle
    can't punch through the max-open cap by submitting two intents at once.

    With ``config.enabled=False`` the function is a pass-through (every intent
    is returned in ``kept``). Useful as a kill switch without removing config.
    """
    result = GateResult()
    if not config.enabled or not intents:
        result.kept = list(intents)
        return result

    now_ts = now or _utcnow()
    cooldown_cutoff = now_ts - timedelta(days=max(0, config.cooldown_days))

    # Working snapshot keyed by stream, so cycle-local intents stack correctly.
    pending: Dict[str, List[OpenSpread]] = {}
    for intent in intents:
        sid = intent.stream
        if sid not in pending:
            pending[sid] = list(store.list_open(sid))

        # — gate 1: max open per stream —
        if len(pending[sid]) >= max(1, config.max_open_per_stream):
            result.blocked.append((intent, (
                f"max_open_per_stream={config.max_open_per_stream} reached "
                f"({len(pending[sid])} open on {sid})"
            )))
            continue

        # — gate 2: dup expiration —
        candidate_exp = _safe_intent_expiration(intent)
        if config.deduplicate_expirations and candidate_exp is not None:
            dup = next((e for e in pending[sid] if e.expiration == candidate_exp), None)
            if dup is not None:
                result.blocked.append((intent, (
                    f"duplicate expiration {candidate_exp.isoformat()} on {sid} "
                    f"(open since {dup.opened_at.isoformat()})"
                )))
                continue

        # — gate 3: cooldown —
        recent = [e for e in pending[sid] if e.opened_at >= cooldown_cutoff]
        if recent:
            youngest = max(recent, key=lambda e: e.opened_at)
            age_days = (now_ts - youngest.opened_at).total_seconds() / 86400.0
            result.blocked.append((intent, (
                f"cooldown_days={config.cooldown_days} not met "
                f"(prior {sid} entry {age_days:.1f}d old, opened {youngest.opened_at.isoformat()})"
            )))
            continue

        result.kept.append(intent)
        # Cycle-local stacking: a kept intent contributes to the next decision
        # within this same call so two intents on the same stream don't both pass.
        pending[sid].append(OpenSpread(
            stream_id=sid, opened_at=now_ts,
            expiration=candidate_exp or now_ts.date(),
            contracts=int(intent.contracts),
        ))

    return result


# ── helpers ──────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _intent_expiration(intent: OrderIntent) -> date:
    """Best-effort expiration extraction; falls back to ``today`` so the store
    can still record (the dup-expiration gate will skip a fallback date)."""
    parsed = _safe_intent_expiration(intent)
    return parsed or _utcnow().date()


def _safe_intent_expiration(intent: OrderIntent) -> Optional[date]:
    for leg in intent.legs:
        if leg.expiration:
            try:
                return datetime.strptime(str(leg.expiration), "%Y-%m-%d").date()
            except ValueError:
                continue
    return None


def _parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value)
    # Tolerate trailing Z (older Python json roundtrips).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


# ── factory used by the runner ───────────────────────────────────────────────


def default_state_path(config: dict) -> Path:
    """Per-experiment state-file path. Falls back to a generic ``vrp_engine`` slug.

    Default: ``<cwd>/data/vrp_stream_state_<experiment_id>.json`` to mirror the
    per-experiment trade-DB convention (``data/attix_<experiment_id>.db``, or
    the legacy ``pilotai_`` prefix on pre-rename experiments).
    """
    exp_id = str(config.get("experiment_id") or "vrp_engine").strip().lower().replace("-", "_")
    return Path("data") / f"vrp_stream_state_{exp_id}.json"


def build_state_store(config: dict) -> StreamStateStore:
    """Construct the default file-backed store for production use.

    Tests bypass this and pass :class:`InMemoryStreamStateStore` directly.
    """
    return JsonStreamStateStore(default_state_path(config))


# ── result-detection helpers (used by the runner on the sink's return value) ──


_SUBMISSION_SUCCESS_STATUSES = frozenset({
    "submitted", "accepted", "filled", "partially_filled", "open", "new", "pending",
})


def submission_was_live(result: object) -> bool:
    """True when the sink result indicates a real broker placement (not a
    dry-run "recorded" status and not an error). Used by the runner to decide
    whether to persist the state row.
    """
    if not isinstance(result, dict):
        return False
    status = str(result.get("status", "")).lower()
    if not status:
        # Some adapters set success=True without a status.
        return bool(result.get("success"))
    return status in _SUBMISSION_SUCCESS_STATUSES
