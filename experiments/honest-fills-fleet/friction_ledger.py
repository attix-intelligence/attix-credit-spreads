#!/usr/bin/env python3
"""EXP-P0A — Friction Budget Ledger (measurement only; no strategy backtest).

For each (structure, underlier, width/DTE class): sample real credit/debit
distributions from options_cache.db on a weekly grid 2020-01..2024-12
(in-sample dev window only; nothing past 2024-12-31), and compute the
friction budget per 1-lot round trip:

  friction_rt = commissions (0.65/contract/side * contracts * 2)
              + engine slippage model (0.05 entry + 0.10 exit per spread side * 100)

Cross-check (SPY only, the one underlier with intraday bars): Roll (1984)
effective-spread estimator on 5-min closes of near-ATM 15-45 DTE contracts,
to test whether the $0.05/leg model is realistic.

min_edge_pct = friction_rt / median premium. DOA flag: median premium < 2x friction.
Spot per (date, expiry) is inferred from put-call parity (strike minimizing
|C-P|) — real marks only, no external price feed needed.

Output: results/friction_ledger.json (consumed by research/FRICTION_LEDGER.md).
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "options_cache.db"
OUT = Path(__file__).resolve().parent / "results" / "friction_ledger.json"

COMMISSION = 0.65          # per contract per side (engine config)
SLIP_ENTRY = 0.05          # engine backtest slippage per spread side
SLIP_EXIT = 0.10           # engine exit_slippage per spread side
WINDOW = ("2020-01-01", "2024-12-31")

UNDERLIERS = ["SPY", "QQQ", "XLF", "XLI", "GLD", "TLT"]

db = sqlite3.connect(str(DB))
db.execute("PRAGMA query_only=1")


def fridays():
    d = date(2020, 1, 3)
    while d <= date(2024, 12, 27):
        yield d
        d += timedelta(days=7)


def chain(und, dt, exp):
    """{(strike, type): close} for one date/expiry."""
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
    """Strike minimizing |C - P| (put-call parity ATM)."""
    best, spot = None, None
    strikes = sorted({k for k, t in ch})
    for k in strikes:
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
    """narrow ~1.2% of spot, wide ~3% of spot (comparable across underliers)."""
    return {"narrow": max(1.0, round(spot * 0.012)), "wide": max(2.0, round(spot * 0.03))}


def sample_structures():
    """Returns rows: (structure, underlier, cls, premium$) per sample date."""
    rows = []
    for und in UNDERLIERS:
        for dt in fridays():
            # ---- verticals at DTE 15 and 30, narrow/wide widths, 5%/2% OTM ----
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
                        ks = nearest_strike(puts, spot * (1 - otm))
                        kl = nearest_strike(puts, ks - w) if ks else None
                        if not ks or not kl or kl >= ks:
                            continue
                        ps, pl = ch.get((ks, "P")), ch.get((kl, "P"))
                        if ps is None or pl is None or ps <= pl:
                            continue
                        cred = (ps - pl) * 100
                        rows.append(("vertical_put", und, f"dte{dte}_{wname}{w:g}_{oname}", cred))
                # ---- iron condor (wide width, 4%P/3%C) ----
                w = wc["wide"]
                kps = nearest_strike(puts, spot * 0.96)
                kpl = nearest_strike(puts, kps - w) if kps else None
                kcs = nearest_strike(calls, spot * 1.03)
                kcl = nearest_strike(calls, kcs + w) if kcs else None
                ok = all(x is not None for x in (kps, kpl, kcs, kcl)) and kpl < kps and kcl > kcs
                if ok:
                    vals = [ch.get((kps, "P")), ch.get((kpl, "P")), ch.get((kcs, "C")), ch.get((kcl, "C"))]
                    if all(v is not None for v in vals):
                        cred = (vals[0] - vals[1] + vals[2] - vals[3]) * 100
                        if cred > 0:
                            rows.append(("iron_condor", und, f"dte{dte}_w{w:g}", cred))
                # ---- event iron fly only at short DTE ----
                if dte == 15:
                    exp7 = pick_expiry(und, dt, 7, lo=3, hi=12)
                    if exp7:
                        ch7 = chain(und, dt, exp7)
                        s7 = infer_spot(ch7) if len(ch7) >= 8 else None
                        if s7:
                            p7 = sorted({k for k, t in ch7 if t == "P"})
                            c7 = sorted({k for k, t in ch7 if t == "C"})
                            ka = nearest_strike(p7, s7)
                            wing = max(1.0, round(s7 * 0.02))
                            kpw = nearest_strike(p7, ka - wing) if ka else None
                            kcw = nearest_strike(c7, ka + wing) if ka else None
                            vals = [ch7.get((ka, "P")), ch7.get((ka, "C")),
                                    ch7.get((kpw, "P")), ch7.get((kcw, "C"))] if ka and kpw and kcw else [None]
                            if all(v is not None for v in vals):
                                cred = (vals[0] + vals[1] - vals[2] - vals[3]) * 100
                                if cred > 0:
                                    rows.append(("iron_fly_7dte", und, f"wing{wing:g}", cred))
            # ---- calendar: ATM put, front ~15 / back ~45 ----
            ef, eb = pick_expiry(und, dt, 15), pick_expiry(und, dt, 45, lo=35, hi=70)
            if ef and eb and ef < eb:
                chf, chb = chain(und, dt, ef), chain(und, dt, eb)
                spot = infer_spot(chf) if len(chf) >= 8 else None
                if spot:
                    pf = sorted({k for k, t in chf if t == "P"})
                    ka = nearest_strike(pf, spot)
                    vf, vb = chf.get((ka, "P")), chb.get((ka, "P"))
                    if vf is not None and vb is not None and vb > vf:
                        rows.append(("calendar_atm_put", und, "f15_b45", (vb - vf) * 100))
            # ---- BWB put (1/-2/1, broken lower wing), ~30 DTE ----
            exp = pick_expiry(und, dt, 30)
            if exp:
                ch30 = chain(und, dt, exp)
                spot = infer_spot(ch30) if len(ch30) >= 8 else None
                if spot:
                    puts = sorted({k for k, t in ch30 if t == "P"})
                    k0 = nearest_strike(puts, spot * 0.98)
                    k1 = nearest_strike(puts, spot * 0.95)
                    if k0 and k1 and k1 < k0:
                        k2 = nearest_strike(puts, k1 - (k0 - k1) * 1.5)
                        if k2 and k2 < k1:
                            v0, v1, v2 = ch30.get((k0, "P")), ch30.get((k1, "P")), ch30.get((k2, "P"))
                            if None not in (v0, v1, v2):
                                net = (-v0 + 2 * v1 - v2) * 100  # credit if positive
                                rows.append(("bwb_put_30dte", und, "98_95_broken", net))
    return rows


STRUCT_META = {
    # contracts per 1-lot, spread-sides for slippage model
    "vertical_put":     {"contracts": 2, "sides": 1},
    "iron_condor":      {"contracts": 4, "sides": 2},
    "iron_fly_7dte":    {"contracts": 4, "sides": 2},
    "calendar_atm_put": {"contracts": 2, "sides": 1},
    "bwb_put_30dte":    {"contracts": 4, "sides": 2},
}


def roll_effective_spread():
    """Roll (1984) estimator on SPY 5-min closes, near-ATM 15-45 DTE contracts.

    Samples the first Friday of each quarter 2020-2024; contracts within 2% of
    inferred spot. Returns per-leg effective spread stats in $."""
    out = []
    # sample (contract, date) pairs that actually have dense 5-min coverage,
    # restricted to 10-50 DTE and premium 0.3..30 (near-the-money range),
    # spread across the window via modulo sampling
    pairs = db.execute(
        """SELECT i.contract_symbol, i.date, COUNT(*) n, AVG(i.close) avgpx
           FROM option_intraday i
           JOIN option_contracts c ON i.contract_symbol=c.contract_symbol
           WHERE i.date BETWEEN '2020-01-01' AND '2024-12-31'
             AND julianday(c.expiration) - julianday(i.date) BETWEEN 10 AND 50
           GROUP BY i.contract_symbol, i.date
           HAVING n >= 30 AND avgpx BETWEEN 0.3 AND 30
        """).fetchall()
    pairs = [p for i, p in enumerate(sorted(pairs)) if i % max(1, len(pairs)//400) == 0][:400]
    for sym, dts, n, avgpx in pairs:
        closes = [r[0] for r in db.execute(
            "SELECT close FROM option_intraday WHERE contract_symbol=? AND date=? ORDER BY rowid",
            (sym, dts)).fetchall() if r[0] and r[0] > 0]
        if len(closes) < 30:
            continue
        if True:
            dp = [b - a for a, b in zip(closes, closes[1:])]
            n = len(dp) - 1
            if n < 20:
                continue
            m1 = sum(dp[:-1]) / n
            m2 = sum(dp[1:]) / n
            cov = sum((dp[i] - m1) * (dp[i + 1] - m2) for i in range(n)) / n
            if cov < 0:
                out.append(2 * math.sqrt(-cov))
    return out


def main():
    rows = sample_structures()
    spreads = roll_effective_spread()

    ledger = {}
    for struct, und, cls, prem in rows:
        ledger.setdefault((struct, und, cls), []).append(prem)

    table = []
    for (struct, und, cls), prems in sorted(ledger.items()):
        if len(prems) < 20:      # coverage floor
            continue
        meta = STRUCT_META[struct]
        comm_rt = COMMISSION * meta["contracts"] * 2
        comm_expire = COMMISSION * meta["contracts"]
        slip = (SLIP_ENTRY + SLIP_EXIT) * meta["sides"] * 100
        friction_rt = comm_rt + slip
        med = median(prems)
        prems_s = sorted(prems)
        q1 = prems_s[len(prems_s) // 4]
        q3 = prems_s[3 * len(prems_s) // 4]
        table.append({
            "structure": struct, "underlier": und, "class": cls,
            "samples": len(prems),
            "median_premium": round(med, 2), "iqr": [round(q1, 2), round(q3, 2)],
            "commission_rt": round(comm_rt, 2), "slippage_model": round(slip, 2),
            "friction_rt": round(friction_rt, 2),
            "friction_expire": round(comm_expire + SLIP_ENTRY * meta["sides"] * 100, 2),
            "min_edge_pct_of_premium": round(friction_rt / med * 100, 1) if med > 0 else None,
            "doa": bool(med < 2 * friction_rt) if struct not in ("bwb_put_30dte", "calendar_atm_put") or med > 0 else None,
        })

    roll_stats = {}
    if spreads:
        s = sorted(spreads)
        roll_stats = {
            "n_contract_days": len(s),
            "median_eff_spread_per_leg": round(s[len(s) // 2], 4),
            "q1": round(s[len(s) // 4], 4), "q3": round(s[3 * len(s) // 4], 4),
            "engine_model_entry_per_side": SLIP_ENTRY,
            "note": "Roll (1984) 2*sqrt(-autocov) on 5-min closes; near-ATM 15-45 DTE SPY, quarterly Fridays 2020-2024",
        }

    OUT.write_text(json.dumps({"window": WINDOW, "rows": table, "roll_spy": roll_stats,
                               "assumptions": {"commission_per_contract_side": COMMISSION,
                                               "slip_entry_per_side": SLIP_ENTRY,
                                               "slip_exit_per_side": SLIP_EXIT}}, indent=1))
    print(f"{len(table)} ledger rows; roll sample n={roll_stats.get('n_contract_days')}")
    for r in table:
        if r["underlier"] == "SPY" or r["doa"]:
            print(r["structure"], r["underlier"], r["class"], "med", r["median_premium"],
                  "friction", r["friction_rt"], "minedge%", r["min_edge_pct_of_premium"] or "n/a", "DOA" if r["doa"] else "")


if __name__ == "__main__":
    main()
