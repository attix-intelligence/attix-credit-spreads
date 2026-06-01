"""Tests for compass.live.vrp_streams — per-stream signal → order intent (PR-B)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from compass.live.vrp_contracts import STREAM_SPECS, StreamStatus
from compass.live.vrp_data import VRPSnapshot
from compass.live.vrp_streams import (
    CreditSpreadStream,
    InactiveStream,
    build_default_registry,
)
from tests.vrp_fixtures import make_put_chain, make_snapshot


def _spy_stream() -> CreditSpreadStream:
    return CreditSpreadStream(STREAM_SPECS["exp1220"])


# ── credit-spread entry signal ────────────────────────────────────────────────

def test_credit_spread_emits_bull_put_intent():
    snap = make_snapshot(vix=18.0)
    res = _spy_stream().generate(snap, capital=10_000.0)
    assert res.status == "entered"
    assert len(res.intents) == 1
    intent = res.intents[0]
    assert intent.structure == "bull_put"
    assert intent.symbol == "SPY"
    # legs: sell short put (higher strike) + buy long put (lower strike), $5 wide.
    sell = next(leg for leg in intent.legs if leg.side == "sell")
    buy = next(leg for leg in intent.legs if leg.side == "buy")
    assert sell.right == "P" and buy.right == "P"
    assert sell.strike - buy.strike == pytest.approx(5.0)
    assert intent.est_credit > 0
    assert intent.est_max_loss == pytest.approx((sell.strike - buy.strike) - intent.est_credit)


def test_short_strike_targets_delta_20():
    """Short put is selected by |Δ| ≈ 0.20 within [0.15, 0.25] (not by spot %).

    With the fixture's monotonic |Δ| = clamp(0.50 + 5·(K−S)/S, …), the strike
    closest to |Δ|=0.20 for SPY at 500 is K=470 (|Δ|=0.20). The old picker would
    have selected ~475 (5%-OTM by spot), which is delta-blind. The legacy 475
    target is now the LONG strike (short − 5).
    """
    snap = make_snapshot(spots={"SPY": 500.0}, vix=18.0)
    res = _spy_stream().generate(snap, capital=10_000.0)
    sell = next(leg for leg in res.intents[0].legs if leg.side == "sell")
    buy = next(leg for leg in res.intents[0].legs if leg.side == "buy")
    assert sell.strike == pytest.approx(470.0, abs=1.0)
    assert buy.strike == pytest.approx(465.0, abs=1.0)
    # Verify the chosen short's |Δ| is in window.
    chain = snap.chains["SPY"]
    short_row = chain[(chain["type"] == "put") & (chain["strike"] == sell.strike)].iloc[0]
    assert 0.15 <= abs(float(short_row["delta"])) <= 0.25


def test_contracts_scale_with_capital():
    snap = make_snapshot(spots={"SPY": 500.0}, vix=18.0)
    stream = _spy_stream()
    # per-spread risk = (5 - 1.5) * 100 = $350 with the fixture's pricing.
    res_small = stream.generate(snap, capital=350.0)
    res_big = stream.generate(snap, capital=3_500.0)
    assert res_small.intents[0].contracts == 1
    assert res_big.intents[0].contracts == 10


def test_capital_below_one_spread_yields_no_capital():
    snap = make_snapshot(spots={"SPY": 500.0}, vix=18.0)
    res = _spy_stream().generate(snap, capital=100.0)  # < $350 one-spread risk
    assert res.status == "no_capital"
    assert res.intents == []


def test_zero_capital_no_entry():
    res = _spy_stream().generate(make_snapshot(vix=18.0), capital=0.0)
    assert res.status == "no_capital"


def test_vix_gate_blocks_entry():
    snap = make_snapshot(spots={"SPY": 500.0}, vix=45.0)  # > vix_max_entry 40
    res = _spy_stream().generate(snap, capital=10_000.0)
    assert res.status == "vix_gated"
    assert res.intents == []


def test_missing_chain_degrades():
    # Snapshot without SPY (e.g. provider dropped it) → degraded, no crash.
    snap = make_snapshot(spots={"QQQ": 430.0}, vix=18.0)
    res = _spy_stream().generate(snap, capital=10_000.0)
    assert res.status == "degraded"


def test_credit_spread_rejects_non_tradeable_spec():
    with pytest.raises(ValueError):
        CreditSpreadStream(STREAM_SPECS["gld_cal"])  # BLOCKED spec


# ── inactive streams ──────────────────────────────────────────────────────────

def test_blocked_stream_reports_blocked():
    res = InactiveStream(STREAM_SPECS["gld_cal"]).generate(make_snapshot(), capital=10_000.0)
    assert res.status == "blocked"
    assert res.intents == []


def test_deferred_stream_reports_deferred():
    res = InactiveStream(STREAM_SPECS["v5_hedge"]).generate(make_snapshot(), capital=10_000.0)
    assert res.status == "deferred"
    assert res.intents == []


def test_inactive_rejects_tradeable_spec():
    with pytest.raises(ValueError):
        InactiveStream(STREAM_SPECS["exp1220"])


# ── registry ──────────────────────────────────────────────────────────────────

def test_registry_has_all_eight_with_correct_types():
    reg = build_default_registry()
    assert tuple(reg.keys()) == tuple(STREAM_SPECS.keys())
    for sid, gen in reg.items():
        if STREAM_SPECS[sid].status is StreamStatus.TRADEABLE:
            assert isinstance(gen, CreditSpreadStream)
        else:
            assert isinstance(gen, InactiveStream)


# ── credit-positive safety net (post-XLI 165/160P debit-spread bug) ───────────

def test_worst_case_credit_helper_basic():
    """``_worst_case_credit = short_bid − long_ask`` — the most adverse fill
    direction consistent with both quotes. Returns None when bid/ask missing."""
    from compass.live.vrp_streams import _worst_case_credit
    short = pd.Series({"bid": 1.10, "ask": 1.30})
    long_ = pd.Series({"bid": 0.90, "ask": 1.05})
    # short_bid (1.10) − long_ask (1.05) = +0.05 (positive, barely safe)
    assert _worst_case_credit(short, long_) == pytest.approx(0.05)


def test_worst_case_credit_negative_signals_potential_debit():
    """The XLI-style regime: deeper-OTM long leg has higher ask than short bid.
    Worst-case credit is NEGATIVE — actual fill could come back as a debit."""
    from compass.live.vrp_streams import _worst_case_credit
    short = pd.Series({"bid": 1.10, "ask": 1.30})
    long_ = pd.Series({"bid": 1.20, "ask": 1.40})
    # short_bid (1.10) − long_ask (1.40) = -0.30 (negative ⇒ flag)
    assert _worst_case_credit(short, long_) == pytest.approx(-0.30)


def test_worst_case_credit_returns_none_on_missing_quotes():
    """Degrades silently to None when bid/ask aren't populated — caller falls
    back to the mid-based check so degraded chains don't kill all entries."""
    from compass.live.vrp_streams import _worst_case_credit
    assert _worst_case_credit(pd.Series({"bid": None, "ask": 1.0}), pd.Series({"bid": 0.9, "ask": 1.0})) is None
    assert _worst_case_credit(pd.Series({"bid": 1.0, "ask": 1.5}), pd.Series({"bid": 0.9, "ask": None})) is None
    assert _worst_case_credit(pd.Series({"bid": 0.0, "ask": 1.0}), pd.Series({"bid": 0.5, "ask": 1.0})) is None


def test_select_spread_skips_when_worst_case_credit_negative(caplog):
    """Reproduce the XLI bug: chain shows positive mid-credit but the bid/ask
    structure makes the actual fill a likely debit. ``_select_spread`` must
    fall through to the next short-strike candidate (or return None) and log
    the skip with the strikes + worst-case number.

    Adjusted post-PR-D to the delta picker: the short (165P) carries the
    in-window |Δ|=0.20; the long (160P) is out of window (|Δ|=0.10) but the
    picker pairs them by width=5. mid-credit passes, worst-case fails → skip.
    """
    import logging
    # Build a hand-crafted put chain where the only $5-wide pair has a
    # POSITIVE mid-credit but a NEGATIVE worst-case credit:
    #   short 165P:  bid 1.10  mid 1.30  ask 1.50   |Δ|=0.20 (in delta window)
    #   long  160P:  bid 1.05  mid 1.20  ask 1.40   |Δ|=0.10 (out, used for width pair)
    #   mid-credit  = 1.30 − 1.20 = +0.10 ✓ (> 0.05 floor) — would proceed pre-fix
    #   worst-case  = 1.10 − 1.40 = -0.30 ✗ — must be rejected post-fix
    rows = [
        {"strike": 165.0, "type": "put", "bid": 1.10, "ask": 1.50, "mid": 1.30,
         "contract_symbol": "XLI260626P00165000", "expiration": pd.Timestamp("2026-06-26"),
         "delta": -0.20, "iv": 0.20, "volume": 100, "open_interest": 500,
         "last": 1.30, "raw_delta": -0.20, "gamma": 0.01, "theta": -0.05, "vega": 0.10, "itm": False},
        {"strike": 160.0, "type": "put", "bid": 1.05, "ask": 1.40, "mid": 1.20,
         "contract_symbol": "XLI260626P00160000", "expiration": pd.Timestamp("2026-06-26"),
         "delta": -0.10, "iv": 0.22, "volume": 100, "open_interest": 500,
         "last": 1.20, "raw_delta": -0.10, "gamma": 0.01, "theta": -0.05, "vega": 0.10, "itm": False},
    ]
    puts = pd.DataFrame(rows)
    stream = CreditSpreadStream(STREAM_SPECS["xli_cs"])
    caplog.set_level(logging.INFO)
    result = stream._select_spread(puts, spot=173.0)
    assert result is None, (
        "spread with positive mid-credit but negative worst-case credit must "
        "be rejected (reproduces the 2026-06-01 XLI 165/160P debit-spread bug)"
    )
    # The skip must be logged with the worst-case number so operators can audit.
    skip_records = [r for r in caplog.records if "worst-case credit" in r.message]
    assert skip_records, "the skip should be logged with worst_case_credit details"
    msg = skip_records[0].message
    assert "165" in msg and "160" in msg, "log line should reference both strikes"


def test_select_spread_still_accepts_genuine_positive_credit():
    """Sanity: when both mid AND worst-case credit are above ``min_credit``, the
    spread is still selected. The new safety net must not over-block.

    Adjusted post-PR-D: the chosen short must be in [delta_min, delta_max] —
    495P carries |Δ|=0.20, 490P carries |Δ|=0.10 (out, used as width pair).
    """
    # Normal bull-put: short 495P richer than long 490P at both mid and bid/ask.
    rows = [
        {"strike": 495.0, "type": "put", "bid": 1.70, "ask": 1.80, "mid": 1.75,
         "contract_symbol": "SPY260626P00495000", "expiration": pd.Timestamp("2026-06-26"),
         "delta": -0.20, "iv": 0.20, "volume": 100, "open_interest": 500,
         "last": 1.75, "raw_delta": -0.20, "gamma": 0.01, "theta": -0.05, "vega": 0.10, "itm": False},
        {"strike": 490.0, "type": "put", "bid": 0.30, "ask": 0.40, "mid": 0.35,
         "contract_symbol": "SPY260626P00490000", "expiration": pd.Timestamp("2026-06-26"),
         "delta": -0.10, "iv": 0.20, "volume": 100, "open_interest": 500,
         "last": 0.35, "raw_delta": -0.10, "gamma": 0.01, "theta": -0.05, "vega": 0.10, "itm": False},
    ]
    puts = pd.DataFrame(rows)
    stream = CreditSpreadStream(STREAM_SPECS["exp1220"])
    res = stream._select_spread(puts, spot=520.0)
    assert res is not None
    short_row, long_row, credit = res
    assert float(short_row["strike"]) == 495.0
    assert float(long_row["strike"]) == 490.0
    assert credit == pytest.approx(1.40)  # mid-credit = 1.75 − 0.35


# ── delta-targeted picker hardening (the K-bleeder fix, PR-D) ────────────────


def _snapshot_from_chain(symbol: str, spot: float, chain: pd.DataFrame, vix: float = 18.0) -> VRPSnapshot:
    return VRPSnapshot(
        as_of=datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc),
        chains={symbol: chain},
        spot={symbol: spot},
        vix=vix,
        degraded=[],
    )


def test_skew_flip_rejects_debit_spread():
    """XLI 2026-05-29 K-bleeder regression: deeper-OTM long has HIGHER mid than
    closer short (skew). The old picker would have shipped a debit spread; the
    delta-targeted picker MUST sit out the cycle.
    """
    spot = 174.0
    as_of = datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)
    chain = make_put_chain("XLI", spot, as_of)
    # Inject a skew flip across the target delta-window's "short minus width"
    # pair: every put 5+ dollars below a candidate short gets a mid > the short.
    # The picker's credit check (short_mid - long_mid ≥ min_credit) must fail
    # and the cycle must return no_entry.
    puts = chain["type"] == "put"
    chain.loc[puts, "mid"] = chain.loc[puts].apply(
        lambda r: 5.00 if r["strike"] <= spot * 0.96 else 0.50, axis=1,
    )
    chain.loc[puts, "bid"] = chain.loc[puts, "mid"] - 0.05
    chain.loc[puts, "ask"] = chain.loc[puts, "mid"] + 0.05

    stream = CreditSpreadStream(STREAM_SPECS["xli_cs"])
    res = stream.generate(_snapshot_from_chain("XLI", spot, chain), capital=10_000.0)
    assert res.status == "no_entry"
    assert res.intents == []


def test_no_in_window_short_yields_no_entry():
    """Chain with all puts outside [delta_min, delta_max] → skip the cycle."""
    spot = 100.0
    as_of = datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)
    chain = make_put_chain("XLI", spot, as_of)
    # Drive every |Δ| to 0.50 (ATM) → nothing in [0.15, 0.25].
    chain.loc[chain["type"] == "put", "delta"] = -0.50

    stream = CreditSpreadStream(STREAM_SPECS["xli_cs"])
    res = stream.generate(_snapshot_from_chain("XLI", spot, chain), capital=10_000.0)
    assert res.status == "no_entry"
    assert res.intents == []


def test_missing_delta_column_refuses_to_pick_blind():
    """If the chain lacks ``delta`` (provider degraded), refuse to fall back to
    a spot-anchored picker — sit out the cycle. That fallback is the very bug
    being fixed.
    """
    spot = 100.0
    as_of = datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)
    chain = make_put_chain("XLI", spot, as_of).drop(columns=["delta"])

    stream = CreditSpreadStream(STREAM_SPECS["xli_cs"])
    res = stream.generate(_snapshot_from_chain("XLI", spot, chain), capital=10_000.0)
    assert res.status == "no_entry"


def test_chosen_short_has_minimum_credit():
    """``min_credit`` is enforced: a candidate short that produces credit below
    the floor is rejected even when |Δ| is on target.
    """
    snap = make_snapshot(spots={"SPY": 500.0}, vix=18.0)
    # Fixture's mid is linear-by-strike → 5-wide spread credit ≈ 1.50.
    # Raise min_credit above 1.50 → no entry.
    stream = CreditSpreadStream(STREAM_SPECS["exp1220"], min_credit=2.50)
    res = stream.generate(snap, capital=10_000.0)
    assert res.status == "no_entry"


def test_delta_window_constructor_validates():
    with pytest.raises(ValueError):
        CreditSpreadStream(STREAM_SPECS["exp1220"], delta_min=0.30, delta_max=0.20)
    with pytest.raises(ValueError):
        CreditSpreadStream(STREAM_SPECS["exp1220"], target_short_delta=0.30,
                            delta_min=0.15, delta_max=0.25)


def test_width_is_preserved_at_default_5():
    """``long = short − width`` is preserved regardless of where delta lands."""
    snap = make_snapshot(spots={"SPY": 500.0}, vix=18.0)
    res = _spy_stream().generate(snap, capital=10_000.0)
    sell = next(leg for leg in res.intents[0].legs if leg.side == "sell")
    buy = next(leg for leg in res.intents[0].legs if leg.side == "buy")
    assert sell.strike - buy.strike == pytest.approx(5.0)


def test_picker_advances_to_next_candidate_when_first_credit_fails():
    """A candidate short whose paired long fails the credit check shouldn't
    prevent the picker from trying the next-best short by delta gap.
    """
    spot = 500.0
    as_of = datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)
    chain = make_put_chain("SPY", spot, as_of)
    # K=470 is the target (|Δ|=0.20). Poison its width-paired long (K=465) so
    # the spread credit fails (long mid > short mid). The picker should then
    # fall through to K=471 or K=469 (next-closest by delta gap) and ship.
    puts = chain["type"] == "put"
    chain.loc[puts & (chain["strike"] == 465.0), "mid"] = 99.0
    chain.loc[puts & (chain["strike"] == 465.0), "bid"] = 98.95
    chain.loc[puts & (chain["strike"] == 465.0), "ask"] = 99.05

    stream = CreditSpreadStream(STREAM_SPECS["exp1220"])
    res = stream.generate(_snapshot_from_chain("SPY", spot, chain), capital=10_000.0)
    assert res.status == "entered"
    sell = next(leg for leg in res.intents[0].legs if leg.side == "sell")
    # The poisoned 465 long forced the picker off the K=470 short; should land
    # on a neighbouring strike still within the [0.15, 0.25] window.
    assert sell.strike != 470.0
    assert sell.strike - next(leg for leg in res.intents[0].legs if leg.side == "buy").strike == pytest.approx(5.0)
