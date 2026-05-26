"""
EXP-3290 — Test Hypothesis H3 (Terstegge 2025 overnight VRP mechanism).

Reference: research/DEALER_GEX_LITERATURE.md §6, H3.
Claim: Overnight-only SPY put-credit spreads retain VRP that intraday-entry
strategies cannot harvest, because dealer hedging constraints bind hardest
overnight when deltas cannot be reset.

Falsifiable pre-registered test:
    SR_overnight − SR_intraday > 0.30  (net of transaction costs)
    AND SR_overnight ≥ 0.7

Method:
    For each trading day t in 2023-01-01 .. 2025-12-31:
      Find the nearest SPY put expiration ≥1 calendar day out (1-7 DTE).
      Pick the ~5% OTM short strike, 5-wide long strike.
      OVERNIGHT  leg: sell at close[t], buy back at open[t+1].
      INTRADAY   leg: sell at open[t],  buy back at close[t].
    Compute Sharpe per leg using per-trade arithmetic returns, annualised
    by sqrt(trades_per_year).  Apply per-spread transaction cost.

Data: IronVault option_daily OHLC (real prices, Rule Zero compliant).
Output: compass/reports/exp3290_overnight_entry_test.json
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from shared.iron_vault import IronVault

ROOT = Path(__file__).resolve().parent.parent
TRADING_DAYS = 252

# Hypothesis test parameters (pre-registered)
START_DATE = "2023-01-01"
END_DATE   = "2025-12-31"
OTM_PCT    = 0.95           # short strike 5% OTM
WIDTH      = 5.0            # long strike $5 below short
MIN_DTE    = 1              # ≥1 calendar day to expiration
MAX_DTE    = 7              # ≤7 calendar days
TXN_PER_SPREAD = 2.00       # $2 per round-trip spread (4 legs ~ 50¢ each, conservative)
H3_SR_GAP    = 0.30         # SR_overnight − SR_intraday must exceed this
H3_OVERNIGHT_MIN = 0.7      # SR_overnight must clear this


# ──────────────────────────────────────────────────────────────────────────
# IronVault helpers
# ──────────────────────────────────────────────────────────────────────────

def _conn(hd: IronVault) -> sqlite3.Connection:
    return sqlite3.connect(hd._db_path)


def _td_set(spy_df: pd.DataFrame) -> set:
    return set(spy_df.index.strftime("%Y-%m-%d"))


def get_spy_ohlc(start: str, end: str) -> pd.DataFrame:
    """Pull SPY OHLC from yfinance (used to pick strikes near close[t] / open[t])."""
    import yfinance as yf
    df = yf.download("SPY", start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close"]].astype(float)


def find_expirations(hd: IronVault, start: str, end: str) -> List[str]:
    with _conn(hd) as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT expiration FROM option_contracts "
            "WHERE ticker='SPY' AND option_type='P' "
            "AND expiration BETWEEN ? AND ? ORDER BY expiration",
            (start, end)).fetchall()]


def get_strikes_for_exp(hd: IronVault, exp: str) -> List[float]:
    with _conn(hd) as c:
        return sorted(r[0] for r in c.execute(
            "SELECT DISTINCT strike FROM option_contracts "
            "WHERE ticker='SPY' AND option_type='P' AND expiration=?",
            (exp,)).fetchall())


def get_option_ohlc(hd: IronVault, contract_symbol: str, date: str) -> Optional[Dict]:
    with _conn(hd) as c:
        r = c.execute(
            "SELECT open, high, low, close, volume FROM option_daily "
            "WHERE contract_symbol=? AND date=?", (contract_symbol, date)).fetchone()
    if r is None:
        return None
    o, h, l, cl, v = r
    if cl is None:
        return None
    return {"open": o, "high": h, "low": l, "close": cl, "volume": v}


def _contract_symbol(exp: str, strike: float) -> str:
    yy = exp[2:4]; mm = exp[5:7]; dd = exp[8:10]
    k = int(round(strike * 1000))
    return f"O:SPY{yy}{mm}{dd}P{k:08d}"


def select_spread(hd: IronVault, exp: str, ref_price: float,
                  trade_date: str) -> Optional[Dict]:
    """Pick (short, long) strikes near OTM_PCT * ref_price, with width=$5.
    Returns dict with strikes + contract symbols, or None if not found.
    Requires both legs to have OHLC data on trade_date."""
    strikes = get_strikes_for_exp(hd, exp)
    if not strikes:
        return None
    target = ref_price * OTM_PCT
    for sk in sorted(strikes, key=lambda k: abs(k - target))[:12]:
        lk = sk - WIDTH
        if lk not in strikes:
            cands = [s for s in strikes if s < sk and abs(s - lk) <= 1.0]
            if not cands:
                continue
            lk = max(cands)
        if sk - lk <= 0:
            continue
        short_sym = _contract_symbol(exp, sk)
        long_sym  = _contract_symbol(exp, lk)
        sd = get_option_ohlc(hd, short_sym, trade_date)
        ld = get_option_ohlc(hd, long_sym,  trade_date)
        if sd is None or ld is None:
            continue
        # Need positive entry credit at this point (using close as a sanity check)
        credit_close = sd["close"] - ld["close"]
        if credit_close <= 0.05:
            continue
        return {"short": sk, "long": lk,
                "short_sym": short_sym, "long_sym": long_sym,
                "width": sk - lk}
    return None


# ──────────────────────────────────────────────────────────────────────────
# Two-leg backtest
# ──────────────────────────────────────────────────────────────────────────

def run_h3_backtest(hd: IronVault, spy: pd.DataFrame) -> Dict:
    """Build paired overnight vs intraday trades for each eligible day."""
    td_set = _td_set(spy)
    exps_all = find_expirations(hd, START_DATE, END_DATE)
    exps_dt  = [(e, datetime.strptime(e, "%Y-%m-%d")) for e in exps_all]

    overnight_trades: List[Dict] = []
    intraday_trades:  List[Dict] = []
    skipped = {"no_exp": 0, "no_spread": 0, "no_overnight_quote": 0,
               "no_intraday_quote": 0, "no_next_day": 0}

    # Iterate every trading day with both today's and tomorrow's data
    sorted_days = sorted(td_set)
    for i, d in enumerate(sorted_days[:-1]):
        if d < START_DATE or d > END_DATE:
            continue
        d_dt = datetime.strptime(d, "%Y-%m-%d")
        d_next = sorted_days[i + 1]

        try:
            spy_open  = float(spy.loc[d, "Open"])
            spy_close = float(spy.loc[d, "Close"])
        except KeyError:
            continue
        if math.isnan(spy_open) or math.isnan(spy_close):
            continue

        # Pick nearest expiration in [MIN_DTE, MAX_DTE]
        cand_exps = [(e, edt) for (e, edt) in exps_dt
                     if MIN_DTE <= (edt - d_dt).days <= MAX_DTE]
        if not cand_exps:
            skipped["no_exp"] += 1
            continue
        exp, exp_dt = cand_exps[0]  # nearest

        # OVERNIGHT leg: select strikes using spy_close, then close[t] → open[t+1]
        ov_spread = select_spread(hd, exp, spy_close, d)
        if ov_spread is not None:
            sd_t  = get_option_ohlc(hd, ov_spread["short_sym"], d)
            ld_t  = get_option_ohlc(hd, ov_spread["long_sym"],  d)
            sd_t1 = get_option_ohlc(hd, ov_spread["short_sym"], d_next)
            ld_t1 = get_option_ohlc(hd, ov_spread["long_sym"],  d_next)
            if (sd_t1 is None or ld_t1 is None
                    or sd_t1["open"] is None or ld_t1["open"] is None):
                # Spread expired worthless or quote missing — handle below
                # If expiration ≤ d_next and short strike > spy_open_next, both legs OTM ⇒ 0
                exp_le_next = exp <= d_next
                try:
                    spy_open_next = float(spy.loc[d_next, "Open"])
                except KeyError:
                    spy_open_next = None
                if (exp_le_next and spy_open_next is not None
                        and ov_spread["short"] < spy_open_next):
                    # Both legs OTM at exit → spread worth 0
                    entry_credit = sd_t["close"] - ld_t["close"]
                    exit_value   = 0.0
                    pnl_gross    = (entry_credit - exit_value) * 100.0
                    pnl_net      = pnl_gross - TXN_PER_SPREAD
                    overnight_trades.append({
                        "date": d, "exit_date": d_next,
                        "short": ov_spread["short"], "long": ov_spread["long"],
                        "exp": exp, "entry_credit": round(entry_credit, 4),
                        "exit_value": exit_value, "pnl_gross": round(pnl_gross, 2),
                        "pnl_net": round(pnl_net, 2),
                        "spy_close_t": spy_close, "spy_open_t1": spy_open_next,
                        "exit_mode": "otm_worthless",
                    })
                else:
                    skipped["no_overnight_quote"] += 1
            else:
                entry_credit = sd_t["close"] - ld_t["close"]
                exit_value   = sd_t1["open"] - ld_t1["open"]
                pnl_gross    = (entry_credit - exit_value) * 100.0
                pnl_net      = pnl_gross - TXN_PER_SPREAD
                overnight_trades.append({
                    "date": d, "exit_date": d_next,
                    "short": ov_spread["short"], "long": ov_spread["long"],
                    "exp": exp, "entry_credit": round(entry_credit, 4),
                    "exit_value": round(exit_value, 4),
                    "pnl_gross": round(pnl_gross, 2), "pnl_net": round(pnl_net, 2),
                    "spy_close_t": spy_close,
                    "spy_open_t1": float(spy.loc[d_next, "Open"]),
                    "exit_mode": "open_quote",
                })
        else:
            skipped["no_spread"] += 1

        # INTRADAY leg: select strikes using spy_open, then open[t] → close[t]
        id_spread = select_spread(hd, exp, spy_open, d)
        if id_spread is not None:
            sd_o = get_option_ohlc(hd, id_spread["short_sym"], d)
            ld_o = get_option_ohlc(hd, id_spread["long_sym"],  d)
            if (sd_o is None or ld_o is None
                    or sd_o["open"] is None or ld_o["open"] is None):
                skipped["no_intraday_quote"] += 1
            else:
                entry_credit = sd_o["open"] - ld_o["open"]
                exit_value   = sd_o["close"] - ld_o["close"]
                if entry_credit <= 0.05:
                    skipped["no_intraday_quote"] += 1
                else:
                    pnl_gross = (entry_credit - exit_value) * 100.0
                    pnl_net   = pnl_gross - TXN_PER_SPREAD
                    intraday_trades.append({
                        "date": d, "exit_date": d,
                        "short": id_spread["short"], "long": id_spread["long"],
                        "exp": exp, "entry_credit": round(entry_credit, 4),
                        "exit_value": round(exit_value, 4),
                        "pnl_gross": round(pnl_gross, 2), "pnl_net": round(pnl_net, 2),
                        "spy_open_t": spy_open, "spy_close_t": spy_close,
                        "exit_mode": "close_quote",
                    })

    return {"overnight": overnight_trades, "intraday": intraday_trades,
            "skipped": skipped}


# ──────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────

def trade_metrics(trades: List[Dict], pnl_key: str = "pnl_net") -> Dict:
    if not trades:
        return {"n": 0}
    pnls = np.array([t[pnl_key] for t in trades], dtype=float)
    n = len(pnls); total = float(pnls.sum())
    wins = int((pnls > 0).sum())
    mu = float(pnls.mean()); sigma = float(pnls.std(ddof=1)) if n > 1 else 1.0

    dates = pd.to_datetime([t["date"] for t in trades])
    span_years = max((dates.max() - dates.min()).days / 365.25, 0.5)
    tpy = n / span_years

    sharpe = mu / sigma * math.sqrt(tpy) if sigma > 1e-9 else 0.0
    down = pnls[pnls < 0]
    ds = float(down.std(ddof=1)) if len(down) > 1 else sigma
    sortino = mu / ds * math.sqrt(tpy) if ds > 1e-9 else 0.0

    # Equity curve & DD on $100K notional (1 contract per trade)
    eq = np.cumsum(pnls) + 100_000.0
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max())

    # Yearly
    df = pd.DataFrame({"y": dates.year, "pnl": pnls})
    yearly = {}
    for yr, grp in df.groupby("y"):
        yp = grp["pnl"].values
        yearly[int(yr)] = {
            "n": int(len(yp)), "pnl": round(float(yp.sum()), 2),
            "wr": round(float((yp > 0).sum()) / len(yp), 3),
            "sharpe": round(float(yp.mean()) / (yp.std(ddof=1) if len(yp) > 1 else 1.0)
                            * math.sqrt(252) if (len(yp) > 1 and yp.std(ddof=1) > 1e-9) else 0.0, 2),
        }

    return {
        "n": n, "total_pnl": round(total, 2),
        "win_rate": round(wins / n, 3), "avg_pnl": round(mu, 2),
        "std_pnl": round(sigma, 2), "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3), "max_dd_pct": round(dd * 100, 2),
        "trades_per_year": round(tpy, 1), "span_years": round(span_years, 2),
        "yearly": yearly,
    }


def bootstrap_sharpe_gap(ov_pnls: np.ndarray, id_pnls: np.ndarray,
                         n_boot: int = 2000, seed: int = 42) -> Dict:
    """Stationary bootstrap of (SR_ov − SR_id) — gives a 95% CI on the gap."""
    rng = np.random.default_rng(seed)
    def _sr(x):
        if len(x) < 2:
            return 0.0
        s = x.std(ddof=1)
        return float(x.mean() / s * math.sqrt(len(x))) if s > 1e-9 else 0.0
    gaps = np.empty(n_boot)
    for b in range(n_boot):
        ov_idx = rng.integers(0, len(ov_pnls), size=len(ov_pnls))
        id_idx = rng.integers(0, len(id_pnls), size=len(id_pnls))
        gaps[b] = _sr(ov_pnls[ov_idx]) - _sr(id_pnls[id_idx])
    return {"mean": round(float(gaps.mean()), 3),
            "p025": round(float(np.percentile(gaps, 2.5)), 3),
            "p500": round(float(np.percentile(gaps, 50)), 3),
            "p975": round(float(np.percentile(gaps, 97.5)), 3),
            "pr_gap_gt_threshold": round(float((gaps > H3_SR_GAP).mean()), 3)}


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def run() -> Dict:
    print("EXP-3290 — H3 (Terstegge overnight VRP) test")
    print("=" * 60)
    hd = IronVault.instance()

    print(f"Loading SPY OHLC {START_DATE} .. {END_DATE} ...")
    spy = get_spy_ohlc(START_DATE, END_DATE)
    print(f"  {len(spy)} trading days")

    print("Running paired overnight/intraday backtest ...")
    bt = run_h3_backtest(hd, spy)
    ov = bt["overnight"]; idt = bt["intraday"]
    print(f"  overnight trades: {len(ov)}  |  intraday trades: {len(idt)}")
    print(f"  skipped: {bt['skipped']}")

    ov_gross = trade_metrics(ov, "pnl_gross")
    ov_net   = trade_metrics(ov, "pnl_net")
    id_gross = trade_metrics(idt, "pnl_gross")
    id_net   = trade_metrics(idt, "pnl_net")

    print()
    print(f"  Overnight — gross Sharpe {ov_gross.get('sharpe', 0):.2f} | net {ov_net.get('sharpe', 0):.2f}")
    print(f"             win {ov_net.get('win_rate', 0):.0%} | total ${ov_net.get('total_pnl', 0):,.0f}")
    print(f"  Intraday  — gross Sharpe {id_gross.get('sharpe', 0):.2f} | net {id_net.get('sharpe', 0):.2f}")
    print(f"             win {id_net.get('win_rate', 0):.0%} | total ${id_net.get('total_pnl', 0):,.0f}")

    # H3 pre-registered test
    sr_ov  = ov_net.get("sharpe", 0.0)
    sr_id  = id_net.get("sharpe", 0.0)
    gap    = sr_ov - sr_id
    pass_min  = sr_ov >= H3_OVERNIGHT_MIN
    pass_gap  = gap >= H3_SR_GAP
    h3_pass   = pass_min and pass_gap

    # Bootstrap for CI
    boot = None
    if ov and idt:
        ov_pnls = np.array([t["pnl_net"] for t in ov])
        id_pnls = np.array([t["pnl_net"] for t in idt])
        boot = bootstrap_sharpe_gap(ov_pnls, id_pnls)
        print(f"  Bootstrap gap mean {boot['mean']:.2f} CI95 [{boot['p025']:.2f}, {boot['p975']:.2f}]")

    print()
    print(f"H3 verdict — SR_ov={sr_ov:.2f}  SR_id={sr_id:.2f}  gap={gap:.2f}")
    print(f"  ≥ {H3_OVERNIGHT_MIN}?  {'PASS' if pass_min else 'FAIL'}")
    print(f"  gap ≥ {H3_SR_GAP}? {'PASS' if pass_gap else 'FAIL'}")
    print(f"  OVERALL: {'CONFIRMED' if h3_pass else 'REJECTED'}")

    # Proposed v8a modification
    if h3_pass:
        recommendation = ("Reconfigure exp1220 SPY leg to overnight-only entry: "
                          "sell at 15:55 ET, close at 09:35 ET next session. "
                          "Use 1-7 DTE near-OTM put-credit spreads. "
                          "Expected lift: Sharpe " f"{sr_ov:.2f} vs current intraday-style {sr_id:.2f}.")
    else:
        recommendation = ("Do not migrate exp1220 to overnight-only entry — the "
                          "Terstegge overnight-VRP signal does NOT survive the H3 "
                          "pre-registered cutoffs on SPY 1-7 DTE put spreads (net of "
                          "transaction costs). Keep current intraday-style hold or "
                          "consider de-emphasizing SPX-tracking premium sale and "
                          "leaning further into the XLF/XLI/QQQ sector legs.")

    report = {
        "experiment": "EXP-3290",
        "hypothesis": "H3 — Terstegge 2025 overnight VRP",
        "anchor_paper": "Terstegge (SSRN, 2025)",
        "anchor_doc": "research/DEALER_GEX_LITERATURE.md §6 H3",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "data_source": "IronVault option_daily (real OHLC, Rule Zero)",
        "params": {
            "otm_pct": OTM_PCT, "width": WIDTH,
            "min_dte": MIN_DTE, "max_dte": MAX_DTE,
            "txn_per_spread_usd": TXN_PER_SPREAD,
            "h3_sr_gap_cutoff": H3_SR_GAP,
            "h3_overnight_min": H3_OVERNIGHT_MIN,
        },
        "skipped": bt["skipped"],
        "overnight_gross": ov_gross,
        "overnight_net":   ov_net,
        "intraday_gross":  id_gross,
        "intraday_net":    id_net,
        "h3_test": {
            "sharpe_overnight_net": round(sr_ov, 3),
            "sharpe_intraday_net":  round(sr_id, 3),
            "gap": round(gap, 3),
            "pass_overnight_min": pass_min,
            "pass_gap_threshold": pass_gap,
            "h3_confirmed": h3_pass,
            "bootstrap_gap": boot,
        },
        "recommendation_for_v8a": recommendation,
        "caveats": [
            "Underlying is SPY (ETF), not SPX index — Terstegge's mechanism is "
            "framed on SPX. SPY may carry a retail-flow channel (see H1) that "
            "confounds the overnight-binding-constraint channel.",
            "Entry/exit use IronVault end-of-day OHLC. The 'open' price for a "
            "given contract is the first traded print of that day, which can be "
            "stale for low-volume strikes; ~28.8% of SPY put rows show "
            "open == close (no within-day movement / no early prints).",
            "1-7 DTE puts include 0DTE-like exposures. Strike selection uses "
            "spy_open or spy_close as the reference price; bid-ask is not "
            "explicitly modelled (covered by the $2/spread proxy).",
            "Position sizing is 1 contract / trade. Equity-curve max DD is not "
            "comparable to v8a's $-vol-targeted sizing.",
        ],
    }

    out = ROOT / "compass" / "reports" / "exp3290_overnight_entry_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {out}")
    return report


if __name__ == "__main__":
    run()
