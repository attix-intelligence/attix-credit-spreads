#!/usr/bin/env python3
"""EXP-P1E geometry DOA — which broken-wing-butterfly geometries price at a
CREDIT clearing 2x friction? (P0A-methodology measurement, pre-prereg.)

The P0A ledger found the slate's 98/95/broken-1.5x BWB prices at a net DEBIT
everywhere; the program doc requires geometry rework at prereg time. This
measures candidate put-BWB geometries (long upper / short 2x body / long
broken lower wing, strikes as % of parity-inferred spot) on SPY and QQQ,
weekly Friday grid 2020-01..2024-12, close marks. DOA bar: median net credit
< 2 x $35.20 (4-contract friction) => geometry not preregistered as a credit
structure. Measurement only; no strategy backtest; nothing past 2024-12-31.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "options_cache.db"
FRICTION_RT = 35.2
DOA = 2 * FRICTION_RT

# (name, upper_pct, body_pct, lower_pct) — long upper, short 2x body, long lower
GEOMETRIES = [
    ("ledger_ref_98_95_90", 0.98, 0.95, 0.90),
    ("g1_97_93_87",         0.97, 0.93, 0.87),
    ("g2_98_94_88",         0.98, 0.94, 0.88),
    ("g3_96_92_85",         0.96, 0.92, 0.85),
    ("g4_99_96_91",         0.99, 0.96, 0.91),
]
DTES = (30, 15)

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def fridays():
    d = date(2020, 1, 3)
    while d <= date(2024, 12, 27):
        yield d
        d += timedelta(days=7)


def chain(und, dt, exp):
    rows = db.execute(
        """SELECT c.strike, c.option_type, d.close FROM option_daily d
           JOIN option_contracts c USING(contract_symbol)
           WHERE c.ticker=? AND c.expiration=? AND d.date=? AND d.close>0""",
        (und, exp, dt.isoformat())).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def pick_expiry(und, dt, target, lo=10, hi=55):
    exps = [r[0] for r in db.execute(
        "SELECT DISTINCT expiration FROM option_contracts WHERE ticker=? "
        "AND expiration BETWEEN ? AND ? ORDER BY expiration",
        (und, (dt + timedelta(days=lo)).isoformat(), (dt + timedelta(days=hi)).isoformat()))]
    return min(exps, key=lambda e: abs((date.fromisoformat(e) - dt).days - target)) if exps else None


def infer_spot(ch):
    best, spot = None, None
    for k in sorted({k for k, t in ch}):
        c, p = ch.get((k, "C")), ch.get((k, "P"))
        if c is None or p is None:
            continue
        d_ = abs(c - p)
        if best is None or d_ < best:
            best, spot = d_, k
    return spot


def nearest(strikes, target):
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


def main():
    out = {}
    for und in ("SPY", "QQQ"):
        for dte in DTES:
            samples = {g[0]: [] for g in GEOMETRIES}
            for dt in fridays():
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
                for name, up, body, lo_ in GEOMETRIES:
                    ku, kb, kl = (nearest(puts, spot * x) for x in (up, body, lo_))
                    if not (ku and kb and kl and kl < kb < ku):
                        continue
                    pu, pb, pl = ch.get((ku, "P")), ch.get((kb, "P")), ch.get((kl, "P"))
                    if None in (pu, pb, pl):
                        continue
                    net = 2 * pb - pu - pl  # premium received per 1x
                    samples[name].append(net * 100)
            for name, vals in samples.items():
                if len(vals) < 30:
                    continue
                med = statistics.median(vals)
                credit_share = sum(v > 0 for v in vals) / len(vals)
                key = f"{und}_dte{dte}_{name}"
                out[key] = {"n": len(vals), "median_net_usd": round(med, 1),
                            "pct_priced_at_credit": round(credit_share * 100, 1),
                            "doa_clears": bool(med >= DOA)}
                print(f"{key:36s} n={len(vals):3d} median=${med:8.1f} credit%={credit_share*100:5.1f} "
                      f"{'CLEARS' if med >= DOA else 'DOA'}")
    res = ROOT / "experiments" / "wave2" / "results" / "p1e_geometry_doa.json"
    res.parent.mkdir(exist_ok=True)
    res.write_text(json.dumps({"doa_threshold_usd": DOA, "classes": out}, indent=2))
    print(f"-> {res}")


if __name__ == "__main__":
    main()
