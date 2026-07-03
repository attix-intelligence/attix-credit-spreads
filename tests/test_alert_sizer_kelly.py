"""WS-1 tests: AlertPositionSizer Kelly routing (_kelly_size).

Covers: kelly-block precedence over flat/portfolio sizing, regime mapping,
DB-path resolution via ATTIX_DB_PATH, zero-equity not clobbering persisted
state, tier-3 halt skips, and the weekly_loss_breach 0.5× haircut.
"""
from __future__ import annotations

import pytest

from alerts.alert_position_sizer import AlertPositionSizer
from alerts.alert_schema import Alert, AlertType, Direction, Leg
from shared.kelly_sizing import KELLY_DEFAULTS, KellyStateDB

CB_CFG = KELLY_DEFAULTS["circuit_breakers"]


def _kelly_config(db_path=None, account_size=133_800.0, max_contracts=30):
    cfg = {
        "risk": {"account_size": account_size, "max_contracts": max_contracts},
        "kelly": {
            "regime_fractions": {"bull": 9.0, "neutral": 7.0, "bear": 4.0},
            "sizing_base": "current_equity",
            "circuit_breakers": dict(CB_CFG),
        },
    }
    if db_path is not None:
        cfg["db_path"] = str(db_path)
    return cfg


def _bull_put_alert(credit=1.75, short=630.0, long=618.0):
    return Alert(
        type=AlertType.credit_spread,
        ticker="SPY",
        direction=Direction.bullish,
        legs=[
            Leg(strike=short, option_type="put", action="sell", expiration="2026-07-17"),
            Leg(strike=long, option_type="put", action="buy", expiration="2026-07-17"),
        ],
        entry_price=credit,
        stop_loss=credit * 2.25,
        profit_target=credit * 0.45,
        risk_pct=0.02,
    )


def _bear_call_alert(credit=1.75):
    return Alert(
        type=AlertType.credit_spread,
        ticker="SPY",
        direction=Direction.bearish,
        legs=[
            Leg(strike=650.0, option_type="call", action="sell", expiration="2026-07-17"),
            Leg(strike=662.0, option_type="call", action="buy", expiration="2026-07-17"),
        ],
        entry_price=credit,
        stop_loss=credit * 2.25,
        profit_target=credit * 0.45,
        risk_pct=0.02,
    )


def _iron_condor_alert(credit=3.20):
    return Alert(
        type=AlertType.iron_condor,
        ticker="SPY",
        direction=Direction.neutral,
        legs=[
            Leg(strike=630.0, option_type="put", action="sell", expiration="2026-07-17"),
            Leg(strike=618.0, option_type="put", action="buy", expiration="2026-07-17"),
            Leg(strike=650.0, option_type="call", action="sell", expiration="2026-07-17"),
            Leg(strike=662.0, option_type="call", action="buy", expiration="2026-07-17"),
        ],
        entry_price=credit,
        stop_loss=credit * 2.25,
        profit_target=credit * 0.45,
        risk_pct=0.02,
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "exp800.db"


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_kelly_block_takes_precedence(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    result = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    # bull 9%: 12,042 ÷ ((12−1.75)×100) → 11 contracts
    assert result.contracts == 11
    assert result.dollar_risk == pytest.approx(11 * 1025.0)
    assert result.max_loss == result.dollar_risk


def test_no_kelly_block_uses_flat(db_path, monkeypatch):
    cfg = _kelly_config(db_path)
    del cfg["kelly"]
    sizer = AlertPositionSizer(cfg)
    called = {}
    monkeypatch.setattr(
        sizer, "_flat_risk_size",
        lambda *a, **k: called.setdefault("flat", True) or None,
    )
    sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    assert called.get("flat")


def test_empty_regime_fractions_does_not_route_to_kelly(db_path, monkeypatch):
    cfg = _kelly_config(db_path)
    cfg["kelly"]["regime_fractions"] = {}
    sizer = AlertPositionSizer(cfg)
    called = {}
    monkeypatch.setattr(
        sizer, "_flat_risk_size",
        lambda *a, **k: called.setdefault("flat", True) or None,
    )
    sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    assert called.get("flat")


# ---------------------------------------------------------------------------
# Regime mapping
# ---------------------------------------------------------------------------

def test_regime_mapping():
    assert AlertPositionSizer._regime_for_alert(_bull_put_alert()) == "bull"
    assert AlertPositionSizer._regime_for_alert(_bear_call_alert()) == "bear"
    assert AlertPositionSizer._regime_for_alert(_iron_condor_alert()) == "neutral"


def test_regime_fractions_flow_into_contracts(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    equity = 133_800.0
    bull = sizer.size(_bull_put_alert(), equity, 50.0, 0.0)      # 9% → 11
    bear = sizer.size(_bear_call_alert(), equity, 50.0, 0.0)     # 4% → 5
    condor = sizer.size(_iron_condor_alert(), equity, 50.0, 0.0)  # 7%, wing 12, credit 3.20
    assert bull.contracts == 11
    assert bear.contracts == 5
    # neutral 7%: 9,366 ÷ ((12−3.20)×100 = 880) → 10
    assert condor.contracts == 10
    # IC uses plain one-wing max loss, not the (2*width − credit) engine convention
    assert condor.dollar_risk == pytest.approx(10 * 880.0)


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def test_missing_db_path_refuses_to_size(monkeypatch):
    monkeypatch.delenv("ATTIX_DB_PATH", raising=False)
    sizer = AlertPositionSizer(_kelly_config(db_path=None))
    result = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    assert result.contracts == 0
    assert result.dollar_risk == 0.0


def test_env_db_path_used(monkeypatch, tmp_path):
    env_db = tmp_path / "env_exp.db"
    monkeypatch.setenv("ATTIX_DB_PATH", str(env_db))
    sizer = AlertPositionSizer(_kelly_config(db_path=None))
    result = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    assert result.contracts == 11
    assert env_db.exists()


# ---------------------------------------------------------------------------
# Equity feed behavior
# ---------------------------------------------------------------------------

def test_zero_equity_does_not_clobber_state(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    sizer.size(_bull_put_alert(), 150_000.0, 50.0, 0.0)  # sets HWM/equity 150k

    # account_value=0 must not overwrite persisted equity
    result = sizer.size(_bull_put_alert(), 0.0, 50.0, 0.0)
    state = KellyStateDB(db_path, 133_800.0).load()
    assert state["current_equity"] == 150_000.0
    assert state["hwm"] == 150_000.0
    # sized off persisted 150k: 13,500 ÷ 1025 → 13
    assert result.contracts == 13


def test_live_equity_updates_sizing(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    r1 = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    r2 = sizer.size(_bull_put_alert(), 200_000.0, 50.0, 0.0)
    assert r1.contracts == 11
    # 200k × 9% = 18,000 ÷ 1025 → 17
    assert r2.contracts == 17


# ---------------------------------------------------------------------------
# Circuit breakers through the sizer
# ---------------------------------------------------------------------------

def test_tier3_halt_skips_trade(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)          # HWM 133.8k
    result = sizer.size(_bull_put_alert(), 117_000.0, 50.0, 0.0)  # -12.56% → tier 3
    assert result.contracts == 0
    assert result.risk_pct == 0.0


def test_tier1_halves_fraction(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    result = sizer.size(_bull_put_alert(), 122_000.0, 50.0, 0.0)  # -8.82% → tier 1
    # 4.5% of 122k = 5,490 ÷ 1025 → 5
    assert result.contracts == 5


def test_tier2_min_fraction_floor(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    result = sizer.size(_bull_put_alert(), 119_500.0, 50.0, 0.0)  # -10.69% → tier 2
    # 2% of 119.5k = 2,390 ÷ 1025 → 2
    assert result.contracts == 2


def test_weekly_loss_breach_halves(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path))
    full = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    halved = sizer.size(
        _bull_put_alert(), 133_800.0, 50.0, 0.0, weekly_loss_breach=True
    )
    assert full.contracts == 11
    # 4.5% of 133.8k = 6,021 ÷ 1025 → 5
    assert halved.contracts == 5


def test_max_contracts_cap(db_path):
    sizer = AlertPositionSizer(_kelly_config(db_path, max_contracts=3))
    result = sizer.size(_bull_put_alert(), 133_800.0, 50.0, 0.0)
    assert result.contracts == 3
