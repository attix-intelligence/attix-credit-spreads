#!/usr/bin/env python3
"""EXP-P1F DOA check — TLT CALL credit verticals (friction-ledger extension).

The P0A ledger (research/FRICTION_LEDGER.md) measured TLT put verticals only:
6 of 8 classes DOA; survivors dte30_wide3_2pctOTM ($69 median, 25.5% min-edge)
and dte15_wide3_2pctOTM ($63.5, 27.7%). EXP-P1F preregisters verticals BOTH
directions, so the call side must pass the same DOA test before the prereg is
written (program rule: "DOA check first"; kill criterion: median premium <
2x friction = $35.20 for a 2-leg vertical).

Methodology identical to experiments/honest-fills-fleet/friction_ledger.py:
weekly Friday grid 2020-01-03..2024-12-27, chain closes from options_cache.db,
put-call-parity spot inference, nearest listed strikes, width classes at
~1.2%/~3% of spot, 2%/5% OTM. Measurement only — no strategy backtest, no
data past 2024-12-31.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "options_cache.db"
FRICTION_RT = 17.6      # 2-leg vertical round trip (P0A)
DOA_THRESHOLD = 2 * FRICTION_RT

db = sqlite3.connect(str(DB))
db.execute("PRAGMA query_only=1")


def fridays():
    d = date(2020, 1, 3)
    while d <= date(2024, 12, 27):
        yield d
        d += timedelta(days=7)


def chain(und, dt, exp):
    rows = db.execute(
        """SELECT c.strike, c.option_type, d.close FROM option_daily d
           JOIN option_contracts c ON d.contract_symbol=c.contract_symbol
           WHERE c.ticker=? AND c.expiration=? AND d.date=? AND d.close>0""",
        (und, exp, dt.isoformat())).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def expiries(und, dt, lo, hi):
    return [r[0] for r in db.execute(
        """SELECT DISTINCT expiration FROM option_contracts
           WHERE ticker=? AND expiration BETWEEN ? AND ? ORDER BY expiration""",
        (und, (dt + timedelta(days=lo)).isoformat(), (dt + timedelta(days=hi)).isoformat()))]


def pick_expiry(und, dt, target_dte, lo=10, hi=55):
    exps = expiries(und, dt, lo, hi)
    if not exps:
        return None
    return min(exps, key=lambda e: abs((date.fromisoformat(e) - dt).days - target_dte))


def infer_spot(ch):
    best, spot = None, None
    for k in sorted({k for k, t in ch}):
        c, p = ch.get((k, "C")), ch.get((k, "P"))
        if c is None or p is None:
            continue
        d = abs(c - p)
        if best is None or d < best:
            best, spot = d, k
    return spot


def nearest_strike(strikes, target):
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


def width_classes(spot):
    return {"narrow": max(1.0, round(spot * 0.012)), "wide": max(2.0, round(spot * 0.03))}


def main():
    und = "TLT"
    samples: dict[str, list] = {}
    for dt in fridays():
        for dte in (15, 30):
            exp = pick_expiry(und, dt, dte)
            if not exp:
                continue
            ch = chain(und, dt, exp)
            if len(ch) < 8:
                continue
            spot = infer_spot(ch)
            if not spot:
                continue
            puts = sorted({k for k, t in ch if t == "P"})
            calls = sorted({k for k, t in ch if t == "C"})
            wc = width_classes(spot)
            for wname, w in wc.items():
                for otm, oname in ((0.05, "5pctOTM"), (0.02, "2pctOTM")):
                    # call credit vertical: short call above spot, long further up
                    ks = nearest_strike(calls, spot * (1 + otm))
                    kl = nearest_strike(calls, ks + w) if ks else None
                    if not ks or not kl or kl <= ks:
                        continue
                    cs, cl = ch.get((ks, "C")), ch.get((kl, "C"))
                    if cs is None or cl is None or cs <= cl:
                        continue
                    samples.setdefault(f"call_dte{dte}_{wname}{w:g}_{oname}", []).append((cs - cl) * 100)
                    # cross-check: put side of the same class (should match ledger)
                    kps = nearest_strike(puts, spot * (1 - otm))
                    kpl = nearest_strike(puts, kps - w) if kps else None
                    if kps and kpl and kpl < kps:
                        ps, pl = ch.get((kps, "P")), ch.get((kpl, "P"))
                        if ps is not None and pl is not None and ps > pl:
                            samples.setdefault(f"putxcheck_dte{dte}_{wname}{w:g}_{oname}", []).append((ps - pl) * 100)

    out = {}
    for cls, vals in sorted(samples.items()):
        if len(vals) < 20:
            continue
        med = statistics.median(vals)
        q = statistics.quantiles(vals, n=4)
        out[cls] = {
            "samples": len(vals),
            "median_premium": round(med, 1),
            "iqr": [round(q[0], 1), round(q[2], 1)],
            "friction_rt": FRICTION_RT,
            "min_edge_pct_of_premium": round(FRICTION_RT / med * 100, 1) if med > 0 else None,
            "doa": bool(med < DOA_THRESHOLD),
        }
        print(f"{cls:38s} n={len(vals):3d} median=${med:7.1f} "
              f"min-edge={FRICTION_RT/med*100 if med>0 else float('nan'):5.1f}% "
              f"{'DOA' if med < DOA_THRESHOLD else 'clears'}")

    res = ROOT / "experiments" / "honest-fills-fleet" / "results" / "p1f_doa_check.json"
    res.write_text(json.dumps({"underlier": und, "window": ["2020-01-03", "2024-12-27"],
                               "doa_threshold_usd": DOA_THRESHOLD, "classes": out}, indent=2))
    print(f"-> {res}")


if __name__ == "__main__":
    main()
