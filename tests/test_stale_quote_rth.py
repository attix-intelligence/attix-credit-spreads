"""Tests for FIX #1: no fabricated bid/ask from prior close during RTH.

Root cause of the Jul 9 live no-fill: at the opening rotation the Polygon
snapshot ``last_quote`` is empty for many contracts, and the provider
substituted prior-day close for both bid AND ask, pricing spreads off
stale marks ($3.14 limit vs a real ~$1.21-1.28 market).

During RTH a contract with no fresh quote must keep bid=ask=0 so the
chain filters drop it and the strategy skips that leg. Outside RTH the
prior-close fallback is preserved (after-hours scans/reports rely on it).
"""

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import strategy.polygon_provider as pp_mod
from shared.market_calendar import is_rth
from strategy.polygon_provider import QUOTE_MAX_AGE_SECONDS, PolygonProvider
from strategy.spread_strategy import CreditSpreadStrategy

_ET = ZoneInfo("America/New_York")

# Thursday 2026-07-09 09:30:04 ET — the opening rotation, inside RTH.
RTH_NOW = datetime(2026, 7, 9, 9, 30, 4, tzinfo=_ET)
# Thursday 2026-07-09 16:30:00 ET — after the close.
AFTER_HOURS_NOW = datetime(2026, 7, 9, 16, 30, 0, tzinfo=_ET)
# Prior session's last quote timestamp (Wed 2026-07-08 16:00 ET), in ns.
PRIOR_SESSION_NS = int(datetime(2026, 7, 8, 16, 0, 0, tzinfo=_ET).timestamp() * 1e9)

EXP_DT = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _item(bid=0.0, ask=0.0, close=0.0, last_updated_ns=None, strike=620.0):
    last_quote = {}
    if bid:
        last_quote["bid"] = bid
    if ask:
        last_quote["ask"] = ask
    if last_updated_ns is not None:
        last_quote["last_updated"] = last_updated_ns
    return {
        "details": {
            "ticker": f"O:SPY260814P{int(strike * 1000):08d}",
            "strike_price": strike,
            "contract_type": "put",
            "expiration_date": "2026-08-14",
        },
        "greeks": {"delta": -0.12, "iv": 0.18, "gamma": 0.01, "theta": -0.05, "vega": 0.4},
        "day": {"close": close, "volume": 100},
        "open_interest": 500,
        "last_quote": last_quote,
        "underlying_asset": {"price": 628.0},
    }


# ---------------------------------------------------------------------------
# _build_option_row: fallback / freshness behaviour
# ---------------------------------------------------------------------------

class TestBuildOptionRowRTH:
    def test_empty_quote_during_rth_is_not_fabricated(self):
        """The Jul 9 bug: empty quote + prior close must NOT become bid/ask in RTH."""
        row = PolygonProvider._build_option_row(_item(close=3.14), EXP_DT, now=RTH_NOW)
        assert row["bid"] == 0
        assert row["ask"] == 0
        assert row["mid"] == 0

    def test_empty_quote_outside_rth_falls_back_to_close(self):
        row = PolygonProvider._build_option_row(_item(close=3.14), EXP_DT, now=AFTER_HOURS_NOW)
        assert row["bid"] == 3.14
        assert row["ask"] == 3.14
        assert row["mid"] == 3.14

    def test_prior_session_quote_during_rth_is_rejected(self):
        """A non-empty quote left over from the prior session is stale during RTH."""
        row = PolygonProvider._build_option_row(
            _item(bid=1.20, ask=1.30, close=3.14, last_updated_ns=PRIOR_SESSION_NS),
            EXP_DT,
            now=RTH_NOW,
        )
        assert row["bid"] == 0
        assert row["ask"] == 0

    def test_fresh_quote_during_rth_is_used(self):
        fresh_ns = int((RTH_NOW.timestamp() - 2) * 1e9)
        row = PolygonProvider._build_option_row(
            _item(bid=1.20, ask=1.30, close=3.14, last_updated_ns=fresh_ns),
            EXP_DT,
            now=RTH_NOW,
        )
        assert row["bid"] == 1.20
        assert row["ask"] == 1.30
        assert row["mid"] == pytest.approx(1.25)

    def test_quote_at_freshness_boundary_is_used(self):
        boundary_ns = int((RTH_NOW.timestamp() - QUOTE_MAX_AGE_SECONDS) * 1e9)
        row = PolygonProvider._build_option_row(
            _item(bid=1.20, ask=1.30, last_updated_ns=boundary_ns), EXP_DT, now=RTH_NOW
        )
        assert row["bid"] == 1.20
        assert row["ask"] == 1.30

    def test_quote_without_timestamp_during_rth_is_trusted(self):
        """Missing last_updated must not zero out an otherwise live quote."""
        row = PolygonProvider._build_option_row(
            _item(bid=1.20, ask=1.30), EXP_DT, now=RTH_NOW
        )
        assert row["bid"] == 1.20
        assert row["ask"] == 1.30

    def test_no_quote_and_no_close_stays_zero_outside_rth(self):
        row = PolygonProvider._build_option_row(_item(), EXP_DT, now=AFTER_HOURS_NOW)
        assert row["bid"] == 0
        assert row["ask"] == 0
        assert row["mid"] == 0


# ---------------------------------------------------------------------------
# get_full_chain: no-quote contracts are dropped from the chain during RTH
# ---------------------------------------------------------------------------

class TestChainFiltering:
    def _provider(self, monkeypatch, items):
        provider = PolygonProvider(api_key="test-key")
        monkeypatch.setattr(provider, "_paginate", lambda *a, **k: items)
        return provider

    def test_full_chain_drops_no_quote_contracts_during_rth(self, monkeypatch):
        monkeypatch.setattr(pp_mod, "is_rth", lambda now=None: True)
        fresh_ns = int((time.time() - 2) * 1e9)
        items = [
            _item(bid=1.20, ask=1.30, close=1.25, last_updated_ns=fresh_ns, strike=620.0),
            _item(close=3.14, strike=615.0),  # empty quote, prior close only
        ]
        chain = self._provider(monkeypatch, items).get_full_chain("SPY")
        assert len(chain) == 1
        assert chain.iloc[0]["strike"] == 620.0

    def test_full_chain_keeps_close_fallback_outside_rth(self, monkeypatch):
        monkeypatch.setattr(pp_mod, "is_rth", lambda now=None: False)
        chain = self._provider(monkeypatch, [_item(close=3.14, strike=615.0)]).get_full_chain("SPY")
        assert len(chain) == 1
        assert chain.iloc[0]["bid"] == 3.14
        assert chain.iloc[0]["ask"] == 3.14


# ---------------------------------------------------------------------------
# Caller behaviour: a missing (filtered) leg means the spread is skipped
# ---------------------------------------------------------------------------

class TestCallerSkipsNoQuoteLegs:
    def _strategy(self):
        return CreditSpreadStrategy({
            'strategy': {
                'min_dte': 30, 'max_dte': 45,
                'min_delta': 0.10, 'max_delta': 0.15,
                'spread_width': 5,
                'min_iv_rank': 25, 'min_iv_percentile': 25,
                'technical': {},
            },
            'risk': {
                'account_size': 100000, 'max_risk_per_trade': 2.0,
                'max_positions': 7, 'profit_target': 50,
                'stop_loss_multiplier': 2.5, 'delta_threshold': 0.30,
                'min_credit_pct': 20,
            },
        })

    def _chain(self, include_long_leg: bool) -> pd.DataFrame:
        rows = [{
            'strike': 620.0, 'type': 'put', 'bid': 1.85, 'ask': 1.95,
            'delta': -0.12, 'mid': 1.90, 'expiration': EXP_DT,
        }]
        if include_long_leg:
            rows.append({
                'strike': 615.0, 'type': 'put', 'bid': 0.55, 'ask': 0.60,
                'delta': -0.08, 'mid': 0.575, 'expiration': EXP_DT,
            })
        return pd.DataFrame(rows)

    def test_spread_skipped_when_long_leg_has_no_quote(self):
        """A leg dropped by the RTH quote filter must mean no spread that cycle."""
        strategy = self._strategy()
        spreads = strategy._find_spreads(
            'SPY', self._chain(include_long_leg=False), 628.0, EXP_DT, 'bull_put',
            as_of_date=RTH_NOW,
        )
        assert spreads == []

    def test_spread_found_when_both_legs_quoted(self):
        strategy = self._strategy()
        spreads = strategy._find_spreads(
            'SPY', self._chain(include_long_leg=True), 628.0, EXP_DT, 'bull_put',
            as_of_date=RTH_NOW,
        )
        assert len(spreads) == 1
        assert spreads[0]['credit'] == pytest.approx(1.25)


# ---------------------------------------------------------------------------
# is_rth boundaries
# ---------------------------------------------------------------------------

class TestIsRTH:
    @pytest.mark.parametrize("dt,expected", [
        (datetime(2026, 7, 9, 9, 29, 59, tzinfo=_ET), False),   # pre-open
        (datetime(2026, 7, 9, 9, 30, 0, tzinfo=_ET), True),     # open (inclusive)
        (datetime(2026, 7, 9, 12, 0, 0, tzinfo=_ET), True),     # midday
        (datetime(2026, 7, 9, 15, 59, 59, tzinfo=_ET), True),   # just before close
        (datetime(2026, 7, 9, 16, 0, 0, tzinfo=_ET), False),    # close (exclusive)
        (datetime(2026, 7, 11, 12, 0, 0, tzinfo=_ET), False),   # Saturday
    ])
    def test_boundaries(self, dt, expected):
        assert is_rth(dt) is expected

    def test_naive_datetime_treated_as_utc(self):
        # 13:30:04 UTC == 09:30:04 ET on 2026-07-09 (EDT)
        assert is_rth(datetime(2026, 7, 9, 13, 30, 4)) is True
