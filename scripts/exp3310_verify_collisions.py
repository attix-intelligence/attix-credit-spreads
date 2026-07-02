#!/usr/bin/env python3
"""
EXP-3310 — Zero-collision verifier.

Scans a backtest trade log (produced by exp3310_collision_rebacktest.py) and
counts cases where a SHORT strike of one open trade equals a LONG strike of
another SIMULTANEOUSLY-OPEN trade on the same expiration + option type — the
exact broker-reject condition the leg-collision guard exists to prevent.

Two trades are "simultaneously open" when their [entry_date, exit_date] holding
intervals overlap. Each trade is expanded into its per-OCC-symbol legs:
  bull_put  (P): SELL short_strike (P), BUY long_strike (P)
  bear_call (C): SELL short_strike (C), BUY long_strike (C)
  iron_condor : SELL short_strike (P), BUY long_strike (P),
                SELL call_short_strike (C), BUY call_long_strike (C)

A collision = an open SELL leg on (expiration, strike, type) coincides with an
open BUY leg on the same (expiration, strike, type) held by a different trade.

Usage: python scripts/exp3310_verify_collisions.py <results_json>
Exit code 0 iff zero collisions.
"""
import json
import sys
from datetime import datetime


def _parse_dt(v):
    if isinstance(v, datetime):
        return v
    s = str(v)
    # Trade dates are serialized via default=str -> ISO-ish "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2] if fmt == "%Y-%m-%d" else s[:19], fmt)
        except ValueError:
            continue
    # Last resort: date only
    return datetime.strptime(s[:10], "%Y-%m-%d")


def _exp_key(v):
    return str(v)[:10]  # expiration as YYYY-MM-DD


def legs_of(trade):
    """Yield (option_type, strike, direction) legs. direction 'S'=short, 'L'=long."""
    ot = trade.get("option_type")
    ss, ls = trade.get("short_strike"), trade.get("long_strike")
    if ot == "IC" or trade.get("type") == "iron_condor":
        if ss is not None:
            yield ("P", float(ss), "S")
        if ls is not None:
            yield ("P", float(ls), "L")
        css, cls = trade.get("call_short_strike"), trade.get("call_long_strike")
        if css is not None:
            yield ("C", float(css), "S")
        if cls is not None:
            yield ("C", float(cls), "L")
    else:
        t = "C" if (ot == "C" or trade.get("type") == "bear_call_spread") else "P"
        if ss is not None:
            yield (t, float(ss), "S")
        if ls is not None:
            yield (t, float(ls), "L")


def main():
    path = sys.argv[1]
    with open(path) as f:
        data = json.load(f)
    trades = data.get("trades", data if isinstance(data, list) else [])

    # Normalize
    norm = []
    n_ic = 0
    n_ic_with_calls = 0
    for i, t in enumerate(trades):
        entry = _parse_dt(t["entry_date"])
        exit_ = _parse_dt(t["exit_date"])
        exp = _exp_key(t.get("expiration"))
        legs = list(legs_of(t))
        if t.get("option_type") == "IC" or t.get("type") == "iron_condor":
            n_ic += 1
            if t.get("call_short_strike") is not None and t.get("call_long_strike") is not None:
                n_ic_with_calls += 1
        norm.append({"i": i, "entry": entry, "exit": exit_, "exp": exp, "legs": legs, "raw": t})

    def overlaps(a, b):
        # A position occupies its legs during the ENTRY scans of days [entry, exit).
        # The daily loop runs _manage_positions (closes/expirations/stops) at the
        # start of a day BEFORE the entry scan, so a position exiting on day X is
        # already out of open_positions when new entries are scanned that day — its
        # OCC symbols are freed. Two trades are therefore only "simultaneously held"
        # (as the guard sees them) when their [entry, exit) intervals STRICTLY
        # overlap. A pure handoff (a.exit == b.entry) is not a collision.
        return a["entry"] < b["exit"] and b["entry"] < a["exit"]

    collisions = []
    n = len(norm)
    for a in range(n):
        ta = norm[a]
        a_short = {(ot, k) for (ot, k, d) in ta["legs"] if d == "S"}
        a_long = {(ot, k) for (ot, k, d) in ta["legs"] if d == "L"}
        for b in range(a + 1, n):
            tb = norm[b]
            if ta["exp"] != tb["exp"]:
                continue
            if not overlaps(ta, tb):
                continue
            b_short = {(ot, k) for (ot, k, d) in tb["legs"] if d == "S"}
            b_long = {(ot, k) for (ot, k, d) in tb["legs"] if d == "L"}
            # short of A == long of B, or short of B == long of A
            hit = (a_short & b_long) | (b_short & a_long)
            for (ot, k) in sorted(hit):
                collisions.append({
                    "expiration": ta["exp"],
                    "option_type": ot,
                    "strike": k,
                    "trade_a": ta["i"], "trade_b": tb["i"],
                    "a_entry": ta["entry"].date().isoformat(),
                    "a_exit": ta["exit"].date().isoformat(),
                    "b_entry": tb["entry"].date().isoformat(),
                    "b_exit": tb["exit"].date().isoformat(),
                    "a_type": ta["raw"].get("option_type"),
                    "b_type": tb["raw"].get("option_type"),
                })

    result = {
        "trade_log": path,
        "total_trades": n,
        "iron_condors": n_ic,
        "iron_condors_with_call_legs_in_log": n_ic_with_calls,
        "collision_count": len(collisions),
        "zero_collisions_verified": len(collisions) == 0,
        "sample_collisions": collisions[:20],
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if len(collisions) == 0 else 2)


if __name__ == "__main__":
    main()
