"""WS-1 tests: shared/kelly_sizing.py — unit behavior + parity with the
EXP-800 scanner (scripts/exp800_safe_kelly_scanner.py).

The parity test loads the scanner module directly. The scanner runs
``pre_scan_check("EXP-800")`` at import time (line 52), which fingerprints the
live paper config and WRITES a halt into sentinel_state.json on drift — so we
stub ``sentinel.guards`` in sys.modules BEFORE exec'ing the module.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from shared.kelly_sizing import (
    KELLY_DEFAULTS,
    KellyStateDB,
    kelly_fraction,
    regime_for_structure,
    size_contracts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = PROJECT_ROOT / "scripts" / "exp800_safe_kelly_scanner.py"

CB_CFG = KELLY_DEFAULTS["circuit_breakers"]


# ---------------------------------------------------------------------------
# Scanner loading (sentinel stubbed — see module docstring)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scanner():
    saved_guards = sys.modules.get("sentinel.guards")
    saved_sentinel = sys.modules.get("sentinel")

    fake_pkg = types.ModuleType("sentinel")
    fake_guards = types.ModuleType("sentinel.guards")
    fake_guards.pre_scan_check = lambda *a, **k: None
    fake_pkg.guards = fake_guards
    sys.modules["sentinel"] = fake_pkg
    sys.modules["sentinel.guards"] = fake_guards

    try:
        spec = importlib.util.spec_from_file_location(
            "exp800_scanner_under_test", SCANNER_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod
    finally:
        for name, saved in (("sentinel", saved_sentinel), ("sentinel.guards", saved_guards)):
            if saved is not None:
                sys.modules[name] = saved
            else:
                sys.modules.pop(name, None)
        sys.modules.pop("exp800_scanner_under_test", None)


# ---------------------------------------------------------------------------
# Parity: size_contracts ≡ scanner._size_contracts
# ---------------------------------------------------------------------------

SIZING_GRID = [
    # (equity, kelly_pct, width, credit, max_contracts)
    (133_800.0, 9.0, 12.0, 1.75, 30),
    (133_800.0, 7.0, 12.0, 1.75, 30),
    (133_800.0, 4.0, 12.0, 1.75, 30),
    (133_800.0, 9.0, 12.0, 3.20, 30),
    (100_000.0, 7.0, 5.0, 1.10, 30),
    (100_000.0, 2.0, 12.0, 1.50, 30),
    (50_000.0, 9.0, 12.0, 0.90, 5),      # max_contracts cap binds
    (1_000.0, 4.0, 12.0, 1.00, 30),      # floors at 1
    (133_800.0, 9.0, 1.0, 1.50, 30),     # max_loss <= 0 → 1
    (133_800.0, 9.0, 1.5, 1.50, 30),     # max_loss == 0 → 1
    (0.0, 9.0, 12.0, 1.75, 30),
]


def test_size_contracts_parity(scanner):
    for args in SIZING_GRID:
        assert size_contracts(*args) == scanner._size_contracts(*args), args


def test_size_contracts_known_values():
    # 133,800 × 9% = 12,042 ÷ (12 − 1.75)×100 = 1025 → 11
    assert size_contracts(133_800, 9.0, 12.0, 1.75, 30) == 11
    # neutral 7% → 9,366 ÷ 1025 → 9
    assert size_contracts(133_800, 7.0, 12.0, 1.75, 30) == 9
    # bear 4% → 5,352 ÷ 1025 → 5
    assert size_contracts(133_800, 4.0, 12.0, 1.75, 30) == 5
    # cap binds
    assert size_contracts(1_000_000, 9.0, 12.0, 1.75, 30) == 30
    # degenerate max_loss → 1 contract
    assert size_contracts(133_800, 9.0, 1.0, 2.0, 30) == 1
    # tiny equity floors at 1
    assert size_contracts(1_000, 4.0, 12.0, 1.0, 30) == 1


# ---------------------------------------------------------------------------
# Parity: kelly_fraction ≡ scanner._kelly_fraction
# ---------------------------------------------------------------------------

FRACTION_STATES = [
    {"cb_tier": 0, "halt_remaining": 0},
    {"cb_tier": 1, "halt_remaining": 0},
    {"cb_tier": 2, "halt_remaining": 0},
    {"cb_tier": 3, "halt_remaining": 30},
    {"cb_tier": 3, "halt_remaining": 1},
    {"cb_tier": 3, "halt_remaining": 0},  # halt exhausted → sizes again
]


def test_kelly_fraction_parity(scanner):
    kelly_cfg = {
        "regime_fractions": dict(KELLY_DEFAULTS["regime_fractions"]),
        "circuit_breakers": dict(CB_CFG),
    }
    for regime in ("bull", "neutral", "bear", "unknown"):
        for state in FRACTION_STATES:
            ours = kelly_fraction(regime, kelly_cfg, state)
            theirs = scanner._kelly_fraction(regime, kelly_cfg, state)
            assert ours == theirs, (regime, state)


def test_kelly_fraction_tiers():
    cfg = {
        "regime_fractions": {"bull": 9.0, "neutral": 7.0, "bear": 4.0},
        "circuit_breakers": dict(CB_CFG),
    }
    pct, note = kelly_fraction("bull", cfg, {"cb_tier": 0, "halt_remaining": 0})
    assert pct == 9.0

    pct, _ = kelly_fraction("bull", cfg, {"cb_tier": 1, "halt_remaining": 0})
    assert pct == 4.5  # 0.5×

    pct, _ = kelly_fraction("bull", cfg, {"cb_tier": 2, "halt_remaining": 0})
    assert pct == 2.0  # min_fraction floor

    pct, note = kelly_fraction("bull", cfg, {"cb_tier": 3, "halt_remaining": 12})
    assert pct == 0.0
    assert "12" in note

    # halt exhausted at tier 3 → back to full fraction
    pct, _ = kelly_fraction("bear", cfg, {"cb_tier": 3, "halt_remaining": 0})
    assert pct == 4.0

    # unknown regime falls back to neutral
    pct, _ = kelly_fraction("sideways", cfg, {"cb_tier": 0, "halt_remaining": 0})
    assert pct == 7.0


# ---------------------------------------------------------------------------
# Regime mapping
# ---------------------------------------------------------------------------

def test_regime_for_structure():
    assert regime_for_structure("bull_put") == "bull"
    assert regime_for_structure("bull_put_spread") == "bull"
    assert regime_for_structure("bear_call") == "bear"
    assert regime_for_structure("bear_call_spread") == "bear"
    assert regime_for_structure("iron_condor") == "neutral"
    assert regime_for_structure("IRON_CONDOR") == "neutral"
    assert regime_for_structure("weird_condor_thing") == "neutral"
    assert regime_for_structure("") == "neutral"
    assert regime_for_structure(None) == "neutral"


# ---------------------------------------------------------------------------
# KellyStateDB: bootstrap, HWM, tier transitions (incl. parity vs scanner)
# ---------------------------------------------------------------------------

def test_state_db_bootstrap_and_hwm(tmp_path):
    db = KellyStateDB(tmp_path / "exp.db", 100_000.0)
    state = db.load()
    assert state["hwm"] == 100_000.0
    assert state["current_equity"] == 100_000.0
    assert state["cb_tier"] == 0

    state = db.update_equity(110_000.0, CB_CFG)
    assert state["hwm"] == 110_000.0
    assert state["drawdown_pct"] == 0.0

    # dip below HWM but above tier1 → tier stays 0
    state = db.update_equity(105_000.0, CB_CFG)
    assert state["hwm"] == 110_000.0
    assert state["cb_tier"] == 0
    assert state["drawdown_pct"] == pytest.approx(-4.5455, abs=1e-3)

    # persists across reopen
    db2 = KellyStateDB(tmp_path / "exp.db", 100_000.0)
    assert db2.load()["hwm"] == 110_000.0


def _tier_walk(db_cls, db_path, account_size):
    """Run an equity path through tier transitions; return list of (tier, halt)."""
    db = db_cls(db_path, account_size)
    out = []
    for equity in (
        100_000,  # baseline
        91_000,   # -9%  → tier 1
        89_500,   # -10.5% → tier 2
        87_500,   # -12.5% → tier 3 (fresh halt)
        87_000,   # deeper tier 3 — halt NOT reset
        89_500,   # back to tier-2 band — halt preserved (prev_tier==3)
        94_000,   # -6% > recovery -7% → tier 0
        91_000,   # -9% → tier 1 again
        93_000,   # -7% dd > tier1 → tier 0 (tier-1 recovery)
    ):
        s = db.update_equity(float(equity), CB_CFG)
        out.append((s["cb_tier"], s["halt_remaining"]))
    return out


def test_state_db_tier_transitions(tmp_path):
    walk = _tier_walk(KellyStateDB, tmp_path / "ours.db", 100_000.0)
    assert walk == [
        (0, 0),
        (1, 0),
        (2, 0),
        (3, 30),
        (3, 30),
        (2, 30),  # tier-2 band after tier 3 preserves halt
        (0, 0),   # recovered above -7%
        (1, 0),
        (0, 0),
    ]


def test_state_db_tier_transition_parity(scanner, tmp_path):
    ours = _tier_walk(KellyStateDB, tmp_path / "ours.db", 100_000.0)
    theirs = _tier_walk(scanner.KellyStateDB, tmp_path / "theirs.db", 100_000.0)
    assert ours == theirs


def test_decrement_halt(tmp_path):
    db = KellyStateDB(tmp_path / "exp.db", 100_000.0)
    db.update_equity(87_000.0, CB_CFG)  # tier 3, halt 30
    for expected in (29, 28, 27):
        db.decrement_halt()
        assert db.load()["halt_remaining"] == expected

    # not at tier 3 → no-op
    db.update_equity(94_000.0, CB_CFG)  # recovery → tier 0
    before = db.load()["halt_remaining"]
    db.decrement_halt()
    assert db.load()["halt_remaining"] == before


def test_decrement_halt_parity_with_scanner(scanner, tmp_path):
    """Scanner's module-level _decrement_halt(state, db) vs our method."""
    ours = KellyStateDB(tmp_path / "ours.db", 100_000.0)
    theirs = scanner.KellyStateDB(tmp_path / "theirs.db", 100_000.0)
    s1 = ours.update_equity(87_000.0, CB_CFG)
    s2 = theirs.update_equity(87_000.0, CB_CFG)
    assert (s1["cb_tier"], s1["halt_remaining"]) == (s2["cb_tier"], s2["halt_remaining"])

    ours.decrement_halt()
    scanner._decrement_halt(s2, theirs)
    assert ours.load()["halt_remaining"] == theirs.load()["halt_remaining"] == 29
