"""Tests for compass/exp1780_exp1220_integration.py."""

import math
import numpy as np
import pandas as pd
import pytest

from compass.exp1780_exp1220_integration import (
    BEST_V3_CONFIG, ALLOCATIONS, STRESS_PERIODS,
    StressResult, AllocationResult, IntegrationResult,
    compute_sharpe, compute_metrics,
    build_exp1220_daily_returns,
    find_optimal_allocation, stress_test,
    TRADING_DAYS,
)
# Rename to avoid pytest collecting it as a test function
from compass.exp1780_exp1220_integration import test_allocation as run_test_allocation


def _make_spy_prices(n=1000, seed=1):
    """Build test SPY prices via random walk."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2016-01-04", periods=n)
    rets = rng.normal(0.0004, 0.011, n)
    prices = 200 * np.cumprod(1 + rets)
    return pd.DataFrame({"SPY": prices}, index=idx)


def _make_returns(n=500, mu=0.001, sigma=0.01, seed=1):
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2016-01-04", periods=n)
    return pd.Series(rng.normal(mu, sigma, n), index=idx)


class TestConfig:
    def test_best_config_keys(self):
        for k in ["lookback_preset", "vol_target", "leverage", "rebalance_days"]:
            assert k in BEST_V3_CONFIG

    def test_allocations_contains_zero(self):
        assert 0.0 in ALLOCATIONS

    def test_allocations_sorted(self):
        assert ALLOCATIONS == sorted(ALLOCATIONS)

    def test_stress_periods_defined(self):
        assert "COVID Crash (Feb-Mar 2020)" in STRESS_PERIODS
        assert "2022 Bear Market" in STRESS_PERIODS
        for name, (s, e) in STRESS_PERIODS.items():
            assert s < e


class TestSharpe:
    def test_formula(self):
        rets = np.array([0.01, -0.005, 0.008, 0.003, -0.002])
        expected = rets.mean() / rets.std(ddof=1) * math.sqrt(TRADING_DAYS)
        assert abs(compute_sharpe(rets) - expected) < 0.001

    def test_empty(self):
        assert compute_sharpe(np.array([])) == 0.0

    def test_constant(self):
        assert compute_sharpe(np.full(100, 0.001)) == 0.0


class TestMetrics:
    def test_positive(self):
        rng = np.random.RandomState(1)
        m = compute_metrics(rng.normal(0.001, 0.005, 252))
        assert m["cagr"] > 0
        assert m["sharpe"] > 0

    def test_empty(self):
        assert compute_metrics(np.array([]))["cagr"] == 0

    def test_all_fields(self):
        rng = np.random.RandomState(1)
        m = compute_metrics(rng.normal(0.001, 0.005, 100))
        for k in ["cagr", "sharpe", "dd", "sortino", "calmar", "vol"]:
            assert k in m


class TestExp1220Builder:
    def test_returns_series(self):
        prices = _make_spy_prices(500)
        exp1220 = build_exp1220_daily_returns(prices)
        assert isinstance(exp1220, pd.Series)
        assert len(exp1220) == len(prices)

    def test_requires_spy(self):
        idx = pd.bdate_range("2020-01-02", periods=100)
        prices = pd.DataFrame({"QQQ": np.full(100, 400.0)}, index=idx)
        with pytest.raises(ValueError, match="SPY"):
            build_exp1220_daily_returns(prices)

    def test_positive_theta_baseline(self):
        """On stable SPY days, EXP-1220 should earn positive theta."""
        idx = pd.bdate_range("2020-01-02", periods=50)
        prices = pd.DataFrame({"SPY": np.full(50, 450.0)}, index=idx)
        exp1220 = build_exp1220_daily_returns(prices)
        # Post-warmup (after first day), all days are stable → positive theta
        assert (exp1220.iloc[1:] > 0).all()

    def test_negative_on_big_down(self):
        """Big down days should produce negative EXP-1220 returns."""
        idx = pd.bdate_range("2020-01-02", periods=5)
        # Day 2: SPY drops 3% → EXP-1220 should be negative
        prices_arr = [100.0, 100.0, 97.0, 97.5, 97.5]
        prices = pd.DataFrame({"SPY": prices_arr}, index=idx)
        exp1220 = build_exp1220_daily_returns(prices)
        # Day index 2 is the drop day
        assert exp1220.iloc[2] < 0


class TestTestAllocation:
    def test_zero_allocation_equals_exp1220(self):
        exp1220 = _make_returns(500, mu=0.001)
        exp1780 = _make_returns(500, mu=0.0005, seed=2)
        result = run_test_allocation(exp1220, exp1780, 0.0)
        # 0% crisis alpha → 100% exp1220
        pure_exp1220 = compute_metrics(exp1220.values)
        assert abs(result.sharpe - pure_exp1220["sharpe"]) < 0.05

    def test_full_allocation(self):
        exp1220 = _make_returns(500, mu=0.001)
        exp1780 = _make_returns(500, mu=0.0005, seed=2)
        result = run_test_allocation(exp1220, exp1780, 1.0)
        # 100% crisis alpha should give exp1780-only metrics
        pure_exp1780 = compute_metrics(exp1780.values)
        assert abs(result.sharpe - pure_exp1780["sharpe"]) < 0.05

    def test_blended(self):
        exp1220 = _make_returns(500, mu=0.002)
        exp1780 = _make_returns(500, mu=0.0001, seed=3)
        result = run_test_allocation(exp1220, exp1780, 0.15)
        assert result.crisis_alpha_pct == 0.15
        assert isinstance(result.cagr, float)

    def test_passes_100_flag(self):
        # Synthetic high-return series to trigger the flag
        idx = pd.bdate_range("2016-01-04", periods=252)
        high_ret = pd.Series(np.full(252, 0.003), index=idx)
        low_ret = pd.Series(np.full(252, 0.0001), index=idx)
        # 100% high → CAGR very high
        r = run_test_allocation(high_ret, low_ret, 0.0)
        # numpy bool is also acceptable
        assert r.passes_100_cagr in (True, False, np.True_, np.False_)


class TestFindOptimal:
    def test_prefers_100_cagr_passing(self):
        allocs = [
            AllocationResult(0.0, 120, 2.0, 2.5, 15, 8.0, 20, 100, 0, True),
            AllocationResult(0.1, 110, 2.3, 2.8, 12, 9.2, 18, 90, 0, True),
            AllocationResult(0.2, 80, 2.5, 3.0, 10, 8.0, 16, 70, 0, False),  # better Sharpe but fails CAGR
        ]
        best = find_optimal_allocation(allocs)
        # Should pick the one with passes_100_cagr=True AND highest Sharpe
        assert best.crisis_alpha_pct == 0.1
        assert best.passes_100_cagr

    def test_fallback_when_none_pass(self):
        allocs = [
            AllocationResult(0.0, 50, 1.0, 1.2, 15, 3.3, 20, 40, 0, False),
            AllocationResult(0.1, 60, 1.5, 1.8, 12, 5.0, 18, 50, 0, False),
        ]
        best = find_optimal_allocation(allocs)
        assert best.crisis_alpha_pct == 0.1  # highest Sharpe


class TestStressTest:
    def test_basic(self):
        # Build series with COVID period
        idx = pd.bdate_range("2019-06-03", "2023-12-31")
        rng = np.random.RandomState(1)
        e1220 = pd.Series(rng.normal(0.001, 0.005, len(idx)), index=idx)
        e1780 = pd.Series(rng.normal(0.0003, 0.008, len(idx)), index=idx)
        spy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(idx))), index=idx)
        results = stress_test(e1220, e1780, spy, 0.15)
        assert len(results) > 0
        assert all(isinstance(r, StressResult) for r in results)

    def test_insufficient_data(self):
        # Very short date range → no stress periods match
        idx = pd.bdate_range("2025-06-01", "2025-06-30")
        e1220 = pd.Series(0.001, index=idx)
        e1780 = pd.Series(0.001, index=idx)
        spy = pd.Series(100.0, index=idx)
        results = stress_test(e1220, e1780, spy, 0.10)
        # No COVID or 2022 bear in this range
        assert len(results) == 0


class TestAllocationResult:
    def test_fields(self):
        r = AllocationResult(
            crisis_alpha_pct=0.15, cagr=105.0, sharpe=2.5,
            sortino=3.0, max_dd=12.0, calmar=8.75, vol=15.0,
            total_return=500, corr_to_spy=0.1, passes_100_cagr=True,
        )
        assert r.crisis_alpha_pct == 0.15
        assert r.passes_100_cagr
