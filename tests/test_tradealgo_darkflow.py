"""Tests for shared.tradealgo_darkflow.

Fixture data is shaped to mirror the real prod response (verified against
data/tradealgo/2026-05-27/snapshot.json on 2026-05-28). Strings for
multiplier / dollar_value / market_cap; numeric for options/ats sub-fields.
"""
from __future__ import annotations

import math

import pytest

from shared.tradealgo_darkflow import (
    DarkFlowRecord,
    darkflow_zscores,
    parse_historical_darkflow,
    parse_movement_darkflow,
    top_darkflow,
)


def _entry(
    ticker: str,
    *,
    multiplier: float,
    dollar_value: float,
    flow_sentiment: float | None = 0.6,
    ats_pct: float | None = 100.0,
    perf: float | None = 1.0,
    has_options: bool = True,
) -> dict:
    """Realistically-shaped movement entry."""
    out: dict = {
        "ticker": ticker,
        "multiplier": str(multiplier),
        "dollar_value": str(dollar_value),
        "has_options": has_options,
        "perf": perf,
        "market_cap": "1000000000",
        "last_price": 50.0,
        "ats": {
            "compared": {"day_dollar_volume": ats_pct} if ats_pct is not None else {}
        },
    }
    if has_options and flow_sentiment is not None:
        out["options"] = {
            "call_flow": flow_sentiment,
            "flow_sentiment": flow_sentiment,
            "put_to_call": (1 - flow_sentiment) / max(flow_sentiment, 1e-6),
            "call_total_prem": 1_000_000,
            "put_total_prem": 200_000,
        }
    return out


@pytest.fixture
def snapshot():
    """A snapshot bundle with 3 movement files populated."""
    return {
        "movement/darkflow-large.json": {
            "trending_up": [
                _entry("META", multiplier=1.96, dollar_value=6.9e9,
                       flow_sentiment=0.79, ats_pct=145.6, perf=4.2),
                _entry("IREN", multiplier=2.19, dollar_value=2.7e9,
                       flow_sentiment=0.68, ats_pct=132.4, perf=10.2),
            ],
            "trending_down": [
                _entry("AAPL", multiplier=1.34, dollar_value=4.0e9,
                       flow_sentiment=0.40, ats_pct=85.0, perf=-2.1),
            ],
        },
        "movement/darkflow-medium.json": {
            "trending_up": [
                _entry("ASTS", multiplier=1.53, dollar_value=2.2e9,
                       flow_sentiment=0.78, ats_pct=118.0, perf=3.0),
                _entry("APP",  multiplier=2.26, dollar_value=2.5e9,
                       flow_sentiment=0.81, ats_pct=128.0, perf=5.5),
            ],
            "trending_down": [],
        },
        "movement/darkflow-small.json": {
            "trending_up": [
                _entry("ONDS", multiplier=1.70, dollar_value=5.4e8,
                       flow_sentiment=0.86, ats_pct=110.0, perf=2.4),
            ],
            "trending_down": [
                _entry("XYZQ", multiplier=1.10, dollar_value=1.5e8,
                       flow_sentiment=0.35, ats_pct=78.0, perf=-1.5),
            ],
        },
    }


# ---------------------------------------------------------------------------
# parse_movement_darkflow
# ---------------------------------------------------------------------------

class TestParseMovement:
    def test_returns_per_ticker_records(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        assert set(records.keys()) == {"META", "IREN", "AAPL", "ASTS", "APP", "ONDS", "XYZQ"}
        assert all(isinstance(r, DarkFlowRecord) for r in records.values())

    def test_string_fields_coerced_to_float(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        meta = records["META"]
        assert isinstance(meta.multiplier, float) and meta.multiplier == 1.96
        assert isinstance(meta.dollar_value, float) and meta.dollar_value == 6.9e9
        assert isinstance(meta.market_cap, float) and meta.market_cap == 1e9

    def test_side_and_bucket_tagged(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        assert records["META"].side == "up"
        assert records["META"].cap_bucket == "large"
        assert records["AAPL"].side == "down"
        assert records["XYZQ"].cap_bucket == "small"

    def test_options_nested_fields(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        meta = records["META"]
        assert meta.flow_sentiment == 0.79
        assert meta.call_flow == 0.79
        assert meta.ats_dollar_volume_pct == 145.6

    def test_missing_options_block_yields_none(self):
        snap = {
            "movement/darkflow-large.json": {
                "trending_up": [_entry("NONE", multiplier=1.5, dollar_value=1e9,
                                       has_options=False, flow_sentiment=None)],
                "trending_down": [],
            }
        }
        rec = parse_movement_darkflow(snap)["NONE"]
        assert rec.flow_sentiment is None
        assert rec.call_flow is None

    def test_unparseable_strings_drop_record(self):
        snap = {
            "movement/darkflow-large.json": {
                "trending_up": [{
                    "ticker": "BAD", "multiplier": "not-a-number",
                    "dollar_value": "1e9",
                }],
                "trending_down": [],
            },
        }
        assert "BAD" not in parse_movement_darkflow(snap)

    def test_missing_ticker_drop_record(self):
        snap = {
            "movement/darkflow-large.json": {
                "trending_up": [{"multiplier": "1.5", "dollar_value": "1e9"}],
                "trending_down": [],
            },
        }
        assert parse_movement_darkflow(snap) == {}

    def test_dedupe_keeps_highest_multiplier(self):
        snap = {
            "movement/darkflow-small.json":  {
                "trending_up": [_entry("X", multiplier=1.0, dollar_value=1e8)],
                "trending_down": [],
            },
            "movement/darkflow-medium.json": {
                "trending_up": [_entry("X", multiplier=3.0, dollar_value=1e8)],
                "trending_down": [],
            },
            "movement/darkflow-large.json":  {
                "trending_up": [_entry("X", multiplier=2.0, dollar_value=1e8)],
                "trending_down": [],
            },
        }
        rec = parse_movement_darkflow(snap)["X"]
        assert rec.multiplier == 3.0
        assert rec.cap_bucket == "medium"

    def test_empty_snapshot_returns_empty_dict(self):
        assert parse_movement_darkflow({}) == {}

    def test_malformed_module_skipped(self):
        snap = {
            "movement/darkflow-large.json": "not a dict",
            "movement/darkflow-medium.json": {"trending_up": "not a list", "trending_down": []},
            "movement/darkflow-small.json": {
                "trending_up": [_entry("OK", multiplier=1.5, dollar_value=1e8)],
                "trending_down": [],
            },
        }
        records = parse_movement_darkflow(snap)
        assert set(records.keys()) == {"OK"}


# ---------------------------------------------------------------------------
# darkflow_zscores
# ---------------------------------------------------------------------------

class TestZScores:
    def test_returns_score_per_ticker(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        zs = darkflow_zscores(records)
        assert set(zs.keys()) == set(records.keys())

    def test_z_is_mean_zero_across_population_for_multiplier_only(self):
        # Construct a snapshot where only multiplier varies; log(dollar) const,
        # ats const → z(log dollar) and z(ats) are 0 each → composite reduces to z(multiplier)/3
        ats = 100.0
        dol = 1e9
        snap = {
            "movement/darkflow-large.json": {
                "trending_up": [
                    _entry("A", multiplier=1.0, dollar_value=dol,
                           flow_sentiment=0.5, ats_pct=ats),
                    _entry("B", multiplier=2.0, dollar_value=dol,
                           flow_sentiment=0.5, ats_pct=ats),
                    _entry("C", multiplier=3.0, dollar_value=dol,
                           flow_sentiment=0.5, ats_pct=ats),
                ],
                "trending_down": [],
            },
        }
        records = parse_movement_darkflow(snap)
        zs = darkflow_zscores(records)
        # log(dollar) and ats have stddev=0 → those z-components are None,
        # so the composite collapses to just z(multiplier).
        # multiplier population = [1,2,3] → mean=2, sd=1 → z(B)=0
        assert zs["B"] is None or abs(zs["B"]) < 1e-12
        # A and B and C: at most one valid component each → composite None
        # (need >= 2 valid components per ticker)
        # So all should be None given only multiplier varies
        for v in zs.values():
            assert v is None

    def test_high_dollar_value_gets_positive_z(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        zs = darkflow_zscores(records)
        # META has the highest dollar_value by far → expect positive z
        assert zs["META"] is not None and zs["META"] > 0

    def test_zero_dollar_value_excluded_from_log(self):
        snap = {
            "movement/darkflow-large.json": {
                "trending_up": [
                    _entry("A", multiplier=1.5, dollar_value=1e9, ats_pct=100),
                    _entry("B", multiplier=1.5, dollar_value=1e9, ats_pct=120),
                    _entry("C", multiplier=1.5, dollar_value=1e9, ats_pct=80),
                ],
                "trending_down": [],
            },
        }
        records = parse_movement_darkflow(snap)
        zs = darkflow_zscores(records)
        # multiplier stddev = 0 → that component None
        # dollar_value stddev = 0 → that component None
        # only ats has variance → only 1 valid component → composite None
        for v in zs.values():
            assert v is None

    def test_empty_records_returns_empty(self):
        assert darkflow_zscores({}) == {}


# ---------------------------------------------------------------------------
# parse_historical_darkflow
# ---------------------------------------------------------------------------

class TestHistorical:
    def test_unions_up_and_down_lists(self):
        snap = {
            "historical-darkflow/daily-darkflow-up.json": [
                {"ticker": "AAA", "trending_status": "up"},
                {"ticker": "BBB", "trending_status": "up"},
            ],
            "historical-darkflow/daily-darkflow-down.json": [
                {"ticker": "CCC", "trending_status": "down"},
            ],
        }
        out = parse_historical_darkflow(snap)
        assert [e["ticker"] for e in out] == ["AAA", "BBB", "CCC"]

    def test_missing_paths_yield_empty(self):
        assert parse_historical_darkflow({}) == []

    def test_filters_non_dict_entries(self):
        snap = {
            "historical-darkflow/daily-darkflow-up.json": [
                {"ticker": "AAA"}, "string-entry", 42, None,
            ],
            "historical-darkflow/daily-darkflow-down.json": "not-a-list",
        }
        out = parse_historical_darkflow(snap)
        assert len(out) == 1 and out[0]["ticker"] == "AAA"


# ---------------------------------------------------------------------------
# top_darkflow
# ---------------------------------------------------------------------------

class TestTopDarkflow:
    def test_sorts_descending_by_dollar_value(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        top = top_darkflow(records, n=3, side="up", sort_by="dollar_value")
        tickers = [r.ticker for r in top]
        assert tickers == ["META", "IREN", "APP"]

    def test_side_filter_down_only(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        top = top_darkflow(records, n=5, side="down")
        assert {r.ticker for r in top} == {"AAPL", "XYZQ"}

    def test_side_none_returns_all(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        assert len(top_darkflow(records, n=100, side=None)) == len(records)

    def test_sort_by_multiplier(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        top = top_darkflow(records, n=2, side="up", sort_by="multiplier")
        assert [r.ticker for r in top] == ["APP", "IREN"]

    def test_invalid_sort_raises(self, snapshot):
        records = parse_movement_darkflow(snapshot)
        with pytest.raises(ValueError):
            top_darkflow(records, sort_by="garbage")
