"""Regression tests for the EXP-800 tier-3 halt deadlock.

Bug (found by EXP-800-BT, 2026-07-03): once cb_tier reached 3, `_scan_ticker`
blocked new entries unconditionally (``cb_tier >= 3``) and the HWM never
resets, so a loss REALIZED past -12% while the book is flat froze drawdown
below tier-3 forever — the strategy never traded again (1,536 of 1,571
trading days blocked in the 2020-2026 backtest; the 30-slot halt counter was
decorative).

Fix: the halt is finite and self-clearing. While the halt counter runs,
entries are blocked; once it is exhausted, sizing resumes at the tier-2 floor
(min_fraction) even if DD remains pinned below tier-3, and full recovery
above recovery_dd restores full Kelly — matching paper_exp800.yaml's
documented behavior ("halt new entries for 30 trades ... recover above -7%").
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The scanner runs pre_scan_check() at import time which can sys.exit(1).
# Patch it to a no-op for testing (same pattern as test_exp800_fixes.py).
with patch("sentinel.guards.pre_scan_check"):
    from scripts.exp800_safe_kelly_scanner import (
        _KELLY_DEFAULTS,
        KellyStateDB,
        _decrement_halt,
        _kelly_fraction,
        _tier3_entry_blocked,
    )

CB = _KELLY_DEFAULTS["circuit_breakers"]
HALT = int(CB["tier3_halt_trades"])       # 30
FLOOR = float(CB["min_fraction"])         # 2.0
BULL_FULL = float(_KELLY_DEFAULTS["regime_fractions"]["bull"])  # 9.0


@pytest.fixture
def kelly_db(tmp_path):
    return KellyStateDB(tmp_path / "kelly_state.db", account_size=100_000)


def _simulate_scan_day(db, state, equity):
    """One scan iteration as _scan_ticker sees it: fraction check, halt
    decrement when blocked, then next-day equity update."""
    kelly_pct, note = _kelly_fraction("bull", _KELLY_DEFAULTS, state)
    blocked = kelly_pct == 0.0 or _tier3_entry_blocked(state)
    if blocked:
        _decrement_halt(state, db)
    state = db.update_equity(equity, CB)
    return state, kelly_pct, blocked


class TestTier3DeadlockRegression:
    def test_realized_loss_while_flat_self_clears_after_halt_window(self, kelly_db):
        """THE deadlock repro: -21% realized with a flat book. Equity can
        never move again; trading must still resume once the halt expires."""
        state = kelly_db.update_equity(79_000, CB)  # single-day gap through all tiers
        assert state["cb_tier"] == 3
        assert state["halt_remaining"] == HALT
        assert _tier3_entry_blocked(state)

        # Flat book: equity frozen at 79k for every subsequent scan.
        blocked_days = 0
        for _ in range(HALT):
            state, kelly_pct, blocked = _simulate_scan_day(kelly_db, state, 79_000)
            assert blocked, "entries must stay blocked while the halt counter runs"
            assert kelly_pct == 0.0
            blocked_days += 1

        assert blocked_days == HALT
        assert state["halt_remaining"] == 0
        assert state["cb_tier"] == 3  # DD still pinned at -21% — that's fine

        # Halt exhausted: the block must clear even though DD cannot recover.
        assert not _tier3_entry_blocked(state)
        kelly_pct, note = _kelly_fraction("bull", _KELLY_DEFAULTS, state)
        assert kelly_pct == FLOOR, (
            f"expected tier-2 floor {FLOOR}% after halt exhaustion, got {kelly_pct} ({note})"
        )
        # Floor applies regardless of regime (never full Kelly while tier 3)
        for regime in ("bull", "neutral", "bear"):
            pct, _ = _kelly_fraction(regime, _KELLY_DEFAULTS, state)
            assert pct == FLOOR

    def test_halt_is_finite_not_decorative(self, kelly_db):
        """State-machine invariant: blocked iff (tier>=3 AND halt>0)."""
        state = kelly_db.update_equity(85_000, CB)  # -15% → tier 3
        assert _tier3_entry_blocked(state)
        state["halt_remaining"] = 0
        assert not _tier3_entry_blocked(state)
        state["halt_remaining"] = 1
        assert _tier3_entry_blocked(state)
        state["cb_tier"] = 2
        assert not _tier3_entry_blocked(state)

    def test_full_recovery_above_recovery_dd_restores_full_kelly(self, kelly_db):
        """Documented recovery path is unchanged: DD back above -7% → tier 0."""
        state = kelly_db.update_equity(79_000, CB)
        for _ in range(HALT):
            state, _, _ = _simulate_scan_day(kelly_db, state, 79_000)
        # Floor-sized trading claws equity back above -7% of the 100k HWM
        state = kelly_db.update_equity(94_000, CB)  # -6% > recovery_dd -7%
        assert state["cb_tier"] == 0
        assert state["halt_remaining"] == 0
        kelly_pct, _ = _kelly_fraction("bull", _KELLY_DEFAULTS, state)
        assert kelly_pct == BULL_FULL

    def test_partial_recovery_keeps_floor_then_tier1(self, kelly_db):
        """Intermediate rungs unchanged: -11% → tier-2 floor; -8.5% → tier-1 half."""
        state = kelly_db.update_equity(79_000, CB)
        for _ in range(HALT):
            state, _, _ = _simulate_scan_day(kelly_db, state, 79_000)
        state = kelly_db.update_equity(89_000, CB)  # -11% → tier 2
        assert state["cb_tier"] == 2
        assert _kelly_fraction("bull", _KELLY_DEFAULTS, state)[0] == FLOOR
        state = kelly_db.update_equity(91_500, CB)  # -8.5% → tier 1
        assert state["cb_tier"] == 1
        assert _kelly_fraction("bull", _KELLY_DEFAULTS, state)[0] == BULL_FULL * 0.5

    def test_fresh_tier3_after_recovery_rearms_full_halt(self, kelly_db):
        """A NEW tier-3 episode (from tier < 3) re-arms the full 30-slot halt."""
        state = kelly_db.update_equity(79_000, CB)
        for _ in range(HALT):
            state, _, _ = _simulate_scan_day(kelly_db, state, 79_000)
        state = kelly_db.update_equity(94_000, CB)   # recover → tier 0
        assert state["cb_tier"] == 0
        state = kelly_db.update_equity(82_000, CB)   # -18% vs 100k HWM → fresh tier 3
        assert state["cb_tier"] == 3
        assert state["halt_remaining"] == HALT
        assert _tier3_entry_blocked(state)

    def test_repinned_tier3_does_not_rearm_halt(self, kelly_db):
        """Staying pinned below tier-3 after halt exhaustion must NOT re-arm
        the counter (that would recreate the deadlock in 30-day cycles)."""
        state = kelly_db.update_equity(79_000, CB)
        for _ in range(HALT):
            state, _, _ = _simulate_scan_day(kelly_db, state, 79_000)
        for _ in range(5):  # more flat scans while still ≤ -12%
            state, kelly_pct, blocked = _simulate_scan_day(kelly_db, state, 79_000)
            assert not blocked
            assert kelly_pct == FLOOR
        assert state["halt_remaining"] == 0
