"""Shared direct-marks multi-leg backtest harness (PROFITABILITY_PROGRAM.md §0).

Consumed by EXP-P1B (calendars/diagonals), EXP-P1C (backspreads/long-vol),
EXP-P1E (broken-wing butterflies / ratios) and EXP-P2B (event structures) —
structures the vertical/IC engine (backtest/backtester.py) cannot represent.

Design (deliberately small and auditable):
  - A position is a list of Legs over real cached marks (`option_daily`).
    No pricing model anywhere: every number is a cached Polygon bar
    (Rule Zero; see docs/DATA_ARCHITECTURE.md).
  - Entry fills use FIX #3 marketable semantics generalized to N legs on
    daily bars: the day's limit is the net OPEN mark minus per-pair slippage
    concession; the order fills AT the limit iff the CLOSE-mark net premium
    traded at/through it. Bars missing an open on any leg book naively and
    are counted in `naive_fallback_entries` (program rule: preregs must
    report the share; > 20 % = fill-uncertain).
  - Daily MTM from close marks; a leg with no bar that day carries its last
    known mark and the day is counted stale (P1B's kill criterion needs
    exactly this statistic).
  - Exits by composable rules evaluated daily in order: profit target on
    net premium, stop on net premium, time stop (calendar days held), and
    front-leg DTE roll-out. Exit fills at close mark minus per-pair exit
    slippage (engine convention), commissions $0.65 per contract per side.

Sign convention: net premium is CASH RECEIVED per 1x structure (credit > 0,
debit < 0). A position's P&L per 1x = entry_net - cost_to_close_net, where
cost_to_close is the same leg list valued with signs flipped.

NOT here (deliberately): position sizing policy, signal generation, capital
compounding rules — callers own those. `run_portfolio` provides a minimal
flat-sizing loop so preregs share one code path for equity/metrics.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date as dt_date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

COMMISSION_PER_CONTRACT = 0.65   # per contract per side, engine parity
ENTRY_SLIP_PER_PAIR = 0.05       # engine `slippage` per 2-leg pair (qty-weighted)
EXIT_SLIP_PER_PAIR = 0.10        # engine `exit_slippage` per pair


# ──────────────────────────────────────────────────────────────────────────────
# Data access
# ──────────────────────────────────────────────────────────────────────────────

class MarksDB:
    """Read-only accessor over option_contracts/option_daily."""

    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def close(self) -> None:
        self.conn.close()

    def bar(self, symbol: str, day: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT open, high, low, close, volume FROM option_daily "
            "WHERE contract_symbol=? AND date=?", (symbol, day)).fetchone()
        if row is None or row[3] is None:
            return None
        return {"open": row[0], "high": row[1], "low": row[2],
                "close": row[3], "volume": row[4]}

    def expirations(self, ticker: str, lo: str, hi: str) -> List[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT expiration FROM option_contracts "
            "WHERE ticker=? AND expiration BETWEEN ? AND ? ORDER BY expiration",
            (ticker, lo, hi))]

    def strikes(self, ticker: str, expiration: str, option_type: str) -> List[float]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT strike FROM option_contracts "
            "WHERE ticker=? AND expiration=? AND option_type=? ORDER BY strike",
            (ticker, expiration, option_type[0].upper()))]

    def contract(self, ticker: str, expiration: str, strike: float,
                 option_type: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT contract_symbol FROM option_contracts "
            "WHERE ticker=? AND expiration=? AND option_type=? "
            "AND ABS(strike - ?) < 1e-9 LIMIT 1",
            (ticker, expiration, option_type[0].upper(), strike)).fetchone()
        return row[0] if row else None

    def trading_days(self, symbol_like_ticker: str, lo: str, hi: str) -> List[str]:
        """Distinct bar dates for an underlier's contracts — the harness clock."""
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT od.date FROM option_daily od "
            "JOIN option_contracts oc USING(contract_symbol) "
            "WHERE oc.ticker=? AND od.date BETWEEN ? AND ? ORDER BY od.date",
            (symbol_like_ticker, lo, hi))]


# ──────────────────────────────────────────────────────────────────────────────
# Structures
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Leg:
    symbol: str          # OCC contract symbol
    side: int            # +1 long (buy), -1 short (sell)
    qty: int = 1         # contracts per 1x structure (ratio legs use >1)
    expiration: str = "" # ISO date; used by dte-based exits

    def __post_init__(self):
        assert self.side in (+1, -1), "side must be +1 or -1"
        assert self.qty >= 1


@dataclass
class Position:
    legs: List[Leg]
    entry_date: str
    entry_net: float                 # premium received per 1x at entry (post-slip)
    contracts: int = 1               # structure multiplier
    entry_commission: float = 0.0
    last_marks: Dict[str, float] = field(default_factory=dict)  # symbol -> last close
    stale_days: int = 0
    mtm_days: int = 0
    meta: dict = field(default_factory=dict)


def _pairs(legs: Sequence[Leg]) -> float:
    """Qty-weighted leg-pairs for slippage scaling (vertical=1, IC=2, 1x2=1.5)."""
    return sum(l.qty for l in legs) / 2.0


def _commission(legs: Sequence[Leg], contracts: int) -> float:
    return COMMISSION_PER_CONTRACT * sum(l.qty for l in legs) * contracts


def net_mark(db: MarksDB, legs: Sequence[Leg], day: str,
             price_field: str = "close",
             carry: Optional[Dict[str, float]] = None) -> Tuple[Optional[float], bool, bool]:
    """Net premium RECEIVED per 1x using `price_field` marks.

    Returns (value, complete, had_field). value is None only if a leg has
    neither a bar today nor a carried mark. `complete` False => at least one
    leg used a carried (stale) mark. `had_field` False => at least one leg's
    bar lacked the requested field (open missing on legacy rows).
    """
    total, complete, had_field = 0.0, True, True
    for leg in legs:
        b = db.bar(leg.symbol, day)
        px = None
        if b is not None:
            px = b.get(price_field)
            if px is None:
                had_field = False
                px = b.get("close")
        if px is None:
            complete = False
            if carry is not None and leg.symbol in carry:
                px = carry[leg.symbol]
            else:
                return None, False, had_field
        if carry is not None and b is not None and b.get("close") is not None:
            carry[leg.symbol] = b["close"]
        total += -leg.side * leg.qty * px   # short leg (+premium), long leg (-premium)
    return total, complete, had_field


# ──────────────────────────────────────────────────────────────────────────────
# FIX #3 marketable entry on daily bars, generalized to N legs
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EntryResult:
    filled: bool
    net: float = 0.0          # premium received per 1x (at the limit) if filled
    naive_fallback: bool = False
    reason: str = ""


def try_enter(db: MarksDB, legs: Sequence[Leg], day: str,
              fill_model: str = "marketable") -> EntryResult:
    """FIX #3 semantics on the day bar: limit = net OPEN mark - slippage
    concession; fills AT the limit iff the CLOSE-mark net traded at/through
    it (close_net >= limit in premium-received terms). Debit structures
    (net < 0) concede by paying more, symmetrically. Missing opens book
    naively at close-mark - slippage and are counted (program §0 caveat)."""
    slip = ENTRY_SLIP_PER_PAIR * _pairs(legs)
    close_net, complete_c, _ = net_mark(db, legs, day, "close")
    if close_net is None or not complete_c:
        return EntryResult(False, reason="missing_leg_bar")
    if fill_model == "naive":
        return EntryResult(True, net=close_net - slip)
    if fill_model != "marketable":
        raise ValueError(f"unknown fill_model {fill_model!r}")
    open_net, complete_o, had_open = net_mark(db, legs, day, "open")
    if open_net is None or not complete_o or not had_open:
        # bar without opens: marketability untestable on close-only data —
        # book naively and COUNT it (caller aggregates naive_fallback share)
        return EntryResult(True, net=close_net - slip, naive_fallback=True)
    limit = open_net - slip
    if limit <= 0 and open_net > 0:
        return EntryResult(False, reason="limit_nonpositive")
    if close_net >= limit - 1e-9:
        return EntryResult(True, net=limit)
    return EntryResult(False, reason="never_marketable")


# ──────────────────────────────────────────────────────────────────────────────
# Exit rules (composable; evaluated in list order, first hit wins)
# ──────────────────────────────────────────────────────────────────────────────
# An exit rule is Callable[[Position, str, float], Optional[str]]:
# (position, day, cost_to_close_net_per_1x) -> reason or None.
# cost_to_close is premium to PAY to close (= close-mark net with signs as
# entered, i.e. entry_net - cost = P&L per 1x before slip/commission).

def profit_target(pt_fraction: float) -> Callable:
    """Close when unrealized profit >= pt_fraction x |entry premium|."""
    def rule(pos: Position, day: str, cost: float) -> Optional[str]:
        if (pos.entry_net - cost) >= pt_fraction * abs(pos.entry_net):
            return f"profit_target_{int(pt_fraction*100)}"
        return None
    return rule


def stop_loss(mult: float) -> Callable:
    """Close when unrealized loss >= mult x |entry premium|."""
    def rule(pos: Position, day: str, cost: float) -> Optional[str]:
        if (cost - pos.entry_net) >= mult * abs(pos.entry_net):
            return f"stop_{mult}x"
        return None
    return rule


def time_stop(max_calendar_days: int) -> Callable:
    def rule(pos: Position, day: str, cost: float) -> Optional[str]:
        held = (dt_date.fromisoformat(day) - dt_date.fromisoformat(pos.entry_date)).days
        if held >= max_calendar_days:
            return f"time_{max_calendar_days}d"
        return None
    return rule


def roll_at_dte(min_dte: int) -> Callable:
    """Close when the NEAREST expiration among legs is <= min_dte away."""
    def rule(pos: Position, day: str, cost: float) -> Optional[str]:
        exps = [l.expiration for l in pos.legs if l.expiration]
        if not exps:
            return None
        dte = (dt_date.fromisoformat(min(exps)) - dt_date.fromisoformat(day)).days
        if dte <= min_dte:
            return f"roll_dte_{min_dte}"
        return None
    return rule


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio loop (flat sizing; callers may drive positions manually instead)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    trades: List[dict]
    equity_curve: List[Tuple[str, float]]
    entered: int = 0
    entry_attempts: int = 0
    unfillable_entries: int = 0
    naive_fallback_entries: int = 0
    stale_mark_days: int = 0
    mtm_days: int = 0

    def summary(self, starting_capital: float) -> dict:
        eq = [v for _, v in self.equity_curve] or [starting_capital]
        peak, max_dd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            max_dd = min(max_dd, (v - peak) / peak * 100 if peak > 0 else -100.0)
        rets = [(eq[i] / eq[i - 1] - 1) for i in range(1, len(eq)) if eq[i - 1] > 0]
        mean = sum(rets) / len(rets) if rets else 0.0
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
        sharpe = mean / math.sqrt(var) * math.sqrt(252) if var > 0 else 0.0
        wins = [t for t in self.trades if t["pnl"] > 0]
        days = max(1, len(self.equity_curve))
        years = days / 252.0
        ending = eq[-1]
        cagr = ((ending / starting_capital) ** (1 / years) - 1) * 100 if ending > 0 else -100.0
        return {
            "total_trades": len(self.trades),
            "total_return_pct": round((ending / starting_capital - 1) * 100, 2),
            "cagr_pct": round(cagr, 2),
            "win_rate_pct": round(len(wins) / len(self.trades) * 100, 2) if self.trades else 0.0,
            "sharpe": round(sharpe, 2),
            "max_dd_pct": round(max_dd, 2),
            "ending_capital": round(ending, 2),
            "entry_attempts": self.entry_attempts,
            "unfillable_entries": self.unfillable_entries,
            "naive_fallback_entries": self.naive_fallback_entries,
            "naive_fallback_share_pct": round(
                100.0 * self.naive_fallback_entries / self.entered, 2) if self.entered else 0.0,
            "stale_mark_day_share_pct": round(
                100.0 * self.stale_mark_days / self.mtm_days, 2) if self.mtm_days else 0.0,
        }


def close_position(db: MarksDB, pos: Position, day: str, reason: str) -> dict:
    cost, complete, _ = net_mark(db, pos.legs, day, "close", carry=pos.last_marks)
    if cost is None:
        cost = sum(-l.side * l.qty * pos.last_marks.get(l.symbol, 0.0) for l in pos.legs)
        reason += "_marked"
    exit_slip = EXIT_SLIP_PER_PAIR * _pairs(pos.legs)
    pnl_1x = (pos.entry_net - cost - exit_slip) * 100.0
    commission = pos.entry_commission + _commission(pos.legs, pos.contracts)
    pnl = pnl_1x * pos.contracts - commission
    return {
        "entry_date": pos.entry_date, "exit_date": day, "exit_reason": reason,
        "entry_net": round(pos.entry_net, 4), "exit_cost": round(cost, 4),
        "contracts": pos.contracts, "commission": round(commission, 2),
        "pnl": round(pnl, 2),
        "stale_days": pos.stale_days, "mtm_days": pos.mtm_days,
        "legs": [(l.side, l.qty, l.symbol) for l in pos.legs],
        **({"meta": pos.meta} if pos.meta else {}),
    }


def run_portfolio(
    db: MarksDB,
    days: Iterable[str],
    signal: Callable[[str, MarksDB, List[Position]], List[Tuple[List[Leg], int, dict]]],
    exit_rules: Sequence[Callable],
    starting_capital: float = 100_000.0,
    fill_model: str = "marketable",
    max_positions: int = 1,
) -> RunResult:
    """Minimal shared loop: for each day — MTM, exits, then entries.

    `signal(day, db, open_positions)` returns candidate structures as
    (legs, contracts, meta) tuples; entries beyond max_positions are ignored.
    Equity = cash + open MTM. Flat sizing: callers fix `contracts` per
    candidate (sizing policy is the caller's, by design).
    """
    res = RunResult(trades=[], equity_curve=[])
    cash = starting_capital
    open_pos: List[Position] = []

    for day in days:
        # 1. exits (evaluate on today's close marks)
        still: List[Position] = []
        for pos in open_pos:
            cost, complete, _ = net_mark(db, pos.legs, day, "close", carry=pos.last_marks)
            pos.mtm_days += 1
            res.mtm_days += 1
            if not complete:
                pos.stale_days += 1
                res.stale_mark_days += 1
            reason = None
            if cost is not None or pos.last_marks:
                eff_cost = cost if cost is not None else sum(
                    -l.side * l.qty * pos.last_marks.get(l.symbol, 0.0) for l in pos.legs)
                for rule in exit_rules:
                    reason = rule(pos, day, eff_cost)
                    if reason:
                        break
            if reason:
                tr = close_position(db, pos, day, reason)
                res.trades.append(tr)
                cash += tr["pnl"]
            else:
                still.append(pos)
        open_pos = still

        # 2. entries
        if len(open_pos) < max_positions:
            for legs, contracts, meta in signal(day, db, open_pos):
                if len(open_pos) >= max_positions:
                    break
                res.entry_attempts += 1
                er = try_enter(db, legs, day, fill_model)
                if not er.filled:
                    if er.reason == "never_marketable":
                        res.unfillable_entries += 1
                    continue
                res.entered += 1
                res.naive_fallback_entries += er.naive_fallback
                pos = Position(legs=list(legs), entry_date=day, entry_net=er.net,
                               contracts=contracts,
                               entry_commission=_commission(legs, contracts),
                               meta=meta or {})
                net_mark(db, legs, day, "close", carry=pos.last_marks)  # seed carries
                open_pos.append(pos)

        # 3. equity
        mtm = 0.0
        for pos in open_pos:
            cost, _, _ = net_mark(db, pos.legs, day, "close", carry=pos.last_marks)
            if cost is None:
                cost = sum(-l.side * l.qty * pos.last_marks.get(l.symbol, 0.0)
                           for l in pos.legs)
            mtm += (pos.entry_net - cost) * 100.0 * pos.contracts - pos.entry_commission
        res.equity_curve.append((day, cash + mtm))

    # 4. force-close leftovers on the final day (honest ledger, no open marks)
    if open_pos:
        last_day = res.equity_curve[-1][0] if res.equity_curve else None
        for pos in open_pos:
            tr = close_position(db, pos, last_day or pos.entry_date, "end_of_window")
            res.trades.append(tr)
            cash += tr["pnl"]
        if res.equity_curve:
            res.equity_curve[-1] = (last_day, cash)
    return res
