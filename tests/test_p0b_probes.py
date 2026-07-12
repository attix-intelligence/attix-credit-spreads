"""Tests for EXP-P0B fill-quality probes (prereg: experiments/EXP-P0B-fill-probes/PREREG.md).

Focus: the safety invariants that must hold regardless of config or caller —
1-lot hard cap, tag discipline, halt gating, dry-run (no network), rotation
determinism/balance, level math, and the EOD kill criterion.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import p0b_common as pc
from scripts.p0b_common import (
    LEVELS, P0BConfigError, SpreadQuote, assert_probe_invariants, build_close_intent,
    build_entry_intent, limit_credit_for_level, probe_tag, rotation_cell,
)

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "configs" / "probe_p0b_tradier.yaml"


@pytest.fixture()
def cfg():
    return pc.load_config(CONFIG_PATH)


@pytest.fixture()
def conn(cfg, tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "probes.db")
    c.row_factory = sqlite3.Row
    c.executescript(pc.SCHEMA)
    return c


# ── config hard cap ───────────────────────────────────────────────────────────

def test_config_loads_and_live_submit_is_off(cfg):
    assert cfg["risk"]["max_contracts"] == 1
    # `enabled` is stage-managed by explicit GOs (dry run: Maximus 2026-07-12).
    # live_submit=false is the invariant until live orders are explicitly armed;
    # this test is the tripwire that arming is a deliberate, reviewed change.
    assert cfg["live_submit"] is False, "live_submit must stay false until Maximus arms live orders"


def test_loader_refuses_max_contracts_above_one(tmp_path):
    import yaml
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    raw["risk"]["max_contracts"] = 2
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(P0BConfigError, match="HARD CAP"):
        pc.load_config(bad)


def test_loader_refuses_non_whitelisted_underlier(tmp_path):
    import yaml
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    raw["probe"]["underliers"] = ["SPY", "TSLA"]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(P0BConfigError, match="whitelist"):
        pc.load_config(bad)


# ── intent invariants ─────────────────────────────────────────────────────────

def _intent(**kw):
    defaults = dict(tag="probe_P0B_20260713_A", underlier="SPY", expiration="2026-08-14",
                    short_strike=730.0, long_strike=725.0, limit_credit=0.42, level="mid")
    defaults.update(kw)
    return build_entry_intent(defaults["tag"], defaults["underlier"], defaults["expiration"],
                              defaults["short_strike"], defaults["long_strike"],
                              defaults["limit_credit"], defaults["level"])


def test_entry_intent_is_one_lot_tagged_bull_put():
    it = _intent()
    assert it.contracts == 1 and all(l.qty == 1 for l in it.legs)
    assert it.stream.startswith("probe_P0B")
    assert it.structure == "bull_put" and it.est_credit == 0.42


def test_invariants_reject_two_lots():
    it = _intent()
    object.__setattr__(it, "contracts", 2)
    with pytest.raises(AssertionError, match="1-LOT HARD CAP"):
        assert_probe_invariants(it)


def test_invariants_reject_untagged_and_non_whitelisted():
    with pytest.raises(AssertionError, match="whitelist"):
        _intent(underlier="QQQ")
    it = _intent()
    object.__setattr__(it, "stream", "vrp-exp1220-sneaky")
    with pytest.raises(AssertionError, match="untagged"):
        assert_probe_invariants(it)


def test_close_intent_flips_sides_and_bumps_attempt_key():
    entry = _intent()
    close = build_close_intent(entry, attempt=2)
    assert close.stream == entry.stream + "_c2"
    assert close.legs[0].side == "buy" and close.legs[0].strike == 730.0
    assert close.legs[1].side == "sell" and close.legs[1].strike == 725.0
    assert close.contracts == 1


# ── rotation ──────────────────────────────────────────────────────────────────

def test_rotation_deterministic_and_balanced(cfg):
    anchor = date.fromisoformat(cfg["probe"]["rotation_anchor"])
    cells = {}
    d = anchor
    n_days = 0
    while n_days < 30:  # 30 trading days ≈ 60 probes
        if d.weekday() < 5:
            for slot in ("A", "B"):
                cell = rotation_cell(cfg, d, slot)
                assert cell == rotation_cell(cfg, d, slot)  # deterministic
                cells[cell] = cells.get(cell, 0) + 1
            n_days += 1
        d = date.fromordinal(d.toordinal() + 1)
    assert len(cells) == 6, f"all 6 cells must be visited: {cells}"
    assert max(cells.values()) == min(cells.values()) == 10, f"perfectly balanced: {cells}"


def test_probe_tag_format():
    assert probe_tag(date(2026, 7, 13), "A") == "probe_P0B_20260713_A"


# ── level math (prereg §2.3) ─────────────────────────────────────────────────

def test_level_math():
    q = SpreadQuote(short_bid=1.00, short_ask=1.10, long_bid=0.55, long_ask=0.62)
    # mid = 1.05 - 0.585 = 0.465 → toward natural (down) → 0.46
    assert limit_credit_for_level(q, "mid") == 0.46
    assert limit_credit_for_level(q, "mid_minus_1c") == 0.45
    assert limit_credit_for_level(q, "marketable") == pytest.approx(1.00 - 0.62)
    assert q.quoted_spread == pytest.approx((1.10 - 0.55) - (1.00 - 0.62))
    assert q.valid()


def test_invalid_nbbo_detected():
    assert not SpreadQuote(0, 1.1, 0.5, 0.6).valid()          # zero bid
    assert not SpreadQuote(1.2, 1.1, 0.5, 0.6).valid()        # crossed


# ── scheduler gates (no network anywhere) ────────────────────────────────────

def _mk_scheduler():
    from scripts import p0b_probe_scheduler as sched
    return sched


def test_enter_refuses_when_disabled(cfg, conn):
    sched = _mk_scheduler()
    cfg["enabled"] = False
    assert sched.phase_enter(cfg, conn, "A") == 2
    assert conn.execute("SELECT COUNT(*) c FROM probes").fetchone()["c"] == 0


def test_enter_refuses_when_halted(cfg, conn, monkeypatch):
    sched = _mk_scheduler()
    cfg["enabled"] = True
    monkeypatch.setattr(pc, "alert", lambda msg: None)
    pc.set_halt(conn, "test halt")
    assert sched.phase_enter(cfg, conn, "A") == 2


def test_enter_dry_run_places_nothing(cfg, conn, monkeypatch):
    """enabled=true, live_submit=false → dry-run log, no sink construction, no DB order."""
    sched = _mk_scheduler()
    cfg["enabled"] = True
    cfg["live_submit"] = False
    monkeypatch.setattr(sched, "is_rth_now", lambda: True)

    q = SpreadQuote(short_bid=1.00, short_ask=1.10, long_bid=0.55, long_ask=0.62)
    spec = {"underlier": "SPY", "spot": 745.0, "expiration": "2026-08-14",
            "short_strike": 730.0, "long_strike": 725.0, "width": 5.0, "quote": q}
    monkeypatch.setattr(sched, "select_spread", lambda *a, **k: (spec, None))

    def boom(*a, **k):
        raise AssertionError("build_sink must not be called in dry-run")
    monkeypatch.setattr(sched, "build_sink", boom)

    assert sched.phase_enter(cfg, conn, "A") == 0
    assert conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] == 0


class _FakeSink:
    """Records intents; returns canned executor responses. No sockets."""
    def __init__(self, status="submitted"):
        self.submitted = []
        self.status = status
        self.account_id = "tradier_6YA42569"
        self.account_type = "live"
        self.source_model = "p0b_probe"

    def submit(self, intent):
        assert_probe_invariants(intent)  # the sink boundary re-checks
        self.submitted.append(intent)
        return {"status": self.status, "order_id": f"FAKE-{len(self.submitted)}",
                "broker_order_id": f"FAKE-{len(self.submitted)}", "client_order_id": "x"}

    def get_order_status(self, order_id):
        return {"order_status": "open"}

    def get_positions(self):
        return []


def test_enter_live_submits_one_lot_and_records(cfg, conn, monkeypatch):
    sched = _mk_scheduler()
    cfg["enabled"] = True
    cfg["live_submit"] = True
    monkeypatch.setattr(sched, "is_rth_now", lambda: True)
    q = SpreadQuote(short_bid=1.00, short_ask=1.10, long_bid=0.55, long_ask=0.62)
    spec = {"underlier": "SPY", "spot": 745.0, "expiration": "2026-08-14",
            "short_strike": 730.0, "long_strike": 725.0, "width": 5.0, "quote": q}
    monkeypatch.setattr(sched, "select_spread", lambda *a, **k: (spec, None))
    fake = _FakeSink()
    monkeypatch.setattr(sched, "build_sink", lambda cfg: fake)

    assert sched.phase_enter(cfg, conn, "A") == 0
    assert len(fake.submitted) == 1
    it = fake.submitted[0]
    assert it.contracts == 1 and it.stream.startswith("probe_P0B_")
    row = conn.execute("SELECT * FROM probes").fetchone()
    assert row["entry_status"] == "open" and row["limit_credit"] == 0.46
    # idempotency: second call is a no-op
    assert sched.phase_enter(cfg, conn, "A") == 0
    assert len(fake.submitted) == 1


def test_eod_check_halts_on_unflattened_probe(cfg, conn, monkeypatch):
    sched = _mk_scheduler()
    monkeypatch.setattr(pc, "alert", lambda msg: None)
    today = pc.now_et().date().isoformat()
    conn.execute(
        "INSERT INTO probes(probe_id,trade_date,slot,underlier,level,entry_status,entry_order_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (f"probe_P0B_{today.replace('-', '')}_A", today, "A", "SPY", "mid", "filled", "FAKE-1"))
    conn.commit()
    monkeypatch.setattr(sched, "build_sink", lambda cfg: _FakeSink())
    assert sched.phase_eod_check(cfg, conn) == 1
    assert pc.is_halted(conn) is not None
    # and the halt gates the next entry
    cfg["enabled"] = True
    assert sched.phase_enter(cfg, conn, "B") == 2


def test_preview_never_touches_network(cfg, conn, tmp_path):
    """preview with a fixture produces the exact POST body offline."""
    sched = _mk_scheduler()
    fixture = tmp_path / "fx.json"
    fixture.write_text(json.dumps({
        "SPY": {"spot": 745.0, "expiration": "2026-08-14", "short_strike": 730.0,
                "long_strike": 725.0,
                "nbbo": {"short_bid": 1.00, "short_ask": 1.10, "long_bid": 0.55, "long_ask": 0.62}},
        "XLI": {"spot": 152.0, "expiration": "2026-08-14", "short_strike": 149.0,
                "long_strike": 147.0,
                "nbbo": {"short_bid": 0.55, "short_ask": 0.70, "long_bid": 0.28, "long_ask": 0.40}},
    }))
    rc = sched.phase_preview(cfg, conn, for_date=date(2026, 7, 13), fixture=fixture)
    assert rc == 0
