"""
tests/test_fill_model.py — FIX #3: honest entry fills (fill_model naive|marketable).

marketable: an entry limit priced at the scan bar's OPEN spread mark (minus the
flat config slippage, like the live strategy) only fills if the market traded
at/through it by the bar CLOSE — otherwise fill-or-cancel, no fill that bar.
naive: legacy instant fill at bar close minus bar-range slippage (default,
preserves historical results).

Uses a stub data provider — no Polygon required.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backtest.backtester import Backtester  # noqa: E402


class StubHistoricalData:
    """Returns one controlled intraday (and optionally daily) price dict."""

    def __init__(self, intraday=None, daily=None):
        self._intraday = intraday
        self._daily = daily

    def get_available_strikes(self, ticker, exp_str, date_str, option_type="P"):
        return [460.0, 465.0, 470.0, 475.0, 480.0, 485.0, 490.0]

    def get_intraday_spread_prices(self, *args, **kwargs):
        return dict(self._intraday) if self._intraday is not None else None

    def get_spread_prices(self, *args, **kwargs):
        return dict(self._daily) if self._daily is not None else None


def _make_config(fill_model=None) -> dict:
    cfg = {
        "strategy": {
            "target_dte": 15,
            "min_dte": 15,
            "spread_width": 5,
            "min_credit_pct": 8,
            "direction": "bull_put",
            "trend_ma_period": 200,
            "iron_condor": {"enabled": False},
        },
        "risk": {
            "stop_loss_multiplier": 1.25,
            "profit_target": 55,
            "max_risk_per_trade": 5.0,
            "max_contracts": 10,
            "max_positions": 20,
            "drawdown_cb_pct": 55,
        },
        "backtest": {
            "starting_capital": 100_000,
            "commission_per_contract": 0.65,
            "slippage": 0.05,
            "exit_slippage": 0.10,
            "compound": False,
            "sizing_mode": "flat",
        },
    }
    if fill_model is not None:
        cfg["backtest"]["fill_model"] = fill_model
    return cfg


def _find_spread(bt: Backtester, scan_hour=10, scan_minute=30):
    """Call _find_real_spread at an ET scan time (SPY @ 500, 3% OTM puts)."""
    bt.capital = bt.starting_capital
    return bt._find_real_spread(
        "SPY", datetime(2026, 3, 10), "2026-03-10", 500.0,
        datetime(2026, 3, 27), spread_width=5, option_type="P",
        scan_hour=scan_hour, scan_minute=scan_minute,
    )


def _bt(fill_model, hist):
    return Backtester(_make_config(fill_model), historical_data=hist, otm_pct=0.03)


# Bar where the spread opened rich and traded down: a limit priced off the open
# (1.50 - 0.05 slippage = 1.45) was never marketable (close credit 1.20).
UNMARKETABLE_BAR = {
    "short_close": 2.00, "long_close": 0.80, "spread_value": 1.20, "slippage": 0.10,
    "short_open": 2.40, "long_open": 0.90, "spread_open": 1.50,
}

# Bar where the spread opened at 1.00: limit 0.95 <= close credit 1.20 → fills.
MARKETABLE_BAR = {
    "short_close": 2.00, "long_close": 0.80, "spread_value": 1.20, "slippage": 0.10,
    "short_open": 1.70, "long_open": 0.70, "spread_open": 1.00,
}


class TestMarketableFillModel:
    def test_limit_above_market_no_fill(self):
        bt = _bt("marketable", StubHistoricalData(intraday=UNMARKETABLE_BAR))
        assert _find_spread(bt) is None
        assert bt._unfilled_entries > 0

    def test_limit_below_market_fills_at_limit(self):
        bt = _bt("marketable", StubHistoricalData(intraday=MARKETABLE_BAR))
        pos = _find_spread(bt)
        assert pos is not None
        # Fill at the limit: open 1.00 - config slippage 0.05, no extra haircut
        assert pos["credit"] == pytest.approx(0.95)
        assert bt._unfilled_entries == 0

    def test_limit_exactly_at_market_fills(self):
        bar = dict(MARKETABLE_BAR, short_open=2.05, long_open=0.80, spread_open=1.25)
        bt = _bt("marketable", StubHistoricalData(intraday=bar))
        pos = _find_spread(bt)
        # limit = 1.25 - 0.05 = 1.20 == close credit 1.20 → traded through → fill
        assert pos is not None
        assert pos["credit"] == pytest.approx(1.20)

    def test_pre_open_scan_slot_places_no_order(self):
        # Options don't trade before 9:30 ET; live's RTH guard blocks these
        # submits. Naive mode booked them off the same day's close (lookahead).
        daily = {"short_close": 2.00, "long_close": 0.80, "spread_value": 1.20}
        bt = _bt("marketable", StubHistoricalData(intraday=MARKETABLE_BAR, daily=daily))
        assert _find_spread(bt, scan_hour=9, scan_minute=5) is None
        # naive keeps the legacy behavior on the same inputs
        bt_naive = _bt(None, StubHistoricalData(intraday=MARKETABLE_BAR, daily=daily))
        assert _find_spread(bt_naive, scan_hour=9, scan_minute=5) is not None

    def test_daily_day_limit_above_market_no_fill(self):
        # Intraday missing → daily bar models a static day-limit (live pre-FIX2):
        # open credit 1.50 − 0.05 = 1.45 limit, day traded down to 1.20 → no fill
        daily = dict(UNMARKETABLE_BAR)
        del daily["slippage"]
        bt = _bt("marketable", StubHistoricalData(intraday=None, daily=daily))
        assert _find_spread(bt) is None
        assert bt._unfilled_entries > 0

    def test_daily_day_limit_at_or_below_market_fills(self):
        daily = dict(MARKETABLE_BAR)
        del daily["slippage"]
        bt = _bt("marketable", StubHistoricalData(intraday=None, daily=daily))
        pos = _find_spread(bt)
        assert pos is not None
        assert pos["credit"] == pytest.approx(0.95)

    def test_daily_fallback_without_opens_books_naively_and_is_counted(self):
        # Legacy cache rows have no open column values → marketability
        # unverifiable with close-only data → legacy fill, counted
        daily = {"short_close": 2.00, "long_close": 0.80, "spread_value": 1.20}
        bt = _bt("marketable", StubHistoricalData(intraday=None, daily=daily))
        pos = _find_spread(bt)
        assert pos is not None
        assert pos["credit"] == pytest.approx(1.20 - 0.05)
        assert bt._fill_model_naive_fallbacks == 1
        assert bt._unfilled_entries == 0


class TestNaiveFillModel:
    def test_default_is_naive_and_always_fills(self):
        # Same bar that produced a no-fill in marketable mode
        bt = _bt(None, StubHistoricalData(intraday=UNMARKETABLE_BAR))
        assert bt._fill_model == "naive"
        pos = _find_spread(bt)
        assert pos is not None
        # Legacy pricing: bar close 1.20 minus bar-range slippage 0.10
        assert pos["credit"] == pytest.approx(1.10)
        assert bt._unfilled_entries == 0


class TestConfigValidation:
    def test_nbbo_is_a_documented_stub(self):
        with pytest.raises(NotImplementedError):
            _bt("nbbo", StubHistoricalData(intraday=MARKETABLE_BAR))

    def test_unknown_fill_model_rejected(self):
        with pytest.raises(ValueError):
            _bt("magic", StubHistoricalData(intraday=MARKETABLE_BAR))
