"""Tests for compass.live.vrp_stream_gates — per-stream cooldown + dup-suppress +
max-open caps that filter OrderIntents before they reach the order sink.

Pure-logic tests; no Alpaca, no executor, no real worker. The runner-integration
side lives in tests/test_vrp_runner.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from compass.live.vrp_contracts import OrderIntent, OrderLeg
from compass.live.vrp_stream_gates import (
    GateResult,
    InMemoryStreamStateStore,
    JsonStreamStateStore,
    OpenSpread,
    StreamGateConfig,
    apply_stream_gates,
    build_state_store,
    default_state_path,
    submission_was_live,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _intent(stream="xli_cs", symbol="XLI", short=165.0, long_=160.0, exp="2026-06-26", n=10) -> OrderIntent:
    legs = (
        OrderLeg(side="sell", sec_type="option", symbol=f"{symbol}_short", qty=n,
                 strike=short, expiration=exp, right="P"),
        OrderLeg(side="buy", sec_type="option", symbol=f"{symbol}_long", qty=n,
                 strike=long_, expiration=exp, right="P"),
    )
    return OrderIntent(
        stream=stream, symbol=symbol, structure="bull_put",
        legs=legs, contracts=n, est_credit=0.36, est_max_loss=4.64,
        rationale=f"{symbol} bull put {short:.0f}/{long_:.0f} exp {exp} x{n}",
    )


def _open(stream="xli_cs", days_old=0.0, exp="2026-06-26", *, now=None) -> OpenSpread:
    ts = (now or datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)) - timedelta(days=days_old)
    return OpenSpread(
        stream_id=stream, opened_at=ts,
        expiration=datetime.strptime(exp, "%Y-%m-%d").date(),
        contracts=10, client_order_id=f"vrp-{stream}-{exp}-test",
    )


NOW = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


# ── StreamGateConfig.from_config ─────────────────────────────────────────────


def test_from_config_defaults_when_block_absent():
    cfg = StreamGateConfig.from_config({})
    assert cfg.enabled is True
    assert cfg.cooldown_days == 7
    assert cfg.max_open_per_stream == 1
    assert cfg.deduplicate_expirations is True


def test_from_config_reads_yaml_block():
    cfg = StreamGateConfig.from_config({
        "vrp_engine": {"stream_gates": {
            "enabled": True, "cooldown_days": 14,
            "max_open_per_stream": 2, "deduplicate_expirations": False,
        }}
    })
    assert (cfg.cooldown_days, cfg.max_open_per_stream, cfg.deduplicate_expirations) == (14, 2, False)


def test_from_config_disabled_kill_switch():
    cfg = StreamGateConfig.from_config({"vrp_engine": {"stream_gates": {"enabled": False}}})
    assert cfg.enabled is False


# ── apply_stream_gates: pass-through when no state ──────────────────────────


def test_no_state_passes_all_intents():
    res = apply_stream_gates(
        [_intent("xli_cs"), _intent("xlf_cs", "XLF")],
        InMemoryStreamStateStore(),
        StreamGateConfig(),
        now=NOW,
    )
    assert len(res.kept) == 2
    assert res.blocked == []


def test_disabled_config_is_passthrough_even_with_state():
    # Even if state would otherwise block, enabled=False short-circuits.
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=0.5, now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs")], store,
        StreamGateConfig(enabled=False),
        now=NOW,
    )
    assert len(res.kept) == 1
    assert res.blocked == []


# ── gate 1: max_open_per_stream ──────────────────────────────────────────────


def test_max_open_blocks_when_cap_reached():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=30, now=NOW)])  # past cooldown
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-07-26")],  # different exp so dup gate won't fire
        store, StreamGateConfig(max_open_per_stream=1, cooldown_days=7),
        now=NOW,
    )
    assert res.kept == []
    assert len(res.blocked) == 1
    intent, reason = res.blocked[0]
    assert "max_open_per_stream=1" in reason


def test_max_open_allows_when_cap_higher():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=30, now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-07-26")],
        store, StreamGateConfig(max_open_per_stream=2, cooldown_days=0),
        now=NOW,
    )
    assert len(res.kept) == 1


def test_max_open_blocks_intra_cycle_stacking():
    """Two intents on the same stream in one cycle must not both pass at cap=1."""
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-06-26"), _intent("xli_cs", exp="2026-07-26")],
        InMemoryStreamStateStore(),
        StreamGateConfig(max_open_per_stream=1, cooldown_days=0),
        now=NOW,
    )
    assert len(res.kept) == 1
    assert len(res.blocked) == 1
    assert "max_open_per_stream" in res.blocked[0][1]


# ── gate 2: deduplicate_expirations ──────────────────────────────────────────


def test_dup_expiration_blocks_same_exp():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=30, exp="2026-06-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-06-26")],
        store, StreamGateConfig(
            max_open_per_stream=5, cooldown_days=0, deduplicate_expirations=True,
        ),
        now=NOW,
    )
    assert res.kept == []
    assert "duplicate expiration 2026-06-26" in res.blocked[0][1]


def test_dup_expiration_allows_different_exp():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=30, exp="2026-06-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-07-26")],
        store, StreamGateConfig(max_open_per_stream=5, cooldown_days=0),
        now=NOW,
    )
    assert len(res.kept) == 1


def test_dup_expiration_can_be_disabled():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=30, exp="2026-06-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-06-26")],
        store, StreamGateConfig(
            max_open_per_stream=5, cooldown_days=0, deduplicate_expirations=False,
        ),
        now=NOW,
    )
    assert len(res.kept) == 1


# ── gate 3: cooldown_days ────────────────────────────────────────────────────


def test_cooldown_blocks_when_recent_entry_exists():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=3.5, exp="2026-07-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-08-26")],  # different exp; max_open bumped to isolate cooldown
        store, StreamGateConfig(
            max_open_per_stream=5, cooldown_days=7, deduplicate_expirations=True,
        ),
        now=NOW,
    )
    assert res.kept == []
    assert "cooldown_days=7" in res.blocked[0][1]
    assert "3.5d old" in res.blocked[0][1]


def test_cooldown_allows_after_threshold():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=8.0, exp="2026-07-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-08-26")],
        store, StreamGateConfig(
            max_open_per_stream=5, cooldown_days=7, deduplicate_expirations=True,
        ),
        now=NOW,
    )
    assert len(res.kept) == 1


def test_cooldown_zero_disables_gate():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=0.5, exp="2026-07-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-08-26")],
        store, StreamGateConfig(max_open_per_stream=5, cooldown_days=0),
        now=NOW,
    )
    assert len(res.kept) == 1


# ── gate independence: one stream blocked, others pass ──────────────────────


def test_block_isolated_to_offending_stream():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=1.0, exp="2026-06-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs"), _intent("xlf_cs", "XLF"), _intent("qqq_cs", "QQQ")],
        store, StreamGateConfig(),
        now=NOW,
    )
    kept_streams = sorted(i.stream for i in res.kept)
    assert kept_streams == ["qqq_cs", "xlf_cs"]
    assert res.blocked[0][0].stream == "xli_cs"


# ── evaluation order: max_open before dup before cooldown ───────────────────


def test_max_open_reason_wins_when_both_conditions_apply():
    store = InMemoryStreamStateStore([_open("xli_cs", days_old=1.0, exp="2026-06-26", now=NOW)])
    res = apply_stream_gates(
        [_intent("xli_cs", exp="2026-06-26")],  # same exp + recent + cap=1
        store, StreamGateConfig(),
        now=NOW,
    )
    # Per the documented eval order, max_open is checked first.
    assert "max_open_per_stream" in res.blocked[0][1]


# ── InMemoryStreamStateStore lifecycle ───────────────────────────────────────


def test_inmemory_record_and_prune():
    store = InMemoryStreamStateStore()
    store.record_submission(_intent("xli_cs"), now=NOW - timedelta(days=10), client_order_id="abc")
    store.record_submission(_intent("xlf_cs", "XLF"), now=NOW - timedelta(hours=1), client_order_id="def")

    assert len(store.all_open()) == 2

    removed = store.prune_older_than(days=7, now=NOW)
    assert removed == 1
    survivors = store.all_open()
    assert len(survivors) == 1
    assert survivors[0].stream_id == "xlf_cs"


# ── JsonStreamStateStore round-trip ──────────────────────────────────────────


def test_json_store_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store = JsonStreamStateStore(path)
    intent = _intent("xli_cs", exp="2026-06-26")
    store.record_submission(intent, now=NOW, client_order_id="vrp-xli_cs-XLI-2026-06-26-165-160")

    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["stream_id"] == "xli_cs"
    assert data[0]["expiration"] == "2026-06-26"

    reread = JsonStreamStateStore(path).list_open("xli_cs")
    assert len(reread) == 1
    assert reread[0].stream_id == "xli_cs"
    assert reread[0].expiration.isoformat() == "2026-06-26"


def test_json_store_missing_file_is_empty(tmp_path):
    store = JsonStreamStateStore(tmp_path / "absent.json")
    assert store.list_open("xli_cs") == []
    assert store.all_open() == []
    # Prune on absent file is a no-op.
    assert store.prune_older_than(7, now=NOW) == 0


def test_json_store_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json")
    store = JsonStreamStateStore(path)
    # Should NOT raise — the runner must never crash on store IO.
    assert store.all_open() == []


def test_json_store_skips_malformed_rows_but_keeps_valid(tmp_path):
    path = tmp_path / "mixed.json"
    payload = [
        {"stream_id": "ok", "opened_at": NOW.isoformat(), "expiration": "2026-06-26",
         "contracts": 5, "client_order_id": "x"},
        {"stream_id": "bad", "opened_at": "not-a-date", "expiration": "2026-06-26"},
    ]
    path.write_text(json.dumps(payload))
    survivors = JsonStreamStateStore(path).all_open()
    assert len(survivors) == 1
    assert survivors[0].stream_id == "ok"


def test_json_store_atomic_write_no_leftover_tmpfiles(tmp_path):
    store = JsonStreamStateStore(tmp_path / "state.json")
    store.record_submission(_intent("xli_cs"), now=NOW, client_order_id="x")
    store.record_submission(_intent("xlf_cs", "XLF"), now=NOW, client_order_id="y")
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".vrp_gates_")]
    assert leftovers == [], f"unexpected tmpfiles left behind: {leftovers}"


# ── default_state_path / build_state_store ───────────────────────────────────


def test_default_state_path_uses_experiment_id():
    p = default_state_path({"experiment_id": "EXP-V8A-IBKR"})
    assert p == Path("data") / "vrp_stream_state_exp_v8a_ibkr.json"


def test_default_state_path_fallback_when_no_experiment():
    p = default_state_path({})
    assert p == Path("data") / "vrp_stream_state_vrp_engine.json"


def test_build_state_store_returns_json_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = build_state_store({"experiment_id": "TEST"})
    assert isinstance(store, JsonStreamStateStore)


# ── submission_was_live result-detection helper ──────────────────────────────


@pytest.mark.parametrize("result, expected", [
    ({"status": "submitted"}, True),
    ({"status": "filled"}, True),
    ({"status": "open"}, True),
    ({"status": "accepted"}, True),
    ({"status": "recorded"}, False),   # dry-run sink — must NOT persist
    ({"status": "error"}, False),
    ({"status": "rejected"}, False),
    ({"success": True}, True),         # status absent, success flag
    ({"success": False}, False),
    ({}, False),
    (None, False),
    ("ok", False),
])
def test_submission_was_live(result, expected):
    assert submission_was_live(result) is expected


# ── prune helpers in apply_stream_gates context ──────────────────────────────


def test_prune_removes_entries_older_than_window():
    store = InMemoryStreamStateStore([
        _open("xli_cs", days_old=100, now=NOW),
        _open("xli_cs", days_old=2, now=NOW),
    ])
    removed = store.prune_older_than(7, now=NOW)
    assert removed == 1
    assert len(store.all_open()) == 1


# ── GateResult convenience ────────────────────────────────────────────────────


def test_block_reasons_grouped_by_stream():
    res = GateResult()
    res.blocked = [
        (_intent("xli_cs"), "cooldown"),
        (_intent("xli_cs"), "dup"),
        (_intent("qqq_cs", "QQQ"), "max"),
    ]
    grouped = res.block_reasons_by_stream
    assert sorted(grouped.keys()) == ["qqq_cs", "xli_cs"]
    assert grouped["xli_cs"] == ["cooldown", "dup"]
