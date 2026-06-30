"""Tests for the leg-collision guard (Option B broker-netting fix).

Reproduces the live trigger Charles reported on 2026-06-30:
  Mon 6/29: SPY 17-Jul bear-call 744/756  (SELL 744C, BUY 756C)
  Tue 6/30: SPY 17-Jul bear-call 756/768  (SELL 756C, BUY 768C)
The Tuesday spread tries to sell-to-open 756C, which we already hold LONG
from Monday. A real broker rejects this; the backtest must skip it too.
"""
from datetime import datetime

from backtest.backtester import (
    enumerate_position_legs,
    position_leg_collision,
)

EXP = datetime(2026, 7, 17)


def _bear_call(short_strike, long_strike, exp=EXP):
    return {
        'ticker': 'SPY',
        'type': 'bear_call_spread',
        'option_type': 'C',
        'expiration': exp,
        'short_strike': short_strike,
        'long_strike': long_strike,
    }


def _bull_put(short_strike, long_strike, exp=EXP):
    return {
        'ticker': 'SPY',
        'type': 'bull_put_spread',
        'option_type': 'P',
        'expiration': exp,
        'short_strike': short_strike,
        'long_strike': long_strike,
    }


def _iron_condor(ps, pl, cs, cl, exp=EXP):
    return {
        'ticker': 'SPY',
        'type': 'iron_condor',
        'option_type': 'IC',
        'expiration': exp,
        'short_strike': ps, 'long_strike': pl,
        'call_short_strike': cs, 'call_long_strike': cl,
    }


def _legs_of(pos):
    return set(enumerate_position_legs(pos))


def test_charles_scenario_collision_detected():
    """The exact reported case: short 756 collides with held long 756."""
    monday = _bear_call(744, 756)            # SELL 744C, BUY 756C
    occupied = _legs_of(monday)
    tuesday = _bear_call(756, 768)           # SELL 756C, BUY 768C
    assert position_leg_collision(tuesday, occupied) is True


def test_reverse_collision_long_matches_held_short():
    """Candidate's long leg equals a held short leg → also rejected."""
    held = _bear_call(756, 768)              # SELL 756C, BUY 768C
    occupied = _legs_of(held)
    candidate = _bear_call(744, 756)         # BUY 756C collides with held SELL 756C
    assert position_leg_collision(candidate, occupied) is True


def test_non_colliding_stack_allowed():
    """Two spreads that share no leg symbol may both open."""
    held = _bear_call(744, 749)              # SELL 744C, BUY 749C
    occupied = _legs_of(held)
    candidate = _bear_call(760, 765)         # disjoint strikes
    assert position_leg_collision(candidate, occupied) is False


def test_identical_spread_no_short_long_collision():
    """Re-stacking the identical spread is NOT a leg collision (handled by the
    separate per-key stack limit, not the broker short/long-netting rule)."""
    held = _bear_call(744, 749)
    occupied = _legs_of(held)
    candidate = _bear_call(744, 749)
    # short 744 vs held short 744 = same direction, not a netting conflict;
    # long 749 vs held long 749 = same direction. No collision here.
    assert position_leg_collision(candidate, occupied) is False


def test_different_expiration_no_collision():
    held = _bear_call(744, 756, exp=datetime(2026, 7, 17))
    occupied = _legs_of(held)
    candidate = _bear_call(756, 768, exp=datetime(2026, 7, 24))
    assert position_leg_collision(candidate, occupied) is False


def test_put_and_call_same_strike_no_collision():
    """Same strike but different option type must not collide."""
    held = _bear_call(756, 768)              # calls
    occupied = _legs_of(held)
    candidate = _bull_put(756, 751)          # puts at 756 — different symbol
    assert position_leg_collision(candidate, occupied) is False


def test_iron_condor_leg_collision():
    """An IC whose put-long leg equals a held bull-put short leg is rejected."""
    held = _bull_put(450, 445)               # SELL 450P, BUY 445P
    occupied = _legs_of(held)
    # IC put side: SELL 455P / BUY 450P  -> long 450 collides with held short 450
    candidate = _iron_condor(455, 450, 470, 475)
    assert position_leg_collision(candidate, occupied) is True


def test_enumerate_skips_none_legs():
    pos = {'expiration': EXP, 'option_type': 'C',
           'short_strike': 744, 'long_strike': None}
    legs = list(enumerate_position_legs(pos))
    assert (EXP, 744.0, 'C', 'S') in legs
    assert all(l[1] is not None for l in legs)


def test_acceptance_no_simultaneous_short_equals_long():
    """Acceptance criterion: across a set of accepted positions, no expiration
    has one position's short strike equal to another's long strike (same type)."""
    accepted = []
    occupied = set()
    candidates = [_bear_call(744, 756), _bear_call(756, 768), _bear_call(760, 772)]
    for c in candidates:
        if not position_leg_collision(c, occupied):
            accepted.append(c)
            for leg in enumerate_position_legs(c):
                occupied.add(leg)
    # 744/756 accepted; 756/768 rejected (756 collision); 760/772 accepted.
    assert len(accepted) == 2
    shorts = {(l[0], l[1], l[2]) for p in accepted
              for l in enumerate_position_legs(p) if l[3] == 'S'}
    longs = {(l[0], l[1], l[2]) for p in accepted
             for l in enumerate_position_legs(p) if l[3] == 'L'}
    assert shorts.isdisjoint(longs)
