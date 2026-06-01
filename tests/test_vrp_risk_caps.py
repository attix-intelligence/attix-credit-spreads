"""VRP-native portfolio risk caps — config parsing + cap-by-cap filtering."""
from __future__ import annotations

import pytest

from compass.live.vrp_contracts import OrderIntent, OrderLeg
from compass.live.vrp_risk_caps import (
    ExistingPosition,
    VRPRiskCaps,
    apply_caps,
)


def _intent(stream: str, ticker: str, expiration: str, est_max_loss: float = 1_000.0) -> OrderIntent:
    leg = OrderLeg(side="sell", sec_type="option", symbol=f"{ticker}260612P00100000",
                   qty=1, strike=100.0, expiration=expiration, right="P")
    return OrderIntent(
        stream=stream, symbol=ticker, structure="bull_put",
        legs=(leg,), contracts=1, est_max_loss=est_max_loss,
    )


# ── from_config ──────────────────────────────────────────────────────────────

def test_from_config_empty_is_inert():
    assert VRPRiskCaps.from_config({}).is_inert()
    assert VRPRiskCaps.from_config(None).is_inert()


def test_from_config_parses_all_three_caps():
    caps = VRPRiskCaps.from_config({
        "max_positions_per_ticker": 2,
        "max_same_expiration": 4,
        "max_aggregate_max_loss_pct": 0.30,
    })
    assert caps.max_positions_per_ticker == 2
    assert caps.max_same_expiration == 4
    assert caps.max_aggregate_max_loss_pct == 0.30
    assert not caps.is_inert()


def test_from_config_rejects_negative_position_cap():
    with pytest.raises(ValueError):
        VRPRiskCaps.from_config({"max_positions_per_ticker": -1})


@pytest.mark.parametrize("bad_pct", [-0.01, 1.01, 5.0])
def test_from_config_rejects_pct_outside_unit_interval(bad_pct):
    with pytest.raises(ValueError):
        VRPRiskCaps.from_config({"max_aggregate_max_loss_pct": bad_pct})


# ── apply_caps ───────────────────────────────────────────────────────────────

def test_inert_caps_pass_intents_through():
    intents = [_intent("xlf_cs", "XLF", "2026-06-12"),
               _intent("qqq_cs", "QQQ", "2026-06-12")]
    kept, dropped = apply_caps(intents, [], 100_000.0, VRPRiskCaps())
    assert kept == intents
    assert dropped == []


def test_max_positions_per_ticker_blocks_third_spy():
    caps = VRPRiskCaps(max_positions_per_ticker=2)
    intents = [_intent("a", "SPY", "2026-06-12"),
               _intent("b", "SPY", "2026-06-19"),
               _intent("c", "SPY", "2026-06-26")]  # 3rd SPY — should drop
    kept, dropped = apply_caps(intents, [], 100_000.0, caps)
    assert [i.stream for i in kept] == ["a", "b"]
    assert len(dropped) == 1
    assert "max_positions_per_ticker" in dropped[0]["reason"]
    assert "SPY" in dropped[0]["reason"]


def test_existing_positions_count_toward_per_ticker_cap():
    caps = VRPRiskCaps(max_positions_per_ticker=2)
    existing = [
        ExistingPosition(ticker="SPY", expiration="2026-06-05"),
        ExistingPosition(ticker="SPY", expiration="2026-06-12"),
    ]
    intents = [_intent("new", "SPY", "2026-06-19")]
    kept, dropped = apply_caps(intents, existing, 100_000.0, caps)
    assert kept == []
    assert len(dropped) == 1
    assert "max_positions_per_ticker" in dropped[0]["reason"]


def test_max_same_expiration_blocks_5th_on_same_date():
    caps = VRPRiskCaps(max_same_expiration=4)
    intents = [_intent(f"s{i}", t, "2026-06-12")
               for i, t in enumerate(["SPY", "QQQ", "XLF", "XLI", "IWM"])]
    kept, dropped = apply_caps(intents, [], 100_000.0, caps)
    assert len(kept) == 4
    assert len(dropped) == 1
    assert "max_same_expiration" in dropped[0]["reason"]
    assert "2026-06-12" in dropped[0]["reason"]


def test_max_aggregate_max_loss_pct_caps_total_risk():
    # equity 100k * 0.30 = 30k budget. Three intents at 12k each = 36k → only 2 fit.
    caps = VRPRiskCaps(max_aggregate_max_loss_pct=0.30)
    intents = [_intent(f"s{i}", t, f"2026-06-{12+i:02d}", est_max_loss=12_000.0)
               for i, t in enumerate(["SPY", "QQQ", "XLF"])]
    kept, dropped = apply_caps(intents, [], 100_000.0, caps)
    assert len(kept) == 2
    assert len(dropped) == 1
    assert "max_aggregate_max_loss_pct" in dropped[0]["reason"]


def test_aggregate_cap_includes_existing_open_max_loss():
    caps = VRPRiskCaps(max_aggregate_max_loss_pct=0.30)
    existing = [ExistingPosition(ticker="SPY", expiration="2026-06-05", est_max_loss=20_000.0)]
    intents = [_intent("new", "QQQ", "2026-06-12", est_max_loss=15_000.0)]  # 20k+15k > 30k
    kept, dropped = apply_caps(intents, existing, 100_000.0, caps)
    assert kept == []
    assert "max_aggregate_max_loss_pct" in dropped[0]["reason"]


def test_zero_equity_with_pct_cap_drops_all():
    caps = VRPRiskCaps(max_aggregate_max_loss_pct=0.30)
    intents = [_intent("a", "SPY", "2026-06-12")]
    kept, dropped = apply_caps(intents, [], 0.0, caps)
    assert kept == []
    assert "equity<=0" in dropped[0]["reason"]


def test_caps_compose_with_stable_arrival_order():
    """First-come-first-served — earlier intents are favored."""
    caps = VRPRiskCaps(max_positions_per_ticker=1, max_same_expiration=2)
    intents = [
        _intent("a", "SPY", "2026-06-12"),  # accepted
        _intent("b", "SPY", "2026-06-19"),  # blocked: per-ticker SPY=2 > 1
        _intent("c", "QQQ", "2026-06-12"),  # accepted (different ticker, same expiry now=2)
        _intent("d", "XLF", "2026-06-12"),  # blocked: same-expiration=3 > 2
    ]
    kept, dropped = apply_caps(intents, [], 100_000.0, caps)
    assert [i.stream for i in kept] == ["a", "c"]
    assert {d["stream"] for d in dropped} == {"b", "d"}
