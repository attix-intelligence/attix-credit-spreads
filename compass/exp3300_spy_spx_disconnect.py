"""
EXP-3300 — H1 test: SPY-vs-SPX VRP disconnect (Dew-Becker-Giglio era).

Hypothesis H1 (DEALER_GEX_LITERATURE.md §6):
  "Retail-heavy products (SPY) retain a tradeable short-gamma VRP even
   after Dew-Becker-Giglio (2025) and Heston-Todorov (2024) measured
   SPX VRP ≈ 0 post-2009."

DATA-RANGE CAVEAT
-----------------
IronVault SPY option_daily begins 2019-03-04 — there is no genuine
pre-2020 history in our cache. The user's framing ("pre-2020 vs
post-2020") is replaced with the structurally correct cut implied
by DBG/Heston-Todorov: their measurements already include 2010-2020,
so the only directly testable claim with our data is "SPY VRP > 0
AND SPY edge persists across 2020-2025 (the DBG-era window)."

We therefore test:

  (T1) exp1220 SPY put-credit-spread Sharpe in two sub-windows of the
       available DBG-era data: early=2020-01..2022-12, late=2023-01..2025-12.
       Pre-registered: SR_late > 0 AND |SR_late - SR_early| < 1.5
       (edge persists, no decay).
  (T2) Mean (IV - RV) on SPY (30-DTE ATM puts) vs mean (IV - RV) on
       SPX (VIX² as 30D IV proxy), 2020-2025.
       Pre-registered: mean_SPY (IV-RV) > 0 with t > 2 (Welch one-sided),
       and mean_SPY (IV-RV) > mean_SPX (IV-RV) (cross-sectional).
  (T3) Time-series stability of (IV-RV): split mean SPY VRP in early vs
       late; pre-registered: |Δ| < 2 vol points (≈ no collapse).

PROXIES
-------
SPY IV : Black-Scholes implied vol inverted from end-of-day midprice
         (close col in IronVault option_daily) of the SPY put with strike
         closest to spot AND expiration closest to T=30 calendar days.
         Bisection on σ ∈ [0.05, 1.50]. Risk-free r=4% flat (insensitive
         for ATM 30-DTE).
SPY RV : 30-day trailing realized vol from Yahoo SPY adj close, sqrt(252)
         scaling on daily log returns.
SPX IV : VIX/100 (CBOE 30-day implied vol on SPX).
SPX RV : 30-day trailing RV from Yahoo ^GSPC adj close.

The SPY IV proxy uses CLOSE price not midpoint quote — IronVault stores
end-of-day trade prints. For ATM options with O(10K) volume this is a
tolerable proxy; for low-volume legs it would be biased. We filter to
volume >= 50 contracts/day to mitigate.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "options_cache.db"
CACHE = ROOT / "compass" / "cache" / "exp3300_spy_iv_series.pkl"
REPORT_JSON = ROOT / "compass" / "reports" / "exp3300_spy_spx_disconnect.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3300_spy_spx_disconnect.html"

TRADING_DAYS = 252
RF = 0.04
TARGET_DTE = 30
DTE_BAND = (20, 45)
MIN_VOLUME = 50
SPOT_BAND = 0.02   # strike within 2% of spot
WINDOW_EARLY = ("2020-01-01", "2022-12-31")
WINDOW_LATE = ("2023-01-01", "2025-12-31")


# ============================================================
# Black-Scholes put + bisection IV
# ============================================================
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol_put(price: float, S: float, K: float, T: float, r: float = RF) -> Optional[float]:
    intrinsic = max(K - S, 0.0)
    if price < intrinsic - 0.01 or price <= 0.01:
        return None
    lo, hi = 0.02, 3.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p = bs_put(S, K, T, r, mid)
        if p > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-4:
            break
    if 0.025 < mid < 2.5:
        return mid
    return None


# ============================================================
# Data loaders
# ============================================================
def load_spy_iv_series() -> pd.DataFrame:
    if CACHE.exists():
        print(f"[cache] loading {CACHE.name}")
        return pd.read_pickle(CACHE)

    print("[iv] inverting SPY 30D ATM put midprice → BS IV via bisection")
    spot = yf.download("SPY", start="2019-01-01", end="2026-05-01",
                       progress=False, auto_adjust=False)["Close"]
    if isinstance(spot, pd.DataFrame):
        spot = spot.iloc[:, 0]
    spot.index = pd.to_datetime(spot.index)

    con = sqlite3.connect(DB_PATH)
    rows = con.execute("""
        SELECT od.date, oc.expiration, oc.strike, od.close, od.volume
        FROM option_daily od
        JOIN option_contracts oc ON od.contract_symbol = oc.contract_symbol
        WHERE oc.ticker='SPY' AND oc.option_type='P'
          AND od.date >= '2019-03-01'
          AND od.close > 0.05
          AND od.volume >= ?
    """, (MIN_VOLUME,)).fetchall()
    con.close()
    print(f"[iv] pulled {len(rows):,} put-rows")

    df = pd.DataFrame(rows, columns=["date", "expiration", "strike", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df["expiration"] = pd.to_datetime(df["expiration"])
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    df = df[(df["dte"] >= DTE_BAND[0]) & (df["dte"] <= DTE_BAND[1])]

    df["spot"] = df["date"].map(spot)
    df = df.dropna(subset=["spot"])
    df["moneyness"] = abs(df["strike"] / df["spot"] - 1.0)
    df = df[df["moneyness"] <= SPOT_BAND]
    df["dte_diff"] = (df["dte"] - TARGET_DTE).abs()
    df = df.sort_values(["date", "dte_diff", "moneyness"])
    pick = df.groupby("date").first().reset_index()
    print(f"[iv] daily ATM-30D picks: {len(pick)}")

    ivs = []
    for _, r in pick.iterrows():
        T = r["dte"] / 365.0
        iv = implied_vol_put(r["close"], r["spot"], r["strike"], T, RF)
        ivs.append(iv)
    pick["spy_iv"] = ivs
    pick = pick.dropna(subset=["spy_iv"])
    out = pick.set_index("date")[["spy_iv", "spot", "strike", "dte"]]
    out.to_pickle(CACHE)
    print(f"[iv] cached {len(out)} → {CACHE.name}")
    return out


def load_vol_panel() -> pd.DataFrame:
    spy_iv = load_spy_iv_series()
    print("[yf] downloading VIX/^GSPC/SPY…")
    px = yf.download(["SPY", "^GSPC", "^VIX"], start="2019-01-01",
                     end="2026-05-01", progress=False, auto_adjust=False)["Close"]
    px.index = pd.to_datetime(px.index)

    rv_spy = (np.log(px["SPY"] / px["SPY"].shift(1))
              .rolling(30).std() * math.sqrt(252))
    rv_spx = (np.log(px["^GSPC"] / px["^GSPC"].shift(1))
              .rolling(30).std() * math.sqrt(252))
    vix = px["^VIX"] / 100.0
    panel = pd.DataFrame({
        "spy_iv": spy_iv["spy_iv"].reindex(px.index),
        "spy_rv": rv_spy,
        "spx_iv": vix,
        "spx_rv": rv_spx,
    }).dropna()
    panel["spy_vrp"] = panel["spy_iv"] - panel["spy_rv"]
    panel["spx_vrp"] = panel["spx_iv"] - panel["spx_rv"]
    panel["disconnect"] = panel["spy_vrp"] - panel["spx_vrp"]
    return panel


# ============================================================
# Stream-level sub-window split
# ============================================================
def load_exp1220_stream() -> pd.Series:
    p = ROOT / "compass" / "cache" / "exp2080_streams.pkl"
    streams = pd.read_pickle(p)
    s = streams["exp1220"].astype(float)
    s.index = pd.to_datetime(s.index)
    return s


def sub_window_metrics(s: pd.Series, lo: str, hi: str) -> dict:
    seg = s.loc[lo:hi]
    if seg.std() == 0 or len(seg) < 30:
        return {"n": len(seg), "sharpe": None, "mean_ann": None,
                "vol_ann": None, "hit_rate": None}
    mean_d = seg.mean()
    vol_d = seg.std(ddof=1)
    sr = (mean_d / vol_d) * math.sqrt(TRADING_DAYS) if vol_d > 0 else None
    nonzero = seg[seg != 0]
    hr = float((nonzero > 0).mean()) if len(nonzero) else None
    return {
        "n": int(len(seg)),
        "nonzero_days": int((seg != 0).sum()),
        "sharpe": float(sr) if sr is not None else None,
        "mean_ann_pct": float(mean_d * TRADING_DAYS * 100),
        "vol_ann_pct": float(vol_d * math.sqrt(TRADING_DAYS) * 100),
        "hit_rate": hr,
        "cumret_pct": float(seg.sum() * 100),
    }


# ============================================================
# H1 tests
# ============================================================
def welch_t(a: np.ndarray, b: np.ndarray, alt="greater") -> tuple[float, float]:
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    t, p = stats.ttest_ind(a, b, equal_var=False, alternative=alt)
    return float(t), float(p)


def one_sample_t(x: np.ndarray, alt="greater") -> tuple[float, float]:
    x = x[~np.isnan(x)]
    t, p = stats.ttest_1samp(x, 0.0, alternative=alt)
    return float(t), float(p)


def html_report(payload: dict) -> str:
    def _row(k, v):
        return f"<tr><td><code>{k}</code></td><td>{v}</td></tr>"

    def _tab(d: dict) -> str:
        return "<table>" + "".join(_row(k, v) for k, v in d.items()) + "</table>"

    css = ("body{font-family:system-ui,sans-serif;max-width:880px;margin:2em auto;"
           "color:#222} table{border-collapse:collapse;margin:1em 0} "
           "td,th{padding:.4em .9em;border:1px solid #ccc;font-size:13.5px} "
           "code{background:#f4f4f4;padding:.1em .3em} "
           ".caveat{background:#fff7d6;padding:1em;border-left:4px solid #d4a017} "
           ".verdict{background:#e9f5ec;padding:1em;border-left:4px solid #2c8a4d;"
           "font-weight:600}")
    body = [
        f"<h1>EXP-3300 — SPY/SPX VRP disconnect (H1)</h1>",
        f"<p><i>Generated {payload['generated_at']}</i></p>",
        f"<div class='caveat'><b>Data caveat.</b> {payload['data_caveat']}</div>",
        "<h2>T1 — exp1220 SPY put-credit-spread Sharpe by sub-window</h2>",
        _tab(payload["t1_stream_metrics"]),
        "<h2>T2 — Mean (IV − RV): SPY vs SPX, 2020-2025</h2>",
        _tab(payload["t2_vrp_means"]),
        "<h2>T3 — Stability of SPY VRP (early vs late)</h2>",
        _tab(payload["t3_vrp_stability"]),
        f"<div class='verdict'>Verdict: <code>{payload['verdict']}</code></div>",
        "<h2>Pre-registered cutoffs</h2>",
        _tab(payload["preregistered"]),
    ]
    return f"<html><head><style>{css}</style></head><body>{''.join(body)}</body></html>"


def main():
    print("=" * 72)
    print("EXP-3300 — SPY-vs-SPX VRP disconnect (H1 of DEALER_GEX_LITERATURE.md)")
    print("=" * 72)

    print("\n[1/4] Loading exp1220 SPY put-credit-spread stream …")
    s1220 = load_exp1220_stream()
    early = sub_window_metrics(s1220, *WINDOW_EARLY)
    late = sub_window_metrics(s1220, *WINDOW_LATE)
    full = sub_window_metrics(s1220, "2020-01-01", "2025-12-31")
    print(f"   early {WINDOW_EARLY}: SR={early['sharpe']:.2f}  "
          f"μ_ann={early['mean_ann_pct']:.2f}%  σ_ann={early['vol_ann_pct']:.2f}%")
    print(f"   late  {WINDOW_LATE}: SR={late['sharpe']:.2f}  "
          f"μ_ann={late['mean_ann_pct']:.2f}%  σ_ann={late['vol_ann_pct']:.2f}%")

    print("\n[2/4] Building SPY+SPX IV/RV panel …")
    panel = load_vol_panel()
    panel = panel.loc["2020-01-01":"2025-12-31"]
    print(f"   panel rows: {len(panel)} ({panel.index[0].date()}..{panel.index[-1].date()})")

    spy_vrp = panel["spy_vrp"].to_numpy()
    spx_vrp = panel["spx_vrp"].to_numpy()
    disc = panel["disconnect"].to_numpy()

    t_spy, p_spy = one_sample_t(spy_vrp, alt="greater")
    t_spx, p_spx = one_sample_t(spx_vrp, alt="greater")
    t_disc, p_disc = one_sample_t(disc, alt="greater")
    t_cs, p_cs = welch_t(spy_vrp, spx_vrp, alt="greater")

    t2 = {
        "n_obs": len(panel),
        "mean_SPY_vrp_volpts": round(float(np.nanmean(spy_vrp) * 100), 3),
        "mean_SPX_vrp_volpts": round(float(np.nanmean(spx_vrp) * 100), 3),
        "mean_disconnect_volpts": round(float(np.nanmean(disc) * 100), 3),
        "one_sample_t_SPY_vrp>0": f"t={t_spy:+.2f}  p={p_spy:.4f}",
        "one_sample_t_SPX_vrp>0": f"t={t_spx:+.2f}  p={p_spx:.4f}",
        "welch_t_SPY>SPX": f"t={t_cs:+.2f}  p={p_cs:.4f}",
    }
    print(f"\n   mean SPY VRP = {t2['mean_SPY_vrp_volpts']} vp   t={t_spy:+.2f}  p={p_spy:.4f}")
    print(f"   mean SPX VRP = {t2['mean_SPX_vrp_volpts']} vp   t={t_spx:+.2f}  p={p_spx:.4f}")
    print(f"   disconnect   = {t2['mean_disconnect_volpts']} vp   Welch t={t_cs:+.2f}  p={p_cs:.4f}")

    print("\n[3/4] T3 stability split …")
    e = panel.loc[WINDOW_EARLY[0]:WINDOW_EARLY[1]]
    l = panel.loc[WINDOW_LATE[0]:WINDOW_LATE[1]]
    t3 = {
        "early_SPY_vrp_volpts": round(float(e["spy_vrp"].mean() * 100), 3),
        "late_SPY_vrp_volpts": round(float(l["spy_vrp"].mean() * 100), 3),
        "early_SPX_vrp_volpts": round(float(e["spx_vrp"].mean() * 100), 3),
        "late_SPX_vrp_volpts": round(float(l["spx_vrp"].mean() * 100), 3),
        "delta_SPY_vrp_volpts": round(float((l["spy_vrp"].mean() - e["spy_vrp"].mean()) * 100), 3),
        "delta_SPX_vrp_volpts": round(float((l["spx_vrp"].mean() - e["spx_vrp"].mean()) * 100), 3),
    }
    print(f"   SPY VRP early→late: {t3['early_SPY_vrp_volpts']} → {t3['late_SPY_vrp_volpts']}  (Δ {t3['delta_SPY_vrp_volpts']})")
    print(f"   SPX VRP early→late: {t3['early_SPX_vrp_volpts']} → {t3['late_SPX_vrp_volpts']}  (Δ {t3['delta_SPX_vrp_volpts']})")

    # ----- Pre-registered cutoffs (decision rules) -----
    prereg = {
        "T1_late_SR_gt_0":           "Pre-reg: SR_late > 0",
        "T1_SR_decay_lt_1.5":        "Pre-reg: |SR_late - SR_early| < 1.5",
        "T2_SPY_VRP_t_gt_2":         "Pre-reg: t-stat one-sample > 2 on SPY VRP",
        "T2_SPY_minus_SPX_t_gt_2":   "Pre-reg: Welch t-stat SPY-SPX > 2 (cross-sectional)",
        "T3_SPY_vrp_delta_lt_2vp":   "Pre-reg: |Δ SPY VRP early→late| < 2 vol points",
    }
    pass_t1a = late["sharpe"] is not None and late["sharpe"] > 0
    pass_t1b = (early["sharpe"] is not None and late["sharpe"] is not None
                and abs(late["sharpe"] - early["sharpe"]) < 1.5)
    pass_t2a = t_spy > 2.0
    pass_t2b = t_cs > 2.0
    pass_t3 = abs(t3["delta_SPY_vrp_volpts"]) < 2.0

    legs = {
        "T1a (late SR>0)": pass_t1a,
        "T1b (|ΔSR|<1.5)": pass_t1b,
        "T2a (SPY VRP t>2)": pass_t2a,
        "T2b (SPY-SPX Welch t>2)": pass_t2b,
        "T3 (|ΔSPY VRP|<2vp)": pass_t3,
    }
    n_pass = sum(legs.values())
    if n_pass == 5:
        verdict = "H1_FULL_VALIDATION"
    elif pass_t1a and pass_t2a and pass_t2b:
        verdict = "H1_VALIDATED_CORE_LEGS"
    elif pass_t1a and pass_t2a:
        verdict = "H1_PARTIAL_SPY_VRP_POSITIVE"
    else:
        verdict = "H1_REJECTED"

    print("\n[4/4] Verdict")
    for k, v in legs.items():
        print(f"   {k:30s}  {'PASS' if v else 'FAIL'}")
    print(f"   overall: {verdict}")

    data_caveat = (
        "IronVault SPY history begins 2019-03-04 — there is no pre-2020 cache "
        "to compare against directly. We test instead whether the SPY edge "
        "PERSISTS through the DBG-measurement window (2020-2025), and whether "
        "SPY VRP exceeds SPX VRP cross-sectionally inside that window. SPY IV "
        "is BS-inverted from end-of-day put close (not bid/ask mid) on volume≥50 "
        "ATM 30D contracts — a proxy for true IV that biases slightly toward "
        "transacted prices. SPX IV = VIX/100."
    )

    payload = {
        "experiment": "EXP-3300",
        "title": "SPY/SPX VRP disconnect (H1)",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_caveat": data_caveat,
        "windows": {"early": WINDOW_EARLY, "late": WINDOW_LATE,
                    "full": ["2020-01-01", "2025-12-31"]},
        "t1_stream_metrics": {
            "early": early, "late": late, "full": full,
        },
        "t2_vrp_means": t2,
        "t3_vrp_stability": t3,
        "preregistered": prereg,
        "legs": {k: bool(v) for k, v in legs.items()},
        "verdict": verdict,
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    REPORT_HTML.write_text(html_report(payload))
    print(f"\n[report] → {REPORT_JSON}")
    print(f"[report] → {REPORT_HTML}")


if __name__ == "__main__":
    main()
