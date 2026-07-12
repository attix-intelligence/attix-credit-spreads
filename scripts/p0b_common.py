"""scripts/p0b_common.py — shared library for EXP-P0B Tradier fill-quality probes.

Prereg: experiments/EXP-P0B-fill-probes/PREREG.md (committed before any probe).
Everything here is deliberately small and assertion-heavy: the safety
invariants (1-lot hard cap, underlier whitelist, tag discipline, halt flag)
are enforced in this module regardless of what the config or caller says.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compass.live.vrp_contracts import OrderIntent, OrderLeg  # noqa: E402

logger = logging.getLogger("p0b")

ET = ZoneInfo("America/New_York")

TAG_PREFIX = "probe_P0B"
LEVELS = ("mid", "mid_minus_1c", "marketable")
SLOTS = ("A", "B")
ENV_SUFFIX = "EXPP0B"  # exp_env_suffix("EXP-P0B") per railway_worker convention


# ── config ────────────────────────────────────────────────────────────────────

class P0BConfigError(RuntimeError):
    pass


def load_config(path: str | Path) -> Dict[str, Any]:
    """Load and validate the probe config. REFUSES max_contracts != 1."""
    import yaml

    with open(path) as fh:
        cfg = yaml.safe_load(fh)

    if cfg.get("experiment_id") != "EXP-P0B":
        raise P0BConfigError(f"not a P0B config: experiment_id={cfg.get('experiment_id')!r}")

    mc = cfg.get("risk", {}).get("max_contracts")
    if mc != 1:
        raise P0BConfigError(
            f"HARD CAP VIOLATION: risk.max_contracts must be 1, got {mc!r}. "
            "The EXP-P0B prereg voids at >1 lot; refusing to run."
        )

    probe = cfg.get("probe", {})
    unders = tuple(probe.get("underliers", ()))
    if not unders or any(u not in ("SPY", "XLI") for u in unders):
        raise P0BConfigError(f"underlier whitelist is (SPY, XLI); config has {unders!r}")
    if tuple(probe.get("levels", ())) != LEVELS:
        raise P0BConfigError(f"levels must be {LEVELS} in this exact order (rotation key)")
    for k in ("entry_cancel_et", "flatten_start_et", "flatten_deadline_et", "eod_check_et"):
        _parse_et(probe[k])  # raises on malformed
    return cfg


def _parse_et(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m), tzinfo=ET)


def now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(ET)


def et_cutoff(cfg: Dict[str, Any], key: str, on: Optional[date] = None) -> datetime:
    t = _parse_et(cfg["probe"][key])
    d = on or now_et().date()
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=ET)


# ── state DB ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
    probe_id TEXT PRIMARY KEY,          -- probe_P0B_<YYYYMMDD>_<slot>
    trade_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    underlier TEXT NOT NULL,
    level TEXT NOT NULL,
    expiration TEXT,
    short_strike REAL, long_strike REAL, width REAL,
    spot_at_placement REAL,
    short_bid REAL, short_ask REAL, long_bid REAL, long_ask REAL,
    mid_credit REAL, natural_credit REAL, quoted_spread REAL,
    limit_credit REAL,
    placed_at TEXT,
    entry_order_id TEXT, entry_idempotency_key TEXT,
    entry_status TEXT DEFAULT 'pending',   -- pending|open|filled|canceled|rejected|skipped
    entry_filled_at TEXT, entry_fill_credit REAL,
    canceled_at TEXT,
    close_order_id TEXT, close_attempts INTEGER DEFAULT 0,
    close_filled_at TEXT, close_fill_debit REAL,
    flat_confirmed_at TEXT,
    pnl_realized REAL, friction_cost REAL,
    skip_reason TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT, probe_id TEXT, kind TEXT,     -- entry|cancel|close
    idempotency_key TEXT, submitted_at TEXT,
    payload TEXT, response TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS status_polls (
    probe_id TEXT, order_id TEXT, polled_at TEXT, raw TEXT, order_status TEXT
);
CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT);
"""


def open_db(cfg: Dict[str, Any]) -> sqlite3.Connection:
    db_path = REPO_ROOT / cfg["db_path"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def is_halted(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT value FROM control WHERE key='halted'").fetchone()
    return row["value"] if row else None


def set_halt(conn: sqlite3.Connection, reason: str) -> None:
    stamp = f"{now_et().isoformat()} :: {reason}"
    conn.execute(
        "INSERT INTO control(key,value) VALUES('halted',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (stamp,))
    conn.commit()
    logger.critical("[P0B HALT] %s", stamp)
    alert(f"🛑 EXP-P0B HALTED: {reason}")


def alert(msg: str) -> None:
    """Best-effort Telegram alert; never raises."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        logger.warning("[alert-no-telegram] %s", msg)
        return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": msg}, timeout=10)
    except Exception as exc:  # noqa: BLE001 — alerts must not break the probe path
        logger.warning("telegram alert failed: %s (%s)", msg, exc)


# ── tags & rotation ───────────────────────────────────────────────────────────

def probe_tag(trade_date: date, slot: str) -> str:
    assert slot in SLOTS, slot
    return f"{TAG_PREFIX}_{trade_date.strftime('%Y%m%d')}_{slot}"


def trading_day_index(trade_date: date, anchor: date) -> int:
    """Weekday count from anchor (holidays skip a slot — harmless for balance)."""
    step = 1 if trade_date >= anchor else -1
    lo, hi = min(anchor, trade_date), max(anchor, trade_date)
    n = sum(1 for o in range(lo.toordinal(), hi.toordinal()) if date.fromordinal(o).weekday() < 5)
    return n * step


def rotation_cell(cfg: Dict[str, Any], trade_date: date, slot: str) -> Tuple[str, str]:
    """Deterministic (underlier, level) for a slot — balanced 6-cell Latin
    rotation over 3 trading days, keyed to the trading-day index (prereg §2.4).
    Day d covers cells (2d, 2d+1) mod 6; underliers alternate across slots."""
    anchor = date.fromisoformat(cfg["probe"]["rotation_anchor"])
    unders = cfg["probe"]["underliers"]
    idx = trading_day_index(trade_date, anchor) * 2 + SLOTS.index(slot)
    cell = idx % 6
    return unders[cell % 2], LEVELS[cell // 2]


# ── level math (prereg §2.3) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SpreadQuote:
    """Per-leg NBBO for a 2-leg put vertical at one instant."""
    short_bid: float
    short_ask: float
    long_bid: float
    long_ask: float

    def valid(self) -> bool:
        return (0 < self.short_bid <= self.short_ask
                and 0 < self.long_bid <= self.long_ask)

    @property
    def natural_credit(self) -> float:
        return round(self.short_bid - self.long_ask, 4)

    @property
    def mid_credit_raw(self) -> float:
        return (self.short_bid + self.short_ask) / 2 - (self.long_bid + self.long_ask) / 2

    @property
    def quoted_spread(self) -> float:
        """Spread-level natural-to-natural width."""
        return round((self.short_ask - self.long_bid) - (self.short_bid - self.long_ask), 4)


def limit_credit_for_level(q: SpreadQuote, level: str) -> float:
    """Limit credit per prereg §2.3. Mid rounds toward the natural (down)."""
    import math
    if level == "marketable":
        return round(q.natural_credit, 2)
    mid_toward_natural = math.floor(q.mid_credit_raw * 100 + 1e-9) / 100
    if level == "mid":
        return round(mid_toward_natural, 2)
    if level == "mid_minus_1c":
        return round(mid_toward_natural - 0.01, 2)
    raise ValueError(f"unknown level {level!r}")


# ── intent construction & guards ──────────────────────────────────────────────

def build_entry_intent(tag: str, underlier: str, expiration: str,
                       short_strike: float, long_strike: float,
                       limit_credit: float, level: str) -> OrderIntent:
    intent = OrderIntent(
        stream=tag,
        symbol=underlier,
        structure="bull_put",
        legs=(
            OrderLeg(side="sell", sec_type="option", symbol=underlier, qty=1,
                     strike=float(short_strike), expiration=expiration, right="P"),
            OrderLeg(side="buy", sec_type="option", symbol=underlier, qty=1,
                     strike=float(long_strike), expiration=expiration, right="P"),
        ),
        contracts=1,
        est_credit=round(float(limit_credit), 2),
        rationale=f"EXP-P0B fill-quality probe level={level} (prereg; not a strategy trade)",
    )
    assert_probe_invariants(intent)
    return intent


def build_close_intent(entry: OrderIntent, attempt: int) -> OrderIntent:
    """Closing intent: buy back the short leg, sell the long leg.
    Each attempt gets a distinct stream suffix -> distinct idempotency key
    (cancel+resubmit ladder; entries are never modified)."""
    intent = OrderIntent(
        stream=f"{entry.stream}_c{attempt}",
        symbol=entry.symbol,
        structure="bull_put",
        legs=(
            OrderLeg(side="buy", sec_type="option", symbol=entry.symbol, qty=1,
                     strike=entry.legs[0].strike, expiration=entry.legs[0].expiration, right="P"),
            OrderLeg(side="sell", sec_type="option", symbol=entry.symbol, qty=1,
                     strike=entry.legs[1].strike, expiration=entry.legs[1].expiration, right="P"),
        ),
        contracts=1,
        rationale="EXP-P0B probe auto-flatten (prereg §2.2: all probes flat by 15:45 ET)",
    )
    assert_probe_invariants(intent, is_close=True)
    return intent


def assert_probe_invariants(intent: OrderIntent, *, is_close: bool = False) -> None:
    """The non-negotiables (prereg §5). Raises AssertionError — callers must
    NOT catch it; a violation is a bug, and submitting is never acceptable."""
    assert intent.contracts == 1, f"1-LOT HARD CAP: contracts={intent.contracts}"
    for leg in intent.legs:
        assert leg.qty == 1, f"1-LOT HARD CAP: leg qty={leg.qty}"
        assert leg.right == "P" and leg.sec_type == "option"
    assert intent.symbol in ("SPY", "XLI"), f"underlier whitelist: {intent.symbol}"
    assert intent.structure == "bull_put"
    assert len(intent.legs) == 2
    assert intent.stream.startswith(TAG_PREFIX), f"untagged probe order: {intent.stream}"
    if not is_close:
        assert intent.est_credit is not None and intent.est_credit >= 0.01, \
            "entry must be a limit order with credit >= $0.01"


# ── executor sink construction (audited path) ────────────────────────────────

def _env(name: str) -> str:
    """Prefer the per-experiment suffixed var, else the plain one."""
    return os.environ.get(f"{name}_{ENV_SUFFIX}") or os.environ.get(name, "")


def build_sink(cfg: Dict[str, Any], *, http: Optional[Any] = None):
    """ExecutorOrderSink on the audited path, with the account identity PINNED:
    the env-provided account must match the config's tradier_live block."""
    from compass.live.executor_order_sink import ExecutorClient, ExecutorOrderSink

    tl = cfg["tradier_live"]
    sink_type = _env("SINK_TYPE") or tl.get("sink_type")
    if sink_type != "executor":
        raise P0BConfigError(f"P0B requires SINK_TYPE=executor, got {sink_type!r}")

    base_url = _env("EXECUTOR_BASE_URL")
    api_key = _env("EXECUTOR_API_KEY")
    account_id = _env("EXECUTOR_ACCOUNT_ID")
    account_type = _env("EXECUTOR_ACCOUNT_TYPE") or "paper"
    if not api_key or not account_id:
        raise P0BConfigError("EXECUTOR_API_KEY / EXECUTOR_ACCOUNT_ID (or _EXPP0B variants) required")
    if account_id != tl["account_id"] or account_type != tl["account_type"]:
        raise P0BConfigError(
            f"account pin mismatch: env=({account_id},{account_type}) "
            f"config=({tl['account_id']},{tl['account_type']}) — refusing (wrong-account guard)")

    client = ExecutorClient(base_url or "http://localhost:38002", api_key,
                            timeout=float(os.environ.get("EXECUTOR_TIMEOUT_S", "15.0")),
                            http=http)
    return ExecutorOrderSink(client, account_id=account_id, account_type=account_type,
                             source_model=cfg.get("executor", {}).get("source_model", "p0b_probe"))


def executor_get(path: str, params: Optional[Dict[str, str]] = None) -> Any:
    """Read-only GET against the executor REST service (quotes + reconciliation).
    Kept out of the sink to avoid touching compass code; GETs need no CSRF."""
    import requests
    base = (_env("EXECUTOR_BASE_URL") or "http://localhost:38002").rstrip("/")
    api_key = _env("EXECUTOR_API_KEY")
    resp = requests.get(f"{base}{path}", params=params or {},
                        headers={"X-API-Key": api_key}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── market data via the executor quotes route (prereg amendment A1) ──────────

def occ_symbol(underlier: str, expiration: str, right: str, strike: float) -> str:
    """OCC option symbol, e.g. SPY260807P00730000."""
    d = date.fromisoformat(expiration)
    return f"{underlier}{d.strftime('%y%m%d')}{right}{int(round(strike * 1000)):08d}"


def executor_quote(cfg: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    """GET /v1/portfolio/quotes/{symbol} — works for underliers AND OCC option
    symbols (venue NBBO from the account's own Tradier session). None on error."""
    try:
        q = executor_get(f"/v1/portfolio/quotes/{symbol}",
                         {"account_id": cfg["tradier_live"]["account_id"]})
        return q if isinstance(q, dict) and "bid" in q else None
    except Exception as exc:  # noqa: BLE001 — a missing quote is a skip, not a crash
        logger.warning("executor quote %s failed: %s", symbol, exc)
        return None


def friday_expirations(today: date, min_dte: int, max_dte: int, target_dte: int) -> List[str]:
    """Candidate Friday expirations in the DTE window, nearest-to-target first.
    Listedness is verified by quoting the actual contract (amendment A1)."""
    out = []
    for delta in range(min_dte, max_dte + 1):
        d = today + timedelta(days=delta)
        if d.weekday() == 4:
            out.append(d)
    out.sort(key=lambda d: abs((d - today).days - target_dte))
    return [d.isoformat() for d in out]


# ── daily caps ────────────────────────────────────────────────────────────────

def orders_today(conn: sqlite3.Connection, trade_date: date) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM orders WHERE submitted_at LIKE ?",
        (f"{trade_date.isoformat()}%",)).fetchone()["c"]


def entries_today(conn: sqlite3.Connection, trade_date: date) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM orders WHERE kind='entry' AND submitted_at LIKE ?",
        (f"{trade_date.isoformat()}%",)).fetchone()["c"]


def record_order(conn: sqlite3.Connection, *, order_id: str, probe_id: str, kind: str,
                 idempotency_key: str, payload: Any, response: Any, status: str) -> None:
    conn.execute(
        "INSERT INTO orders(order_id,probe_id,kind,idempotency_key,submitted_at,payload,response,status) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (order_id, probe_id, kind, idempotency_key, now_et().isoformat(),
         json.dumps(payload, default=str), json.dumps(response, default=str), status))
    conn.commit()
