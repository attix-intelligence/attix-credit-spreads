"""Tests for compass.live.vrp_runner — PR-E cutover wiring (EXP-V8A).

No network/Alpaca: the cc4 ladder is a fake signal fn, the data feed is the
in-memory FakeFeed, and the Alpaca provider is a recording fake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from compass.live.vrp_runner import (
    Cc4VixExposure,
    build_vrp_strategy,
    run_vrp_cycle,
    vrp_enabled,
)
from compass.live.vrp_strategy import VRPMultiStreamStrategy
from compass.live.vrp_stream_gates import InMemoryStreamStateStore, OpenSpread
from tests.vrp_fixtures import FakeFeed, FixedVixExposure, make_snapshot


class _FakeProvider:
    """Records submit_credit_spread; serves a configurable account equity."""

    def __init__(self, equity=100_000.0, raise_account=False):
        self._equity = equity
        self._raise = raise_account
        self.calls = []

    def get_account(self):
        if self._raise:
            raise RuntimeError("alpaca down")
        return {"equity": self._equity}

    def submit_credit_spread(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "submitted", "order_id": f"mock-{len(self.calls)}"}


def _system(config, provider):
    return SimpleNamespace(config=config, alpaca_provider=provider)


def _prebuilt_strategy(vix_mult=1.0, equity=100_000.0):
    return VRPMultiStreamStrategy(
        FakeFeed(make_snapshot(vix=18.0)),
        account_equity=equity,
        vix_provider=FixedVixExposure(vix_mult),
    )


# ── Cc4VixExposure adapter ────────────────────────────────────────────────────

def test_cc4_adapter_returns_sizing_multiplier():
    adapter = Cc4VixExposure(signal_fn=lambda: {"entry_gate": True, "sizing_multiplier": 0.75})
    assert adapter.current_exposure_multiplier() == pytest.approx(0.75)


def test_cc4_adapter_halts_when_entry_gate_false():
    # CB-style block (VIX>=35) overrides the soft multiplier (CB > ladder).
    adapter = Cc4VixExposure(signal_fn=lambda: {"entry_gate": False, "sizing_multiplier": 0.6})
    assert adapter.current_exposure_multiplier() == 0.0


def test_cc4_adapter_fails_flat_on_exception():
    def boom():
        raise RuntimeError("vix feed dead")
    assert Cc4VixExposure(signal_fn=boom).current_exposure_multiplier() == 0.0


def test_cc4_adapter_missing_multiplier_is_zero():
    adapter = Cc4VixExposure(signal_fn=lambda: {"entry_gate": True})
    assert adapter.current_exposure_multiplier() == 0.0


# ── vrp_enabled guard (must be false/absent for every non-VRP experiment) ─────

def test_vrp_enabled_absent_is_false():
    assert vrp_enabled({}) is False
    assert vrp_enabled({"strategy": {}}) is False


def test_vrp_enabled_explicit():
    assert vrp_enabled({"vrp_engine": {"enabled": False}}) is False
    assert vrp_enabled({"vrp_engine": {"enabled": True}}) is True


# ── build_vrp_strategy ────────────────────────────────────────────────────────

def test_build_strategy_reads_live_equity_and_allocates():
    provider = _FakeProvider(equity=80_000.0)
    strat = build_vrp_strategy(
        {"vrp_engine": {"vol_target": 0.12}}, provider,
        data_feed=FakeFeed(make_snapshot(vix=18.0)), vix_provider=FixedVixExposure(1.0),
    )
    plan = strat.plan_cycle()
    assert sum(plan.capital.values()) == pytest.approx(80_000.0, rel=0.02)


def test_build_strategy_equity_failure_yields_no_allocation():
    provider = _FakeProvider(raise_account=True)
    strat = build_vrp_strategy(
        {"vrp_engine": {}}, provider,
        data_feed=FakeFeed(make_snapshot(vix=18.0)), vix_provider=FixedVixExposure(1.0),
    )
    plan = strat.plan_cycle()
    assert plan.capital == {}
    assert plan.intents == []


# ── run_vrp_cycle ─────────────────────────────────────────────────────────────

def test_run_cycle_dry_run_places_no_orders():
    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": True}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    assert len(plan.intents) > 0           # intents PLANNED
    assert provider.calls == []            # but NOTHING placed


def test_run_cycle_live_submits_each_intent():
    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": False}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    assert len(provider.calls) == len(plan.intents) > 0
    assert all(c["spread_type"] == "bull_put" for c in provider.calls)


def test_run_cycle_dry_run_when_no_provider():
    # No alpaca provider → forced dry-run even if config says live.
    system = _system({"vrp_engine": {"dry_run": False}}, None)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    assert len(plan.intents) > 0


def test_run_cycle_reports_blocked_futures_streams():
    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": True}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    assert plan.stream_status["gld_cal"].startswith("blocked")
    assert plan.stream_status["slv_cal"].startswith("blocked")


# ── SINK_TYPE feature flag ───────────────────────────────────────────────────

def test_run_cycle_executor_sink_routes_intents_via_rest(monkeypatch):
    """SINK_TYPE=executor + EXECUTOR_* env → intents POSTed to /v1/orders/spread,
    NOT through the Alpaca provider (so the existing live worker is untouched
    unless this experiment explicitly opts in)."""
    from tests.test_executor_order_sink import FakeHttp

    # Programmable executor responses: a balance query, then N spread submits.
    http = FakeHttp(queue=[
        (200, {  # GET /v1/portfolio/balance for equity sizing
            "total_equity": 250_000.0, "cash": 200_000.0,
            "buying_power": 800_000.0, "unrealized_pnl": 0.0,
            "realized_pnl_today": 0.0, "positions_count": 0,
        }),
    ] + [(200, {  # one OrderResponse per intent the strategy emits
        "success": True, "order_id": f"exec-{i}", "broker_order_id": f"bk-{i}",
        "message": "submitted", "status": "open", "symbol": "SPY",
        "quantity": 1, "timestamp": "2026-05-30T20:00:00Z",
    }) for i in range(16)])

    monkeypatch.setenv("SINK_TYPE", "executor")
    monkeypatch.setenv("EXECUTOR_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTOR_ACCOUNT_ID", "ibkr_paper")
    monkeypatch.setenv("EXECUTOR_BASE_URL", "http://exec.local")

    # Patch ExecutorOrderSink.from_env to inject our FakeHttp.
    import compass.live.executor_order_sink as eos
    real_from_env = eos.ExecutorOrderSink.from_env
    monkeypatch.setattr(
        eos.ExecutorOrderSink, "from_env",
        classmethod(lambda cls, **kw: real_from_env(http=http)),
    )

    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": False}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())

    assert len(plan.intents) > 0
    # Alpaca path UNTOUCHED — every submit went through the executor.
    assert provider.calls == []
    # First HTTP call was balance (equity source); rest are POST /spread.
    posts = [c for c in http.calls if c["method"] == "POST"]
    assert len(posts) == len(plan.intents)
    for p in posts:
        assert p["url"].endswith("/v1/orders/spread")
        assert p["json"]["account_id"] == "ibkr_paper"
        assert p["json"]["account_type"] == "paper"


def test_run_cycle_unknown_sink_type_falls_back_to_alpaca(monkeypatch):
    monkeypatch.setenv("SINK_TYPE", "totally-bogus")
    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": False}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    assert len(provider.calls) == len(plan.intents) > 0


def test_run_cycle_executor_missing_creds_forces_dry_run(monkeypatch):
    monkeypatch.setenv("SINK_TYPE", "executor")
    monkeypatch.delenv("EXECUTOR_API_KEY", raising=False)
    monkeypatch.delenv("EXECUTOR_ACCOUNT_ID", raising=False)
    provider = _FakeProvider()
    system = _system({"vrp_engine": {"dry_run": False}}, provider)
    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=InMemoryStreamStateStore())
    # Sink unavailable → degrade to dry-run, never crash the cycle.
    assert provider.calls == []
    assert len(plan.intents) >= 0


# ── stream gates: cooldown + dup-expiration + max-open ───────────────────────


def _v8a_config(*, dry_run=False, **gate_overrides):
    """A V8A-shaped config with the gates block populated for the test."""
    gates = {
        "enabled": True,
        "cooldown_days": 7,
        "max_open_per_stream": 1,
        "deduplicate_expirations": True,
    }
    gates.update(gate_overrides)
    return {"experiment_id": "EXP-V8A-TEST",
            "vrp_engine": {"dry_run": dry_run, "stream_gates": gates}}


def _open_for_intent(intent, *, days_old=0.0):
    """Build an OpenSpread that matches an intent's stream/expiration so the
    gates can be exercised deterministically without inspecting strategy output.
    """
    exp_leg = next((leg for leg in intent.legs if leg.expiration), None)
    assert exp_leg is not None, "fixture intent missing expiration"
    return OpenSpread(
        stream_id=intent.stream,
        opened_at=datetime.now(timezone.utc) - timedelta(days=days_old),
        expiration=datetime.strptime(exp_leg.expiration, "%Y-%m-%d").date(),
        contracts=int(intent.contracts),
        client_order_id="prior-test",
    )


def test_run_cycle_gates_block_max_open_per_stream():
    """One prior open spread per stream + cap=1 → every new intent blocked.

    Seed at days_old=1.0 (well within the 7-day cooldown window) so the runner's
    pre-gate prune doesn't sweep the entries away before the gate evaluates.
    """
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=False), provider)

    # Seed one prior open spread for every stream the planner will hit.
    planner = _prebuilt_strategy()
    dry_plan = planner.plan_cycle()
    assert len(dry_plan.intents) > 0
    store = InMemoryStreamStateStore([_open_for_intent(i, days_old=1.0) for i in dry_plan.intents])

    plan = run_vrp_cycle(system, strategy=planner, state_store=store)

    assert plan.intents == []                    # all gated out
    assert provider.calls == []                  # nothing placed at the broker
    assert any("gate_blocked" in s for s in plan.stream_status.values())


def test_run_cycle_gates_block_duplicate_expiration():
    """Prior open spread with same expiration AND high max_open → only the dup
    gate can fire (eval order is max_open → dup → cooldown)."""
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=False, max_open_per_stream=10), provider)

    planner = _prebuilt_strategy()
    dry_plan = planner.plan_cycle()
    # days_old=1.0 survives the 7-day prune; same expiration triggers dup gate.
    store = InMemoryStreamStateStore([_open_for_intent(i, days_old=1.0) for i in dry_plan.intents])

    plan = run_vrp_cycle(system, strategy=planner, state_store=store)

    assert plan.intents == []
    assert provider.calls == []
    assert any("duplicate expiration" in s for s in plan.stream_status.values())


def test_run_cycle_gates_block_cooldown_only():
    """Prior open spread with different expiration but recent → only the cooldown
    gate fires (dup gate doesn't apply because expirations differ)."""
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=False, max_open_per_stream=10), provider)

    planner = _prebuilt_strategy()
    dry_plan = planner.plan_cycle()
    # Forge an unrelated expiration so the dup gate doesn't catch.
    forged = []
    for intent in dry_plan.intents:
        e = _open_for_intent(intent, days_old=2.0)
        forged.append(OpenSpread(
            stream_id=e.stream_id,
            opened_at=e.opened_at,
            expiration=e.expiration.replace(year=2099),
            contracts=e.contracts,
            client_order_id=e.client_order_id,
        ))
    store = InMemoryStreamStateStore(forged)

    plan = run_vrp_cycle(system, strategy=planner, state_store=store)

    assert plan.intents == []
    assert provider.calls == []
    assert any("cooldown_days=7" in s for s in plan.stream_status.values())


def test_run_cycle_gates_disabled_lets_everything_through():
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=False, enabled=False), provider)

    planner = _prebuilt_strategy()
    dry_plan = planner.plan_cycle()
    # Even with state that would otherwise block, gates are OFF.
    store = InMemoryStreamStateStore([_open_for_intent(i, days_old=0.1) for i in dry_plan.intents])

    plan = run_vrp_cycle(system, strategy=planner, state_store=store)

    assert len(provider.calls) == len(dry_plan.intents)
    assert len(plan.intents) == len(dry_plan.intents)


def test_run_cycle_records_successful_live_submission_to_state_store():
    """A live cycle with no prior state → all intents submitted AND state recorded."""
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=False), provider)
    store = InMemoryStreamStateStore()

    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=store)

    assert len(provider.calls) == len(plan.intents) > 0
    # Each successful submission produced exactly one state row.
    assert len(store.all_open()) == len(plan.intents)
    # The state's stream ids align with the kept intents.
    assert sorted(e.stream_id for e in store.all_open()) == sorted(i.stream for i in plan.intents)


def test_run_cycle_dry_run_does_not_pollute_state_store():
    """A dry-run cycle plans + gates as usual but MUST NOT touch the live state."""
    provider = _FakeProvider()
    system = _system(_v8a_config(dry_run=True), provider)
    store = InMemoryStreamStateStore()

    plan = run_vrp_cycle(system, strategy=_prebuilt_strategy(), state_store=store)

    assert len(plan.intents) > 0           # planned & kept
    assert provider.calls == []            # nothing placed
    assert store.all_open() == []          # state untouched
