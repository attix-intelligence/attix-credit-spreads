"""Tests for compass/crisis_alpha_v5.py."""

import math
import numpy as np
import pandas as pd
import pytest

from compass.crisis_alpha_v5 import (
    SAFE_HAVENS, EQUITIES, HedgeConfigV5, LeveragedHedgeTest,
    compute_v5_weights, stress_gate, backtest_v5,
    find_dd_periods, score_hedge,
    select_best_hedge,
)
# Renamed import — pytest would otherwise collect test_leveraged_hedge as a test
from compass.crisis_alpha_v5 import test_leveraged_hedge as run_lev_test
from compass.crisis_alpha_v4 import UNIVERSE_V4


def _det_prices(n=1500, seed=1):
    """Deterministic test fixture for screener mechanics ONLY."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2018-01-02", periods=n)
    data = {}
    for i, tk in enumerate(UNIVERSE_V4):
        drift = 0.0002 + (i - len(UNIVERSE_V4) / 2) * 0.00006
        rets = rng.normal(drift, 0.011, n)
        data[tk] = 100 * np.cumprod(1 + rets)
    return pd.DataFrame(data, index=idx)


class TestUniverse:
    def test_safe_havens_size(self):
        assert "TLT" in SAFE_HAVENS
        assert "GLD" in SAFE_HAVENS
        assert "UUP" in SAFE_HAVENS

    def test_equities_excludes_bonds(self):
        for t in EQUITIES:
            assert t not in SAFE_HAVENS


class TestStressGate:
    def test_no_stress_returns_zero(self):
        # Monotonic up — no DD, gate stays 0
        idx = pd.bdate_range("2020-01-02", periods=200)
        prices = pd.Series(np.linspace(100, 200, 200), index=idx)
        gate = stress_gate(prices, threshold=0.05, lookback=60)
        assert gate.sum() == 0

    def test_drawdown_opens_gate(self):
        # Build a series with a clear drawdown
        idx = pd.bdate_range("2020-01-02", periods=200)
        prices = np.concatenate([
            np.linspace(100, 110, 100),  # uptrend
            np.linspace(110, 95, 100),    # 14% drawdown
        ])
        s = pd.Series(prices, index=idx)
        gate = stress_gate(s, threshold=0.05, lookback=60)
        # Late-period days should have gate = 1
        assert gate.iloc[-10:].sum() > 0

    def test_no_lookahead(self):
        # Gate is shifted by 1 — first day must always be 0
        idx = pd.bdate_range("2020-01-02", periods=100)
        prices = pd.Series(np.linspace(100, 50, 100), index=idx)
        gate = stress_gate(prices, threshold=0.05, lookback=20)
        assert gate.iloc[0] == 0.0


class TestFindDdPeriods:
    def test_identifies_dd(self):
        idx = pd.bdate_range("2020-01-02", periods=100)
        # 50 up days then 50 down days
        rets = pd.Series(np.concatenate([np.full(50, 0.01), np.full(50, -0.005)]), index=idx)
        in_dd = find_dd_periods(rets, dd_threshold=0.03)
        # Late days should be in DD
        assert in_dd.iloc[-1]
        # Early days should not
        assert not in_dd.iloc[10]

    def test_no_dd_returns_all_false(self):
        idx = pd.bdate_range("2020-01-02", periods=50)
        rets = pd.Series(0.001, index=idx)
        in_dd = find_dd_periods(rets, dd_threshold=0.03)
        assert not in_dd.any()


class TestHedgeScore:
    def test_perfect_negative_corr(self):
        idx = pd.bdate_range("2020-01-02", periods=300)
        e = pd.Series(np.linspace(0.01, -0.01, 300), index=idx)
        h = -e   # perfect negative
        s = score_hedge(h, e)
        assert s["corr_full"] < -0.9

    def test_zero_variance_safe(self):
        idx = pd.bdate_range("2020-01-02", periods=100)
        e = pd.Series(0.001, index=idx)
        h = pd.Series(0.0, index=idx)
        s = score_hedge(h, e)
        # Both constant — should not crash
        assert "corr_full" in s

    def test_downside_capture_positive(self):
        # Hedge that makes money exactly when EXP-1220 loses
        idx = pd.bdate_range("2020-01-02", periods=200)
        rng = np.random.RandomState(1)
        e_arr = rng.normal(0.001, 0.005, 200)
        h_arr = -e_arr * 0.5   # perfectly negatively correlated
        e = pd.Series(e_arr, index=idx)
        h = pd.Series(h_arr, index=idx)
        s = score_hedge(h, e)
        assert s["downside_capture"] > 0


class TestComputeWeights:
    def test_equity_short_only_zeroes_longs(self):
        prices = _det_prices(800)
        n = len(prices)
        # Build a constant POSITIVE signal for SPY (would normally be long)
        signal = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        signal["SPY"] = 0.5
        cfg = HedgeConfigV5(
            name="t", lookback_preset="v2_round", vol_target=0.05, leverage=1.0,
            dd_brake_threshold=0.05, dd_brake_zone=0.03, max_weight=0.20,
            require_confirmation=False, stress_threshold=0.0, stress_lookback=60,
            safe_haven_boost=1.0, equity_short_only=True,
        )
        w = compute_v5_weights(prices, signal, cfg)
        # SPY should have no positive positions
        assert (w["SPY"] <= 0).all()

    def test_safe_haven_boost(self):
        prices = _det_prices(800)
        signal = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        signal["TLT"] = 0.1
        cfg_boost1 = HedgeConfigV5(
            name="t", lookback_preset="v2_round", vol_target=0.05, leverage=1.0,
            dd_brake_threshold=0.05, dd_brake_zone=0.03, max_weight=0.20,
            require_confirmation=False, stress_threshold=0.0, stress_lookback=60,
            safe_haven_boost=1.0, equity_short_only=False,
        )
        cfg_boost2 = HedgeConfigV5(**{**cfg_boost1.__dict__, "name": "u",
                                      "safe_haven_boost": 2.0})
        w1 = compute_v5_weights(prices, signal, cfg_boost1)
        w2 = compute_v5_weights(prices, signal, cfg_boost2)
        # The boosted version should have ≥ as much TLT exposure on average
        assert w2["TLT"].abs().mean() >= w1["TLT"].abs().mean() - 1e-9


class TestBacktestV5:
    def test_runs(self):
        prices = _det_prices(1500)
        cfg = HedgeConfigV5(
            name="t", lookback_preset="v2_round", vol_target=0.05, leverage=1.0,
            dd_brake_threshold=0.05, dd_brake_zone=0.03, max_weight=0.20,
            require_confirmation=False, stress_threshold=0.0, stress_lookback=60,
            safe_haven_boost=1.5, equity_short_only=False,
        )
        r = backtest_v5(prices, cfg)
        assert r.daily_returns is not None
        assert r.n_days > 0

    def test_stress_gate_reduces_exposure(self):
        prices = _det_prices(1500, seed=2)
        cfg_no_gate = HedgeConfigV5(
            name="t", lookback_preset="v2_round", vol_target=0.05, leverage=1.0,
            dd_brake_threshold=0.05, dd_brake_zone=0.03, max_weight=0.20,
            require_confirmation=False, stress_threshold=0.0, stress_lookback=60,
            safe_haven_boost=1.0, equity_short_only=False,
        )
        cfg_with_gate = HedgeConfigV5(**{**cfg_no_gate.__dict__, "name": "u",
                                         "stress_threshold": 0.10})
        r_no = backtest_v5(prices, cfg_no_gate)
        r_with = backtest_v5(prices, cfg_with_gate)
        # Gated version should have ≤ as much realized vol
        assert r_with.vol <= r_no.vol + 0.01


class TestLeveragedHedgeTest:
    def test_zero_pct_gives_pure_leveraged(self):
        idx = pd.bdate_range("2020-01-02", periods=300)
        e = pd.Series(0.001, index=idx)
        h = pd.Series(-0.001, index=idx)
        t = run_lev_test(e, h, leverage=2.0, crisis_pct=0.0)
        # Pure 2× → CAGR is ~2× the underlying
        assert t.cagr > 0   # leveraged positive series

    def test_full_hedge_gives_pure_hedge(self):
        idx = pd.bdate_range("2020-01-02", periods=300)
        e = pd.Series(0.001, index=idx)
        h = pd.Series(-0.001, index=idx)
        t = run_lev_test(e, h, leverage=2.0, crisis_pct=1.0)
        assert t.cagr < 0


class TestSelectBest:
    def test_picks_lowest_score(self):
        configs = [
            HedgeConfigV5(name="a", lookback_preset="v2_round", vol_target=0.05,
                          leverage=1.0, dd_brake_threshold=0.05, dd_brake_zone=0.03,
                          max_weight=0.2, require_confirmation=False,
                          stress_threshold=0.0, stress_lookback=60,
                          safe_haven_boost=1.0, equity_short_only=False,
                          hedge_score=0.5, vol=5.0),
            HedgeConfigV5(name="b", lookback_preset="v2_round", vol_target=0.05,
                          leverage=1.0, dd_brake_threshold=0.05, dd_brake_zone=0.03,
                          max_weight=0.2, require_confirmation=False,
                          stress_threshold=0.0, stress_lookback=60,
                          safe_haven_boost=1.0, equity_short_only=False,
                          hedge_score=-0.3, vol=5.0),
            HedgeConfigV5(name="c", lookback_preset="v2_round", vol_target=0.05,
                          leverage=1.0, dd_brake_threshold=0.05, dd_brake_zone=0.03,
                          max_weight=0.2, require_confirmation=False,
                          stress_threshold=0.0, stress_lookback=60,
                          safe_haven_boost=1.0, equity_short_only=False,
                          hedge_score=-1.0, vol=0.5),  # ineligible (vol too low)
        ]
        best = select_best_hedge(configs)
        assert best.name == "b"  # lowest among vol > 1.0
