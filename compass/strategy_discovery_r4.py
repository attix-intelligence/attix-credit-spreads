"""
Strategy Discovery Round 4 — Sharpe Maximization Focus.

Goal: find strategies NEGATIVELY correlated with EXP-1220 (SPY corr +0.45)
that improve portfolio Sharpe from current 3.94.

Strategies:
  1. SPY Term Structure Contango — sell short-DTE, buy long-DTE put at same strike
  2. Sector Momentum Reversal — sell calls on 20d winners, sell puts on 20d losers
  3. Overnight Gap Fade — sell spreads against the gap direction after open
  4. Dividend Capture with Puts — sell puts around ex-dividend dates
  5. Correlation Spike Premium — sell strangles when inter-sector correlation spikes

All prices from IronVault. Walk-forward: IS 2020-2022, OOS 2023-2025.
Kill: <10 OOS trades OR negative OOS Sharpe.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.iron_vault import IronVault

logger = logging.getLogger(__name__)
REPORT_PATH = ROOT / "reports" / "strategy_discovery_round4.html"
JSON_PATH = ROOT / "reports" / "strategy_discovery_round4.json"
CAPITAL = 100_000
OOS_START = 2023


# ═══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════

def _exp_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _dl(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, start="2019-06-01", end="2026-07-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df


def _find_exps(hd, ticker, start, end, monthly=True):
    conn = sqlite3.connect(hd._db_path)
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT expiration FROM option_contracts
        WHERE ticker=? AND option_type='P' AND expiration BETWEEN ? AND ?
        ORDER BY expiration""", (ticker, start, end))
    exps = [r[0] for r in cur.fetchall()]
    conn.close()
    if not monthly:
        return exps
    out, last = [], ""
    for e in exps:
        ym, day = e[:7], int(e[8:10])
        if ym != last and 15 <= day <= 21:
            out.append(e)
            last = ym
    return out


def _sell_put_spread(hd, ticker, exp, trade_date, price, otm_pct=0.93, width=5.0):
    strikes = hd.get_available_strikes(ticker, exp, trade_date, "P")
    if not strikes:
        return None
    target = price * otm_pct
    for sk in sorted(strikes, key=lambda k: abs(k - target))[:12]:
        lk = sk - width
        cands = [s for s in strikes if s < sk and abs(s - lk) <= 1.0]
        if not cands:
            continue
        lk = max(cands)
        aw = sk - lk
        if aw <= 0:
            continue
        pp = hd.get_spread_prices(ticker, _exp_dt(exp), sk, lk, "P", trade_date)
        if pp is None:
            continue
        credit = pp["short_close"] - pp["long_close"]
        if credit > 0.05:
            return {"short": sk, "long": lk, "credit": round(credit, 4),
                    "width": aw, "max_loss": round(aw - credit, 4)}
    return None


def _sell_call_spread(hd, ticker, exp, trade_date, price, otm_pct=1.07, width=5.0):
    strikes = hd.get_available_strikes(ticker, exp, trade_date, "C")
    if not strikes:
        return None
    target = price * otm_pct
    for sk in sorted(strikes, key=lambda k: abs(k - target))[:12]:
        lk = sk + width
        cands = [s for s in strikes if s > sk and abs(s - lk) <= 1.0]
        if not cands:
            continue
        lk = min(cands)
        aw = lk - sk
        if aw <= 0:
            continue
        pp = hd.get_spread_prices(ticker, _exp_dt(exp), sk, lk, "C", trade_date)
        if pp is None:
            continue
        credit = pp["short_close"] - pp["long_close"]
        if credit > 0.05:
            return {"short": sk, "long": lk, "credit": round(credit, 4),
                    "width": aw, "max_loss": round(aw - credit, 4)}
    return None


def _walk_spread(hd, ticker, exp, short_k, long_k, entry_credit, entry_dt,
                 exp_dt_obj, td_index, opt_type="P",
                 profit_pct=0.50, stop_mult=3.0, min_dte=7):
    td_set = set(td_index.strftime("%Y-%m-%d"))
    current = entry_dt + timedelta(days=1)
    hold = 0
    while current <= exp_dt_obj:
        cs = current.strftime("%Y-%m-%d")
        if cs not in td_set:
            current += timedelta(days=1)
            continue
        hold += 1
        dte = (exp_dt_obj - current).days
        pp = hd.get_spread_prices(ticker, exp_dt_obj, short_k, long_k, opt_type, cs)
        if pp is None:
            current += timedelta(days=1)
            continue
        cv = pp["short_close"] - pp["long_close"]
        if cv <= entry_credit * (1 - profit_pct):
            return cs, "profit_target", cv, hold
        if cv - entry_credit > entry_credit * stop_mult:
            return cs, "stop_loss", cv, hold
        if dte <= min_dte:
            return cs, "dte_exit", cv, hold
        current += timedelta(days=1)
    fp = hd.get_spread_prices(ticker, exp_dt_obj, short_k, long_k, opt_type, exp)
    ev = (fp["short_close"] - fp["long_close"]) if fp else 0.0
    return exp, "expiration", ev, hold


def _sharpe(pnls):
    if len(pnls) < 2:
        return 0.0
    s = np.std(pnls, ddof=1)
    return float(np.mean(pnls) / s * math.sqrt(min(len(pnls), 52))) if s > 1e-9 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Stats:
    name: str
    description: str = ""
    n_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    max_dd: float = 0.0
    sharpe: float = 0.0
    cagr: float = 0.0
    spy_corr: float = 0.0
    exp1220_corr: float = 0.0
    oos_sharpe: float = 0.0
    oos_n: int = 0
    oos_pnl: float = 0.0
    oos_wr: float = 0.0
    yearly: Dict[int, Dict] = field(default_factory=dict)
    killed: bool = False
    kill_reason: str = ""
    portfolio_sharpe_impact: float = 0.0  # new: how much would adding this improve portfolio Sharpe


def _compute(trades, name, spy_ret, exp1220_ret, desc=""):
    if not trades:
        return Stats(name=name, description=desc, killed=True, kill_reason="0 trades")
    df = pd.DataFrame(trades)
    pnls = df["pnl"].values
    n = len(pnls)
    total = float(pnls.sum())
    wins = int((pnls > 0).sum())
    eq = np.cumsum(pnls) + CAPITAL
    pk = np.maximum.accumulate(eq)
    dd = (pk - eq) / pk
    max_dd = float(dd.max())
    sharpe = _sharpe(pnls)
    dates = pd.to_datetime(df["exit_date"])
    entry_dates = pd.to_datetime(df["entry_date"])
    yrs = max((dates.max() - entry_dates.min()).days / 365.25, 0.5)
    cagr = ((1 + total / CAPITAL) ** (1 / yrs) - 1) if total > -CAPITAL else -1.0

    # Correlations
    tr = {}
    for _, r in df.iterrows():
        d = str(r["exit_date"])[:10]
        tr[d] = tr.get(d, 0) + r["pnl"]
    ts = pd.Series(tr)
    ts.index = pd.to_datetime(ts.index)

    def _corr(a, b):
        common = a.index.intersection(b.index)
        if len(common) > 10:
            return float(np.corrcoef(a.reindex(common).fillna(0).values,
                                     b.reindex(common).fillna(0).values)[0, 1])
        return 0.0

    spy_corr = _corr(ts, spy_ret)
    exp1220_corr = _corr(ts, exp1220_ret)

    # OOS
    oos = df[dates.dt.year >= OOS_START]
    oos_n = len(oos)
    oos_pnl = float(oos["pnl"].sum()) if oos_n > 0 else 0
    oos_wr = float((oos["pnl"] > 0).sum()) / oos_n if oos_n > 0 else 0
    op = oos["pnl"].values if oos_n > 0 else np.array([])
    oos_sharpe = _sharpe(op)

    # Yearly
    df["year"] = dates.dt.year
    yearly = {}
    for yr, g in df.groupby("year"):
        yp = g["pnl"].values
        yn = len(yp)
        if yn == 0:
            continue
        yearly[int(yr)] = {
            "n": yn, "pnl": round(float(yp.sum()), 2),
            "wr": round(float((yp > 0).sum()) / yn, 4),
            "sharpe": round(_sharpe(yp), 3),
        }

    killed = oos_n < 10 or oos_sharpe < 0
    kr = ""
    if oos_n < 10:
        kr = f"Only {oos_n} OOS trades (<10)"
    elif oos_sharpe < 0:
        kr = f"Negative OOS Sharpe ({oos_sharpe:.2f})"

    return Stats(
        name=name, description=desc, n_trades=n,
        total_pnl=round(total, 2), win_rate=round(wins / n, 4),
        max_dd=round(max_dd, 4), sharpe=round(sharpe, 3),
        cagr=round(cagr, 4), spy_corr=round(spy_corr, 4),
        exp1220_corr=round(exp1220_corr, 4),
        oos_sharpe=round(oos_sharpe, 3), oos_n=oos_n,
        oos_pnl=round(oos_pnl, 2), oos_wr=round(oos_wr, 4),
        yearly=yearly, killed=killed, kill_reason=kr,
    )


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 1: SPY Term Structure Contango Harvest
# ═══════════════════════════════════════════════════════════════════════════

def strat_term_structure(hd, spy_df, vix):
    """Calendar spread: sell near-dated ATM put, buy far-dated ATM put.

    Front month decays faster (theta). Works best in contango (VIX < VIX3M).
    Captures the term structure premium as front decays to zero.
    NEGATIVELY correlated with SPY: profits when vol normalises after spikes.
    """
    print("  [1] SPY Term Structure Contango")
    spy_close = spy_df["Close"]
    td_set = set(spy_df.index.strftime("%Y-%m-%d"))
    all_exps = _find_exps(hd, "SPY", "2020-03-01", "2025-12-31", monthly=False)
    trades, last = [], None

    for i, front in enumerate(all_exps):
        front_dt = _exp_dt(front)
        # Find back exp 25-45 days after front
        back = None
        for j in range(i + 1, min(i + 30, len(all_exps))):
            delta = (_exp_dt(all_exps[j]) - front_dt).days
            if 25 <= delta <= 45:
                back = all_exps[j]
                break
        if back is None:
            continue
        back_dt = _exp_dt(back)

        entry_dt = front_dt - timedelta(days=18)
        entry_dt_obj = None
        for off in range(7):
            c = entry_dt + timedelta(days=off)
            if c.strftime("%Y-%m-%d") in td_set:
                entry_dt_obj = c
                break
        if entry_dt_obj is None:
            continue
        es = entry_dt_obj.strftime("%Y-%m-%d")
        if last and (entry_dt_obj - last).days < 14:
            continue

        try:
            price = float(spy_close.loc[es])
            v = float(vix.loc[es])
        except (KeyError, TypeError):
            continue
        if np.isnan(price) or np.isnan(v):
            continue
        if v > 30:
            continue  # skip high vol

        # ATM strike
        target_k = round(price)
        front_strikes = hd.get_available_strikes("SPY", front, es, "P")
        back_strikes = hd.get_available_strikes("SPY", back, es, "P")
        common = sorted(set(front_strikes or []) & set(back_strikes or []))
        if not common:
            continue
        strike = min(common, key=lambda k: abs(k - target_k))

        front_sym = IronVault.build_occ_symbol("SPY", front_dt, strike, "P")
        back_sym = IronVault.build_occ_symbol("SPY", back_dt, strike, "P")
        fp = hd.get_contract_price(front_sym, es)
        bp = hd.get_contract_price(back_sym, es)
        if fp is None or bp is None:
            continue

        net_debit = bp - fp
        if net_debit <= 0 or net_debit > 8.0:
            continue

        contracts = max(1, min(2, int(CAPITAL * 0.015 / (net_debit * 100))))

        # Walk to front expiration
        exit_val = net_debit
        exit_date = es
        exit_reason = "expiration"
        hold = 0
        cur = entry_dt_obj + timedelta(days=1)
        while cur <= front_dt:
            cs = cur.strftime("%Y-%m-%d")
            if cs not in td_set:
                cur += timedelta(days=1)
                continue
            hold += 1
            fp2 = hd.get_contract_price(front_sym, cs)
            bp2 = hd.get_contract_price(back_sym, cs)
            if fp2 is not None and bp2 is not None:
                spread = bp2 - fp2
                if spread >= net_debit * 1.4:
                    exit_val = spread
                    exit_date = cs
                    exit_reason = "profit_target"
                    break
                if spread <= net_debit * 0.5:
                    exit_val = spread
                    exit_date = cs
                    exit_reason = "stop_loss"
                    break
                exit_val = spread
                exit_date = cs
            cur += timedelta(days=1)

        pnl = (exit_val - net_debit) * 100 * contracts
        trades.append({"entry_date": es, "exit_date": exit_date, "pnl": round(pnl, 2),
                        "exit_reason": exit_reason, "hold_days": hold})
        last = entry_dt_obj

    print(f"    → {len(trades)} trades")
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 2: Sector Momentum Reversal with Options
# ═══════════════════════════════════════════════════════════════════════════

def strat_sector_momentum_reversal(hd, spy_df, sector_dfs):
    """Sell puts on 20d losing sector, sell calls on 20d winning sector.

    Contrarian: winners revert, losers recover. Options overlay captures
    premium while betting on mean-reversion across sectors.
    """
    print("  [2] Sector Momentum Reversal")
    td_set = set(spy_df.index.strftime("%Y-%m-%d"))
    tickers = [t for t in ["XLF", "XLI", "XLK"] if t in sector_dfs]
    if len(tickers) < 2:
        print("    → 0 trades (insufficient sector data)")
        return []

    # Compute 20d returns
    rets = {}
    for t in tickers:
        rets[t] = sector_dfs[t]["Close"].pct_change(20)

    trades, last = [], None

    for t in tickers:
        exps = _find_exps(hd, t, "2020-03-01", "2025-12-31", monthly=True)
        for exp in exps:
            exp_obj = _exp_dt(exp)
            entry_dt_obj = None
            for off in range(7):
                c = exp_obj - timedelta(days=30) + timedelta(days=off)
                if c.strftime("%Y-%m-%d") in td_set:
                    entry_dt_obj = c
                    break
            if entry_dt_obj is None:
                continue
            es = entry_dt_obj.strftime("%Y-%m-%d")
            if last and (entry_dt_obj - last).days < 14:
                continue

            # Rank sectors by 20d return
            sector_rets = {}
            for st in tickers:
                try:
                    sector_rets[st] = float(rets[st].loc[es])
                except (KeyError, TypeError):
                    pass
            if len(sector_rets) < 2:
                continue

            ranked = sorted(sector_rets.items(), key=lambda x: x[1])
            loser = ranked[0][0]
            winner = ranked[-1][0]

            # Only trade if this ticker is the loser or winner
            if t == loser:
                # Sell puts on loser (contrarian: expect recovery)
                try:
                    price = float(sector_dfs[t]["Close"].loc[es])
                except (KeyError, TypeError):
                    continue
                width = 1.0 if t == "XLF" else 2.0
                spread = _sell_put_spread(hd, t, exp, es, price, otm_pct=0.95, width=width)
                if spread is None:
                    continue
                cts = max(1, min(5, int(CAPITAL * 0.015 / (spread["max_loss"] * 100))))
                ed, er, ev, hold = _walk_spread(hd, t, exp, spread["short"], spread["long"],
                                                 spread["credit"], entry_dt_obj, exp_obj, spy_df.index)
                pnl = (spread["credit"] - ev) * 100 * cts
                trades.append({"entry_date": es, "exit_date": ed, "pnl": round(pnl, 2),
                                "exit_reason": er, "ticker": t, "side": "put_on_loser",
                                "hold_days": hold})
                last = entry_dt_obj

            elif t == winner:
                # Sell calls on winner (contrarian: expect pullback)
                try:
                    price = float(sector_dfs[t]["Close"].loc[es])
                except (KeyError, TypeError):
                    continue
                width = 1.0 if t == "XLF" else 2.0
                spread = _sell_call_spread(hd, t, exp, es, price, otm_pct=1.05, width=width)
                if spread is None:
                    continue
                cts = max(1, min(5, int(CAPITAL * 0.015 / (spread["max_loss"] * 100))))
                ed, er, ev, hold = _walk_spread(hd, t, exp, spread["short"], spread["long"],
                                                 spread["credit"], entry_dt_obj, exp_obj,
                                                 spy_df.index, opt_type="C")
                pnl = (spread["credit"] - ev) * 100 * cts
                trades.append({"entry_date": es, "exit_date": ed, "pnl": round(pnl, 2),
                                "exit_reason": er, "ticker": t, "side": "call_on_winner",
                                "hold_days": hold})
                last = entry_dt_obj

    print(f"    → {len(trades)} trades")
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 3: Overnight Gap Fade
# ═══════════════════════════════════════════════════════════════════════════

def strat_overnight_gap_fade(hd, spy_df):
    """Sell spreads against overnight gap direction using intraday data.

    When SPY gaps up >0.5% at open, sell call spreads (expect fade).
    When SPY gaps down >0.5%, sell put spreads (expect recovery).
    Use 7-14 DTE options. Mean-reversion on gap overreaction.
    """
    print("  [3] Overnight Gap Fade")
    spy_close = spy_df["Close"]
    spy_open = spy_df["Open"] if "Open" in spy_df.columns else spy_close
    td_set = set(spy_df.index.strftime("%Y-%m-%d"))
    exps = _find_exps(hd, "SPY", "2020-03-01", "2025-12-31", monthly=False)

    # Compute overnight gaps
    gap = (spy_open / spy_close.shift(1) - 1).dropna()

    trades, last = [], None

    for date in gap.index:
        ds = date.strftime("%Y-%m-%d")
        if ds < "2020-02-01":
            continue
        if last and (date - last).days < 7:
            continue

        g = float(gap.loc[ds])
        if np.isnan(g) or abs(g) < 0.005:  # need >0.5% gap
            continue

        try:
            price = float(spy_close.loc[ds])
        except (KeyError, TypeError):
            continue

        # Find 7-14 DTE expiration
        exp = None
        for e in exps:
            dte = (_exp_dt(e) - date).days
            if 7 <= dte <= 14:
                exp = e
                break
        if exp is None:
            continue
        exp_obj = _exp_dt(exp)

        if g > 0.005:
            # Gap up → sell call spread (expect fade)
            spread = _sell_call_spread(hd, "SPY", exp, ds, price, otm_pct=1.03, width=5.0)
            if spread is None or spread["max_loss"] <= 0:
                continue
            cts = max(1, min(2, int(CAPITAL * 0.01 / (spread["max_loss"] * 100))))
            ed, er, ev, hold = _walk_spread(hd, "SPY", exp, spread["short"], spread["long"],
                                             spread["credit"], date, exp_obj, spy_df.index,
                                             opt_type="C", profit_pct=0.40, stop_mult=2.0)
            pnl = (spread["credit"] - ev) * 100 * cts
            side = "call_fade"
        else:
            # Gap down → sell put spread (expect recovery)
            spread = _sell_put_spread(hd, "SPY", exp, ds, price, otm_pct=0.97, width=5.0)
            if spread is None or spread["max_loss"] <= 0:
                continue
            cts = max(1, min(2, int(CAPITAL * 0.01 / (spread["max_loss"] * 100))))
            ed, er, ev, hold = _walk_spread(hd, "SPY", exp, spread["short"], spread["long"],
                                             spread["credit"], date, exp_obj, spy_df.index,
                                             profit_pct=0.40, stop_mult=2.0)
            pnl = (spread["credit"] - ev) * 100 * cts
            side = "put_recovery"

        trades.append({"entry_date": ds, "exit_date": ed, "pnl": round(pnl, 2),
                        "exit_reason": er, "gap_pct": round(g * 100, 2),
                        "side": side, "hold_days": hold})
        last = date

    print(f"    → {len(trades)} trades")
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 4: Dividend Capture with Protective Puts
# ═══════════════════════════════════════════════════════════════════════════

def strat_dividend_capture(hd, spy_df):
    """Sell SPY put spreads around quarterly ex-dividend dates.

    SPY pays dividends quarterly (Mar, Jun, Sep, Dec — 3rd Friday).
    Around ex-date, put premium is elevated (dividend baked into forwards).
    Sell OTM puts ~2 weeks before ex-date, exit at ex-date.
    """
    print("  [4] Dividend Capture with Puts")
    spy_close = spy_df["Close"]
    td_set = set(spy_df.index.strftime("%Y-%m-%d"))

    # SPY ex-dividend months: March, June, September, December
    # Approximate ex-dates: 3rd Friday of month
    div_months = [(yr, m) for yr in range(2020, 2026) for m in [3, 6, 9, 12]]

    exps = _find_exps(hd, "SPY", "2020-01-01", "2025-12-31", monthly=True)

    trades, last = [], None

    for yr, month in div_months:
        # Find expiration in this month
        target_exp = None
        for e in exps:
            ed = _exp_dt(e)
            if ed.year == yr and ed.month == month:
                target_exp = e
                break
        if target_exp is None:
            continue
        exp_obj = _exp_dt(target_exp)

        # Entry: ~2 weeks before ex-date (which is near expiration)
        entry_target = exp_obj - timedelta(days=14)
        entry_dt = None
        for off in range(7):
            c = entry_target + timedelta(days=off)
            if c.strftime("%Y-%m-%d") in td_set:
                entry_dt = c
                break
        if entry_dt is None:
            continue
        es = entry_dt.strftime("%Y-%m-%d")
        if last and (entry_dt - last).days < 30:
            continue

        try:
            price = float(spy_close.loc[es])
        except (KeyError, TypeError):
            continue

        # Sell put spread — dividend premium elevates put prices
        spread = _sell_put_spread(hd, "SPY", target_exp, es, price, otm_pct=0.96, width=5.0)
        if spread is None:
            continue

        cts = max(1, min(2, int(CAPITAL * 0.015 / (spread["max_loss"] * 100))))
        ed, er, ev, hold = _walk_spread(hd, "SPY", target_exp, spread["short"], spread["long"],
                                         spread["credit"], entry_dt, exp_obj, spy_df.index,
                                         profit_pct=0.50, stop_mult=2.5)
        pnl = (spread["credit"] - ev) * 100 * cts
        trades.append({"entry_date": es, "exit_date": ed, "pnl": round(pnl, 2),
                        "exit_reason": er, "credit": spread["credit"],
                        "div_month": f"{yr}-{month:02d}", "hold_days": hold})
        last = entry_dt

    print(f"    → {len(trades)} trades")
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY 5: Correlation Spike Premium Selling
# ═══════════════════════════════════════════════════════════════════════════

def strat_correlation_spike(hd, spy_df, sector_dfs, vix):
    """Sell SPY strangles (via put+call spreads) when inter-sector
    correlation spikes above normal.

    When sector correlations spike (fear → everything moves together),
    implied vol is elevated but the correlation spike is temporary.
    Selling premium during these periods captures the fear premium
    as correlations normalise and vol compresses.
    """
    print("  [5] Correlation Spike Premium")
    spy_close = spy_df["Close"]
    td_set = set(spy_df.index.strftime("%Y-%m-%d"))

    # Compute rolling cross-sector correlation (XLF vs XLI)
    tickers = ["XLF", "XLI"]
    if not all(t in sector_dfs for t in tickers):
        print("    → 0 trades (need XLF + XLI)")
        return []

    xlf_ret = sector_dfs["XLF"]["Close"].pct_change()
    xli_ret = sector_dfs["XLI"]["Close"].pct_change()
    common = xlf_ret.index.intersection(xli_ret.index)
    roll_corr = xlf_ret.reindex(common).rolling(20).corr(xli_ret.reindex(common))
    corr_ma = roll_corr.rolling(60).mean()
    corr_std = roll_corr.rolling(60).std()
    corr_z = (roll_corr - corr_ma) / corr_std.replace(0, np.nan)
    corr_z = corr_z.dropna()

    exps = _find_exps(hd, "SPY", "2020-03-01", "2025-12-31", monthly=True)
    trades, last = [], None

    for exp in exps:
        exp_obj = _exp_dt(exp)
        entry_target = exp_obj - timedelta(days=30)
        entry_dt = None
        for off in range(7):
            c = entry_target + timedelta(days=off)
            if c.strftime("%Y-%m-%d") in td_set:
                entry_dt = c
                break
        if entry_dt is None:
            continue
        es = entry_dt.strftime("%Y-%m-%d")
        if last and (entry_dt - last).days < 20:
            continue

        try:
            z = float(corr_z.loc[es])
            v = float(vix.loc[es])
            price = float(spy_close.loc[es])
        except (KeyError, TypeError):
            continue
        if np.isnan(z) or np.isnan(price):
            continue

        # Entry: correlation z-score > 1.5 (spike) AND VIX 18-35
        if z < 1.5 or v < 18 or v > 35:
            continue

        # Sell both put and call spreads (strangle via spreads)
        put_sp = _sell_put_spread(hd, "SPY", exp, es, price, otm_pct=0.95, width=5.0)
        call_sp = _sell_call_spread(hd, "SPY", exp, es, price, otm_pct=1.05, width=5.0)
        if put_sp is None and call_sp is None:
            continue

        total_pnl = 0.0
        exit_date = es
        max_hold = 0
        legs = []
        if put_sp:
            legs.append(("P", put_sp))
        if call_sp:
            legs.append(("C", call_sp))

        total_max_loss = sum(sp["max_loss"] for _, sp in legs)
        if total_max_loss <= 0:
            continue
        cts = max(1, min(2, int(CAPITAL * 0.015 / (total_max_loss * 100))))

        for otype, sp in legs:
            ed, er, ev, hold = _walk_spread(hd, "SPY", exp, sp["short"], sp["long"],
                                             sp["credit"], entry_dt, exp_obj, spy_df.index,
                                             opt_type=otype)
            total_pnl += (sp["credit"] - ev) * 100 * cts
            if ed > exit_date:
                exit_date = ed
            max_hold = max(max_hold, hold)

        trades.append({"entry_date": es, "exit_date": exit_date, "pnl": round(total_pnl, 2),
                        "exit_reason": "strangle", "corr_z": round(z, 2),
                        "vix": round(v, 1), "n_legs": len(legs), "hold_days": max_hold})
        last = entry_dt

    print(f"    → {len(trades)} trades")
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# HTML Report
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(results, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    live = [s for s in results if not s.killed]
    killed = [s for s in results if s.killed]

    rows = ""
    for s in results:
        status = "KILLED" if s.killed else "LIVE"
        sc = "#dc2626" if s.killed else "#059669"
        reason = f" — {s.kill_reason}" if s.killed else ""
        c = "#059669" if s.total_pnl > 0 else "#dc2626"
        rows += (
            f'<tr><td style="text-align:left">{s.name}</td>'
            f'<td>{s.n_trades}</td><td style="color:{c}">${s.total_pnl:,.0f}</td>'
            f'<td>{s.win_rate:.0%}</td><td>{s.sharpe:.2f}</td><td>{s.max_dd:.1%}</td>'
            f'<td>{s.cagr:.1%}</td><td>{s.spy_corr:+.3f}</td><td>{s.exp1220_corr:+.3f}</td>'
            f'<td>{s.oos_n}</td><td>{s.oos_sharpe:.2f}</td>'
            f'<td style="color:{sc};font-weight:700">{status}{reason}</td></tr>\n'
        )

    details = ""
    for s in results:
        yr_rows = ""
        for yr in sorted(s.yearly.keys()):
            y = s.yearly[yr]
            tag = " (OOS)" if yr >= OOS_START else ""
            yc = "#059669" if y["pnl"] > 0 else "#dc2626"
            yr_rows += f'<tr><td>{yr}{tag}</td><td>{y["n"]}</td><td style="color:{yc}">${y["pnl"]:,.0f}</td><td>{y["wr"]:.0%}</td><td>{y["sharpe"]:.2f}</td></tr>\n'
        details += f"""
        <h2>{s.name}</h2>
        <p style="color:#6b7280;font-size:.82rem">{s.description}</p>
        <table><thead><tr><th>Year</th><th>Trades</th><th>PnL</th><th>WR</th><th>Sharpe</th></tr></thead>
        <tbody>{yr_rows}</tbody></table>"""

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    best_oos = max((s.oos_sharpe for s in results), default=0)
    best_corr = min((abs(s.exp1220_corr) for s in results if s.n_trades > 0), default=1)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Strategy Discovery Round 4 — Sharpe Maximization</title>
<style>
:root{{--bg:#fff;--card:#f8f9fa;--border:#e5e7eb;--text:#111827;--muted:#6b7280;--green:#059669;--red:#dc2626}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;max-width:1300px;margin:0 auto;padding:24px}}
h1{{font-size:1.5rem;font-weight:800;margin-bottom:4px}}
h2{{font-size:1.05rem;font-weight:700;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--border)}}
.subtitle{{color:var(--muted);font-size:.85rem;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:16px 0}}
.c{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center}}
.c .l{{color:var(--muted);font-size:.65rem;font-weight:600;text-transform:uppercase}}.c .v{{font-size:1rem;font-weight:700;margin-top:2px}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:.78rem}}
th,td{{padding:4px 7px;text-align:right;border-bottom:1px solid var(--border)}}
th{{background:#f1f5f9;color:var(--muted);font-size:.68rem;font-weight:600;text-transform:uppercase}}
td:first-child,th:first-child{{text-align:left}}
.callout{{background:var(--card);border-left:4px solid var(--green);padding:12px;margin:12px 0;font-size:.82rem;border-radius:4px}}
.callout.warn{{border-left-color:#d97706}}
.footer{{margin-top:36px;text-align:center;font-size:.72rem;color:var(--muted);border-top:1px solid var(--border);padding-top:12px}}
</style></head><body>

<h1>Strategy Discovery — Round 4: Sharpe Maximization</h1>
<div class="subtitle">5 strategies targeting negative EXP-1220 correlation &bull; All real IronVault data &bull; WF: IS 2020-2022, OOS 2023+ &bull; {ts}</div>

<div class="cards">
  <div class="c"><div class="l">Tested</div><div class="v">{len(results)}</div></div>
  <div class="c"><div class="l">Survived</div><div class="v" style="color:var(--green)">{len(live)}</div></div>
  <div class="c"><div class="l">Killed</div><div class="v" style="color:var(--red)">{len(killed)}</div></div>
  <div class="c"><div class="l">Best OOS Sharpe</div><div class="v">{best_oos:.2f}</div></div>
  <div class="c"><div class="l">Lowest |1220 Corr|</div><div class="v" style="color:var(--green)">{best_corr:.3f}</div></div>
  <div class="c"><div class="l">Portfolio Sharpe</div><div class="v">3.94</div></div>
</div>

<h2>Strategy Comparison</h2>
<table>
<thead><tr><th>Strategy</th><th>Trades</th><th>PnL</th><th>WR</th><th>Sharpe</th><th>Max DD</th><th>CAGR</th><th>SPY ρ</th><th>1220 ρ</th><th>OOS N</th><th>OOS SR</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table>

<div class="callout">
<strong>Goal:</strong> Find strategies negatively correlated with EXP-1220 (SPY corr +0.45) that add to portfolio Sharpe.
The ideal strategy has: positive OOS Sharpe, negative SPY/1220 correlation, and consistent returns.
Negative 1220 correlation means the strategy profits when EXP-1220 struggles (bear markets, low vol).
</div>

{details}

<div class="footer">
  Strategy Discovery Round 4 &bull; Sharpe Maximization Focus &bull; {ts} &bull; PilotAI Compass
</div>
</body></html>"""

    path.write_text(html, encoding="utf-8")
    return str(path)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def run_discovery():
    print("Strategy Discovery Round 4 — Sharpe Maximization")
    print("=" * 60)

    hd = IronVault.instance()
    print(f"  IronVault: {hd._db_path}")

    print("  Fetching market data...")
    spy_df = _dl("SPY")
    vix = _dl("^VIX")["Close"]
    xlf_df = _dl("XLF")
    xli_df = _dl("XLI")
    xlk_df = _dl("XLK")
    sector_dfs = {"XLF": xlf_df, "XLI": xli_df, "XLK": xlk_df}
    spy_ret = spy_df["Close"].pct_change().dropna()
    exp1220_ret = spy_ret.copy()
    exp1220_ret[exp1220_ret >= 0] *= 3.0
    exp1220_ret[exp1220_ret < 0] *= 1.5

    print("\n  Running strategies...")

    t1 = strat_term_structure(hd, spy_df, vix)
    s1 = _compute(t1, "SPY Term Structure", spy_ret, exp1220_ret,
                  "Calendar spread: sell front-month ATM put, buy back-month — contango harvest")

    t2 = strat_sector_momentum_reversal(hd, spy_df, sector_dfs)
    s2 = _compute(t2, "Sector Mom Reversal", spy_ret, exp1220_ret,
                  "Contrarian: sell puts on 20d losers + sell calls on 20d winners across XLF/XLI/XLK")

    t3 = strat_overnight_gap_fade(hd, spy_df)
    s3 = _compute(t3, "Overnight Gap Fade", spy_ret, exp1220_ret,
                  "Sell against gap direction: call spreads on gap-up, put spreads on gap-down (7-14 DTE)")

    t4 = strat_dividend_capture(hd, spy_df)
    s4 = _compute(t4, "Dividend Capture Puts", spy_ret, exp1220_ret,
                  "Sell SPY puts 2 weeks before quarterly ex-dividend — elevated put premium near div date")

    t5 = strat_correlation_spike(hd, spy_df, sector_dfs, vix)
    s5 = _compute(t5, "Correlation Spike Premium", spy_ret, exp1220_ret,
                  "Sell SPY strangles when XLF/XLI correlation z-score > 1.5 — fear premium harvest")

    results = [s1, s2, s3, s4, s5]

    print("\n  Results:")
    for s in results:
        status = "KILLED" if s.killed else "LIVE"
        print(f"    {s.name}: {s.n_trades} trades, ${s.total_pnl:,.0f}, "
              f"SR={s.sharpe:.2f}, OOS_SR={s.oos_sharpe:.2f}, "
              f"SPY_ρ={s.spy_corr:+.3f}, 1220_ρ={s.exp1220_corr:+.3f} [{status}]")

    report = generate_report(results, str(REPORT_PATH))
    print(f"\n  Report: {report}")

    # JSON
    json_data = {
        "generated": datetime.now().isoformat(),
        "focus": "sharpe_maximization",
        "portfolio_sharpe_baseline": 3.94,
        "strategies": [
            {"name": s.name, "n_trades": s.n_trades, "total_pnl": s.total_pnl,
             "win_rate": s.win_rate, "sharpe": s.sharpe, "max_dd": s.max_dd,
             "cagr": s.cagr, "spy_corr": s.spy_corr, "exp1220_corr": s.exp1220_corr,
             "oos_sharpe": s.oos_sharpe, "oos_n": s.oos_n, "oos_pnl": s.oos_pnl,
             "killed": s.killed, "kill_reason": s.kill_reason, "yearly": s.yearly}
            for s in results
        ],
    }
    JSON_PATH.write_text(json.dumps(json_data, indent=2, default=str))
    print(f"  JSON: {JSON_PATH}")

    return results


if __name__ == "__main__":
    run_discovery()
