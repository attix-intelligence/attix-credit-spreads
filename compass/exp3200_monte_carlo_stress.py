"""EXP-3200 — Monte Carlo stress testing framework for v8a.

Generates 10 000 simulated 252-day market paths under five scenarios
and runs the v8a strategy through each, measuring max DD, recovery,
Sharpe degradation, and circuit-breaker trigger rate. Tests whether
the EXP-2600 12% pooled-DD claim holds under 99th-percentile stress.

Scenarios
---------
  baseline          calibrated MVN — no shock
  credit_freeze     corr matrix shrunk toward J (mix=0.5) — 2008-style
  vol_explosion     Σ scaled by k²=16 — VIX 20 → 80, 2020-style
  grinding_dd       μ shifted by -20%/yr — 2022-style negative drift
  flash_crash       single -10% SPY day at random t in [21, 230]
                    other streams shocked by their SPY-beta + residual

Strategy
--------
v8a = LW risk-parity weights (calibrated once on real post-2020 window),
target-vol scaled to 18% from baseline-realised σ, with optional 3%
trailing-DD circuit breaker (EXP-2370 spec: 20-day trailing window,
flatten while breached). Both with-circuit and no-circuit variants
are run so trigger rate is observable even though production v8a is
no-circuit.

Calibration
-----------
Real v8a cube (EXP-2600 build_cubes) sliced to 2020-01-01..2024-12-31.
Per-stream μ, full Σ, SPY-betas (vs exp1220) all from real returns.
Net Sharpe applies EXP-2570 890.3 bps drag.

Outputs
-------
  compass/reports/exp3200_monte_carlo_stress.json
  compass/reports/exp3200_monte_carlo_stress.html

Rule Zero: no synthetic calibration parameters. All distributional
inputs are estimated directly from the real v8a 2020-2024 cube.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compass.exp2600_north_star_v8 import (  # noqa: E402
    build_cubes,
    NET_DRAG_BPS,
    NET_DRAG_PCT,
    TRADING_DAYS,
)

REPORT_JSON = ROOT / "compass" / "reports" / "exp3200_monte_carlo_stress.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3200_monte_carlo_stress.html"

# ── Calibration window (matches EXP-3151) ──
CAL_START = pd.Timestamp("2020-01-01")
CAL_END   = pd.Timestamp("2024-12-31")

# ── Simulation config ──
N_PATHS    = 10_000
N_DAYS     = 252            # 1 year forward
SPY_COL    = "exp1220"      # SPY-VRP-sensitive stream → drives flash crash
TARGET_VOL = 0.18           # EXP-2600 v8a winner

# ── Circuit breaker (EXP-2370 spec) ──
DD_THRESHOLD = 0.03
DD_WINDOW    = 20

# ── DD claim under test ──
PRODUCTION_DD_CLAIM_PCT = 12.0

RNG_SEED = 20260506


# ════════════════════════════════════════════════════════════════════════
# 1. Calibration
# ════════════════════════════════════════════════════════════════════════


@dataclass
class Calibration:
    streams: List[str]
    mu_daily: np.ndarray         # (m,)
    sigma_daily: np.ndarray      # (m, m)
    sd_daily: np.ndarray         # (m,) per-stream std
    corr: np.ndarray             # (m, m)
    spy_idx: int
    spy_beta: np.ndarray         # (m,) regression beta of stream on SPY
    spy_resid_std: np.ndarray    # (m,) residual std of regression
    risk_parity_weights: np.ndarray   # (m,) — pre-vol-scaled
    vol_scale: float             # scalar to hit TARGET_VOL on baseline
    cube_arr: np.ndarray         # real returns (n_obs, m) — for sanity stats
    real_sharpe: float           # realised SR on the calibration window


def _risk_parity_weights(Sigma: np.ndarray, max_iter: int = 200) -> np.ndarray:
    """Equal-risk-contribution weights (Maillard et al. 2010 fixed point).

    Long-only, sum to 1. Standard implementation; matches the spirit of
    compass.exp2360_robust_cov.risk_parity_weights without re-importing
    so this experiment is self-contained.
    """
    m = Sigma.shape[0]
    w = np.full(m, 1.0 / m)
    for _ in range(max_iter):
        sigma_p = math.sqrt(float(w @ Sigma @ w))
        mrc = Sigma @ w / sigma_p     # marginal risk contribution
        rc  = w * mrc                  # risk contribution per asset
        target = sigma_p / m
        w = w * target / np.maximum(rc, 1e-12)
        w = np.clip(w, 1e-9, None)
        w = w / w.sum()
    return w


def calibrate(cube: pd.DataFrame) -> Calibration:
    streams = list(cube.columns)
    sub = cube.loc[(cube.index >= CAL_START) & (cube.index <= CAL_END)].copy()
    arr = sub.to_numpy(dtype=float)
    n, m = arr.shape

    mu = arr.mean(axis=0)
    Sigma = np.cov(arr, rowvar=False, ddof=1)
    sd = np.sqrt(np.diag(Sigma))
    corr = Sigma / np.outer(sd, sd)

    spy_idx = streams.index(SPY_COL)
    spy_r = arr[:, spy_idx]
    spy_var = float(np.var(spy_r, ddof=1))
    beta = np.zeros(m)
    resid_std = np.zeros(m)
    for j in range(m):
        if j == spy_idx:
            beta[j] = 1.0
            resid_std[j] = 0.0
            continue
        cov_j = float(np.cov(arr[:, j], spy_r, ddof=1)[0, 1])
        beta[j] = cov_j / spy_var if spy_var > 1e-12 else 0.0
        resid = arr[:, j] - beta[j] * spy_r
        resid_std[j] = float(resid.std(ddof=1))

    w = _risk_parity_weights(Sigma)

    # Vol-scale to hit TARGET_VOL on the realised in-sample portfolio
    port_real = arr @ w
    realised_vol_ann = float(port_real.std(ddof=1)) * math.sqrt(TRADING_DAYS)
    vol_scale = TARGET_VOL / realised_vol_ann if realised_vol_ann > 1e-12 else 1.0

    port_scaled = port_real * vol_scale
    real_sr = (
        float(port_scaled.mean()) / float(port_scaled.std(ddof=1))
        * math.sqrt(TRADING_DAYS)
    )

    return Calibration(
        streams=streams, mu_daily=mu, sigma_daily=Sigma, sd_daily=sd,
        corr=corr, spy_idx=spy_idx, spy_beta=beta, spy_resid_std=resid_std,
        risk_parity_weights=w, vol_scale=vol_scale, cube_arr=arr,
        real_sharpe=real_sr,
    )


# ════════════════════════════════════════════════════════════════════════
# 2. Path generators (per scenario)
# ════════════════════════════════════════════════════════════════════════


def _mvn_paths(
    mu: np.ndarray, Sigma: np.ndarray, n_paths: int, n_days: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Multivariate-normal sample of shape (n_paths, n_days, m)."""
    m = mu.shape[0]
    # Cholesky with jitter for numerical safety on near-singular Σ
    Sigma_psd = Sigma + 1e-12 * np.eye(m)
    L = np.linalg.cholesky(Sigma_psd)
    Z = rng.standard_normal((n_paths, n_days, m))
    return Z @ L.T + mu


def gen_baseline(c: Calibration, rng: np.random.Generator) -> np.ndarray:
    return _mvn_paths(c.mu_daily, c.sigma_daily, N_PATHS, N_DAYS, rng)


def gen_credit_freeze(
    c: Calibration, rng: np.random.Generator, mix: float = 0.5,
) -> np.ndarray:
    """Shrink correlation matrix toward all-ones."""
    m = c.corr.shape[0]
    new_corr = (1 - mix) * c.corr + mix * np.ones((m, m))
    np.fill_diagonal(new_corr, 1.0)
    new_Sigma = (c.sd_daily[:, None] * new_corr) * c.sd_daily[None, :]
    return _mvn_paths(c.mu_daily, new_Sigma, N_PATHS, N_DAYS, rng)


def gen_vol_explosion(
    c: Calibration, rng: np.random.Generator, vix_mult: float = 4.0,
) -> np.ndarray:
    """Scale Σ by k² where k=4 maps VIX 20 → VIX 80."""
    return _mvn_paths(
        c.mu_daily, c.sigma_daily * (vix_mult ** 2), N_PATHS, N_DAYS, rng,
    )


def gen_grinding_dd(
    c: Calibration, rng: np.random.Generator, drift_ann: float = 0.20,
) -> np.ndarray:
    """Subtract a -20%/yr drift from μ."""
    daily_drift = drift_ann / TRADING_DAYS
    mu_shocked = c.mu_daily - daily_drift
    return _mvn_paths(mu_shocked, c.sigma_daily, N_PATHS, N_DAYS, rng)


def gen_flash_crash(
    c: Calibration, rng: np.random.Generator, spy_shock: float = -0.10,
) -> np.ndarray:
    """Baseline MVN paths with a single -10% SPY day at random t per path.

    Other streams shocked by β_i × shock + ε_i with ε_i drawn from
    the calibrated SPY-residual std, so cross-stream comovement is
    preserved on the shock day.
    """
    paths = gen_baseline(c, rng)
    crash_days = rng.integers(low=DD_WINDOW + 1, high=N_DAYS - 21,
                              size=N_PATHS)
    m = paths.shape[2]
    # Build the shock vector per path: β·shock + ε
    eps = rng.standard_normal((N_PATHS, m)) * c.spy_resid_std[None, :]
    shock_vec = c.spy_beta[None, :] * spy_shock + eps
    shock_vec[:, c.spy_idx] = spy_shock          # exactly -10% on SPY
    rows = np.arange(N_PATHS)
    paths[rows, crash_days, :] = shock_vec
    return paths


SCENARIO_GENERATORS = {
    "baseline":       gen_baseline,
    "credit_freeze":  gen_credit_freeze,
    "vol_explosion":  gen_vol_explosion,
    "grinding_dd":    gen_grinding_dd,
    "flash_crash":    gen_flash_crash,
}

SCENARIO_DESC = {
    "baseline":      "Calibrated MVN, no shock — control",
    "credit_freeze": "Correlations shrunk toward 1.0 (mix=0.5) — 2008-style",
    "vol_explosion": "Σ × 16 (VIX 20 → 80) — 2020-style",
    "grinding_dd":   "μ shifted by −20%/yr — 2022-style",
    "flash_crash":   "Single −10% SPY day at random t (β-propagated)",
}


# ════════════════════════════════════════════════════════════════════════
# 3. v8a strategy applier
# ════════════════════════════════════════════════════════════════════════


def apply_v8a(
    paths: np.ndarray, w_scaled: np.ndarray, use_circuit: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    """Run v8a on simulated paths.

    paths: (n_paths, n_days, m)
    Returns: (port_returns_after_circuit, leverage_path) each (n_paths, n_days)
    """
    port = paths @ w_scaled                                  # (n_paths, n_days)
    if not use_circuit:
        return port, np.ones_like(port)

    n_paths, n_days = port.shape
    levered = np.empty_like(port)
    leverage = np.ones_like(port)
    # Trailing-DD circuit breaker (single pass per path):
    # At day t (t>0), look at eq history over [t-DD_WINDOW, t-1] and
    # current eq. If (window_max - eq) / window_max > DD_THRESHOLD, the
    # circuit is tripped — leverage[t] = 0; else 1.
    for p in range(n_paths):
        eq = 1.0
        eq_arr = np.empty(n_days)
        for t in range(n_days):
            if t == 0:
                lev = 1.0
            else:
                start = max(0, t - DD_WINDOW)
                window_max = float(np.max(eq_arr[start:t]))
                cur_dd = (window_max - eq) / window_max if window_max > 1e-12 else 0.0
                lev = 0.0 if cur_dd > DD_THRESHOLD else 1.0
            leverage[p, t] = lev
            r = port[p, t] * lev
            levered[p, t] = r
            eq *= (1.0 + r)
            eq_arr[t] = eq
    return levered, leverage


# ════════════════════════════════════════════════════════════════════════
# 4. Per-path metrics
# ════════════════════════════════════════════════════════════════════════


def path_metrics(port: np.ndarray) -> Dict[str, np.ndarray]:
    """Vectorised per-path metrics on (n_paths, n_days) returns."""
    n_paths, n_days = port.shape
    eq = np.cumprod(1.0 + port, axis=1)
    cmax = np.maximum.accumulate(eq, axis=1)
    dd = (cmax - eq) / cmax                                  # (n_paths, n_days)
    max_dd = dd.max(axis=1)
    # Recovery time: days from max-DD trough to next time eq ≥ cmax_at_trough.
    # If never recovers → set to N_DAYS (right-censored).
    trough_t = dd.argmax(axis=1)
    rec = np.full(n_paths, N_DAYS, dtype=np.int64)
    for p in range(n_paths):
        t0 = int(trough_t[p])
        peak_lvl = float(cmax[p, t0])
        post = eq[p, t0:]
        idx = np.where(post >= peak_lvl)[0]
        if idx.size > 0:
            rec[p] = int(idx[0])
    mu = port.mean(axis=1)
    sd = port.std(axis=1, ddof=1)
    sharpe = np.where(sd > 1e-12, mu / np.maximum(sd, 1e-12), 0.0) * math.sqrt(TRADING_DAYS)
    final = eq[:, -1] - 1.0                                  # cumulative return
    return {
        "max_dd": max_dd,
        "recovery_days": rec,
        "sharpe": sharpe,
        "total_return": final,
    }


def percentile_summary(arr: np.ndarray) -> Dict[str, float]:
    qs = np.quantile(arr, [0.01, 0.05, 0.50, 0.95, 0.99])
    return {
        "mean": float(arr.mean()),
        "std":  float(arr.std(ddof=1)),
        "p01":  float(qs[0]),
        "p05":  float(qs[1]),
        "p50":  float(qs[2]),
        "p95":  float(qs[3]),
        "p99":  float(qs[4]),
        "min":  float(arr.min()),
        "max":  float(arr.max()),
    }


def trip_rate(leverage: np.ndarray) -> Dict[str, float]:
    """Fraction of (path,day) cells where circuit was tripped (lev=0),
    plus fraction of paths that ever tripped."""
    tripped_cells = float((leverage < 0.5).mean())
    ever = float(((leverage < 0.5).any(axis=1)).mean())
    return {"per_day_pct": round(tripped_cells * 100, 3),
            "per_path_pct": round(ever * 100, 3)}


# ════════════════════════════════════════════════════════════════════════
# 5. Main runner
# ════════════════════════════════════════════════════════════════════════


def run_scenario(
    name: str, c: Calibration, w_scaled: np.ndarray, rng: np.random.Generator,
) -> Dict:
    paths = SCENARIO_GENERATORS[name](c, rng)
    # No-circuit variant (matches production v8a)
    port_nc, lev_nc = apply_v8a(paths, w_scaled, use_circuit=False)
    m_nc = path_metrics(port_nc)
    # With-circuit variant
    port_c, lev_c = apply_v8a(paths, w_scaled, use_circuit=True)
    m_c = path_metrics(port_c)
    # Net (drag-adjusted) Sharpe — drag is deterministic per-day shift
    daily_drag = NET_DRAG_PCT / 100.0 / TRADING_DAYS
    port_nc_net = port_nc - daily_drag
    port_c_net  = port_c  - daily_drag
    m_nc_net = path_metrics(port_nc_net)
    m_c_net  = path_metrics(port_c_net)

    return {
        "name": name,
        "description": SCENARIO_DESC[name],
        "n_paths": int(N_PATHS),
        "n_days":  int(N_DAYS),
        "no_circuit": {
            "gross": {k: percentile_summary(v) for k, v in m_nc.items()},
            "net":   {k: percentile_summary(v) for k, v in m_nc_net.items()},
            "trip":  trip_rate(lev_nc),
            "dd_claim_breach_pct": round(
                float((m_nc["max_dd"] > PRODUCTION_DD_CLAIM_PCT / 100.0).mean()) * 100, 3
            ),
        },
        "with_circuit": {
            "gross": {k: percentile_summary(v) for k, v in m_c.items()},
            "net":   {k: percentile_summary(v) for k, v in m_c_net.items()},
            "trip":  trip_rate(lev_c),
            "dd_claim_breach_pct": round(
                float((m_c["max_dd"] > PRODUCTION_DD_CLAIM_PCT / 100.0).mean()) * 100, 3
            ),
        },
    }


def main() -> None:
    print("=" * 72)
    print("EXP-3200 — Monte Carlo stress testing for v8a")
    print("=" * 72)

    print("\n[1/4] Building v8a cube + calibrating from real post-2020 returns…")
    cubes = build_cubes()
    v8a = cubes["v8a_add_qqq"]
    c = calibrate(v8a)
    w_scaled = c.risk_parity_weights * c.vol_scale
    print(f"      streams           : {c.streams}")
    print(f"      cal window        : {CAL_START.date()} .. {CAL_END.date()}  "
          f"({c.cube_arr.shape[0]} obs)")
    print(f"      RP weights (raw)  : "
          + " ".join(f"{x:.3f}" for x in c.risk_parity_weights))
    print(f"      vol scalar        : {c.vol_scale:.3f}  "
          f"(target σ_ann = {TARGET_VOL*100:.0f}%)")
    print(f"      realised in-sample SR (post-vol-scale): {c.real_sharpe:.2f}")
    print(f"      SPY-betas         : "
          + " ".join(f"{c.streams[i]}={c.spy_beta[i]:+.2f}" for i in range(len(c.streams))))

    print(f"\n[2/4] Running {N_PATHS:,} paths × {N_DAYS}d × "
          f"{len(SCENARIO_GENERATORS)} scenarios "
          f"(both no-circuit and with-circuit variants)…")
    rng = np.random.default_rng(RNG_SEED)
    results: Dict[str, Dict] = {}
    for name in SCENARIO_GENERATORS.keys():
        print(f"\n      [{name}] generating + simulating…")
        sub_rng = np.random.default_rng(rng.integers(0, 2**31 - 1))
        results[name] = run_scenario(name, c, w_scaled, sub_rng)
        nc = results[name]["no_circuit"]
        wc = results[name]["with_circuit"]
        print(f"        no_circuit gross  SR p50 {nc['gross']['sharpe']['p50']:5.2f}  "
              f"DD p99 {nc['gross']['max_dd']['p99']*100:5.1f}%  "
              f"breach@12% {nc['dd_claim_breach_pct']:5.2f}%")
        print(f"        with_circuit gross SR p50 {wc['gross']['sharpe']['p50']:5.2f}  "
              f"DD p99 {wc['gross']['max_dd']['p99']*100:5.1f}%  "
              f"breach@12% {wc['dd_claim_breach_pct']:5.2f}%  "
              f"trip {wc['trip']['per_path_pct']:.1f}% paths")

    # ── DD-claim verdict ──
    print("\n[3/4] 12% Max-DD claim verdict (production = no-circuit v8a)")
    print("-" * 72)
    overall_breach = []
    for name, r in results.items():
        nc = r["no_circuit"]
        breach = nc["dd_claim_breach_pct"]
        p99 = nc["gross"]["max_dd"]["p99"] * 100
        survives = p99 <= PRODUCTION_DD_CLAIM_PCT
        overall_breach.append(breach)
        flag = "✓" if survives else "✗"
        print(f"  {flag} {name:<16s}  p99 DD = {p99:5.1f}%   "
              f"P(DD > 12%) = {breach:5.2f}%   "
              f"{'holds' if survives else 'BREACHES claim'}")
    holds_globally = all(
        r["no_circuit"]["gross"]["max_dd"]["p99"] * 100 <= PRODUCTION_DD_CLAIM_PCT
        for r in results.values()
    )
    print(f"\n  Overall: {'✓ 12% claim survives all 5 scenarios' if holds_globally else '✗ 12% claim BREACHED in ≥1 scenario'}")

    print("\n[4/4] Sharpe degradation table (gross, no-circuit, p50)")
    base_sr = results["baseline"]["no_circuit"]["gross"]["sharpe"]["p50"]
    print(f"  baseline p50 SR  = {base_sr:.2f}  (real in-sample SR = {c.real_sharpe:.2f})")
    for name in ["credit_freeze", "vol_explosion", "grinding_dd", "flash_crash"]:
        sr = results[name]["no_circuit"]["gross"]["sharpe"]["p50"]
        delta = sr - base_sr
        pct = (sr / base_sr - 1) * 100 if abs(base_sr) > 1e-9 else 0.0
        print(f"  {name:<16s}  p50 SR = {sr:6.2f}   Δ = {delta:+5.2f}   ({pct:+6.1f}%)")

    payload = {
        "experiment": "EXP-3200",
        "title": "Monte Carlo stress testing — v8a",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "data_caveat": (
            "Calibration uses real v8a cube on 2020-01-01..2024-12-31. "
            "MVN distributional assumption — no Student-t or jump-diffusion. "
            "Flash-crash scenario uses linear β-propagation; nonlinear "
            "tail comovement (e.g. correlation breakdowns *during* the "
            "shock) not captured beyond the credit_freeze scenario. "
            "Production v8a has no circuit breaker — circuit results "
            "shown for comparison only."
        ),
        "config": {
            "n_paths": N_PATHS,
            "n_days": N_DAYS,
            "target_vol_annual": TARGET_VOL,
            "dd_threshold": DD_THRESHOLD,
            "dd_window_days": DD_WINDOW,
            "production_dd_claim_pct": PRODUCTION_DD_CLAIM_PCT,
            "rng_seed": RNG_SEED,
            "drag_bps": NET_DRAG_BPS,
            "calibration_start": str(CAL_START.date()),
            "calibration_end":   str(CAL_END.date()),
        },
        "calibration": {
            "streams": c.streams,
            "n_obs": int(c.cube_arr.shape[0]),
            "mu_daily": {c.streams[i]: float(c.mu_daily[i]) for i in range(len(c.streams))},
            "sd_ann_pct": {c.streams[i]: float(c.sd_daily[i] * math.sqrt(TRADING_DAYS) * 100)
                            for i in range(len(c.streams))},
            "spy_beta":   {c.streams[i]: float(c.spy_beta[i]) for i in range(len(c.streams))},
            "risk_parity_weights": {c.streams[i]: float(c.risk_parity_weights[i])
                                     for i in range(len(c.streams))},
            "vol_scale": float(c.vol_scale),
            "scaled_weights": {c.streams[i]: float(w_scaled[i]) for i in range(len(c.streams))},
            "in_sample_sharpe_post_scale": float(c.real_sharpe),
        },
        "scenarios": results,
        "verdict": {
            "production_dd_claim_pct": PRODUCTION_DD_CLAIM_PCT,
            "claim_holds_all_scenarios": bool(holds_globally),
            "max_p99_dd_pct": float(max(
                r["no_circuit"]["gross"]["max_dd"]["p99"] * 100 for r in results.values()
            )),
            "worst_scenario": max(
                results.items(),
                key=lambda kv: kv[1]["no_circuit"]["gross"]["max_dd"]["p99"],
            )[0],
        },
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[report] → {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[report] → {REPORT_HTML}")


# ════════════════════════════════════════════════════════════════════════
# 6. HTML
# ════════════════════════════════════════════════════════════════════════


def build_html(p: Dict) -> str:
    cfg = p["config"]
    v = p["verdict"]
    survives = v["claim_holds_all_scenarios"]
    color = "#16a34a" if survives else "#dc2626"
    badge = (
        "12% MAX-DD CLAIM SURVIVES STRESS"
        if survives
        else f"12% CLAIM BREACHED — worst p99 = {v['max_p99_dd_pct']:.1f}% in {v['worst_scenario']}"
    )

    scenario_rows = ""
    for name, r in p["scenarios"].items():
        nc = r["no_circuit"]
        wc = r["with_circuit"]
        ng = nc["gross"]
        wg = wc["gross"]
        nn = nc["net"]
        breach_color = "#16a34a" if ng["max_dd"]["p99"] * 100 <= cfg["production_dd_claim_pct"] else "#dc2626"
        scenario_rows += f"""
<tr>
  <td><strong>{name}</strong><br><span class='muted'>{r['description']}</span></td>
  <td>{ng['sharpe']['p50']:.2f}</td>
  <td>{ng['sharpe']['p05']:.2f}</td>
  <td>{nn['sharpe']['p50']:.2f}</td>
  <td>{ng['max_dd']['p50']*100:.1f}%</td>
  <td style='color:{breach_color};font-weight:700'>{ng['max_dd']['p99']*100:.1f}%</td>
  <td>{ng['max_dd']['max']*100:.1f}%</td>
  <td>{ng['recovery_days']['p50']:.0f}</td>
  <td>{ng['recovery_days']['p99']:.0f}</td>
  <td>{nc['dd_claim_breach_pct']:.2f}%</td>
  <td>{wc['trip']['per_path_pct']:.1f}%</td>
  <td>{wc['trip']['per_day_pct']:.2f}%</td>
  <td>{wg['max_dd']['p99']*100:.1f}%</td>
</tr>
"""

    cal = p["calibration"]
    streams_rows = ""
    for s in cal["streams"]:
        streams_rows += (
            f"<tr><td>{s}</td>"
            f"<td>{cal['mu_daily'][s]*100:.4f}%</td>"
            f"<td>{cal['sd_ann_pct'][s]:.2f}%</td>"
            f"<td>{cal['spy_beta'][s]:+.3f}</td>"
            f"<td>{cal['risk_parity_weights'][s]:.4f}</td>"
            f"<td>{cal['scaled_weights'][s]:.4f}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3200 — Monte Carlo stress (v8a)</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1320px;margin:0 auto;padding:28px;background:#fff;color:#1e293b;}}
h1{{font-size:1.7em;color:#0f172a;}}
h2{{margin-top:2em;border-bottom:2px solid #e2e8f0;padding-bottom:8px;color:#334155;}}
.muted{{color:#64748b;font-size:0.78em;}}
.caveat{{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:14px;margin:16px 0;font-size:0.9rem;line-height:1.55;}}
.sources{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px;font-size:0.84rem;line-height:1.6;}}
.verdict{{background:#fff;border:2px solid {color};border-radius:8px;padding:18px;margin:18px 0;}}
.verdict .badge{{display:inline-block;padding:5px 14px;border-radius:14px;color:#fff;background:{color};font-weight:700;font-size:0.86rem;}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:0.83em;}}
th{{background:#f1f5f9;padding:8px 9px;text-align:right;border-bottom:2px solid #cbd5e1;font-size:0.7em;text-transform:uppercase;}}
th:first-child{{text-align:left;}}
td{{padding:7px 9px;text-align:right;border-bottom:1px solid #e2e8f0;vertical-align:top;}}
td:first-child{{text-align:left;font-weight:600;color:#475569;}}
.kv{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 18px;font-size:0.9em;margin:10px 0;}}
.kv b{{color:#475569;}}
</style></head><body>

<h1>EXP-3200 — Monte Carlo Stress Testing for v8a</h1>
<p class="muted">{cfg['n_paths']:,} paths × {cfg['n_days']}d × 5 scenarios.
Calibration: real v8a cube {cfg['calibration_start']} .. {cfg['calibration_end']}.
{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="sources">
<strong>Rule Zero.</strong> Calibration μ, Σ, SPY-β, residual std, and
risk-parity weights all estimated from the real v8a 2020-2024 cube
(8 streams: {", ".join(cal['streams'])}). Vol-scaled to target
{cfg['target_vol_annual']*100:.0f}% (matching EXP-2600 v8a winner).
Net SR uses EXP-2570 {cfg['drag_bps']:.1f} bps drag. Circuit breaker:
{cfg['dd_threshold']*100:.0f}% trailing-DD over {cfg['dd_window_days']}-day window
(EXP-2370 spec). Production v8a is no-circuit; circuit results are diagnostic.
</div>

<div class="caveat">
<strong>⚠ Modelling caveats.</strong> (1) MVN — no t-tail or jump-diffusion;
real options-strategy returns are heavier-tailed, so this is an
<em>optimistic</em> simulator. (2) Flash-crash uses linear β-propagation
of the SPY shock; nonlinear correlation-breakdown during the shock is
not captured (covered separately by credit_freeze). (3) Calibration
window is post-2020 only — pre-2020 IronVault data is not in this
repo, so we cannot test pre-2010 regimes.
</div>

<div class="verdict">
<span class="badge">{badge}</span>
<div class="kv" style="margin-top:14px">
<div><b>Production claim under test</b></div><div>Max DD ≤ {cfg['production_dd_claim_pct']:.0f}% (no-circuit, gross)</div>
<div><b>Worst p99 DD across scenarios</b></div><div>{v['max_p99_dd_pct']:.2f}% in <code>{v['worst_scenario']}</code></div>
<div><b>Realised in-sample SR (post-scale)</b></div><div>{cal['in_sample_sharpe_post_scale']:.2f}</div>
<div><b>Total simulated paths</b></div><div>{cfg['n_paths']:,} per scenario × 5 scenarios = {cfg['n_paths']*5:,}</div>
</div>
</div>

<h2>1. Scenario summary (no-circuit, production)</h2>
<table>
<thead><tr>
<th rowspan="2">Scenario</th>
<th colspan="2">Sharpe (gross)</th>
<th>Sharpe (net)</th>
<th colspan="3">Max DD</th>
<th colspan="2">Recovery (days)</th>
<th>P(DD &gt; 12%)</th>
<th colspan="2">Circuit (with)</th>
<th>DD p99 (with)</th>
</tr><tr>
<th>p50</th><th>p05</th>
<th>p50</th>
<th>p50</th><th>p99</th><th>worst</th>
<th>p50</th><th>p99</th>
<th>no-circuit</th>
<th>%paths</th><th>%days</th>
<th>p99</th>
</tr></thead>
<tbody>{scenario_rows}</tbody>
</table>

<h2>2. Calibration (real post-2020 cube)</h2>
<table>
<thead><tr>
<th>Stream</th><th>μ daily</th><th>σ ann</th><th>β vs SPY</th>
<th>RP weight</th><th>RP × vol scale</th>
</tr></thead>
<tbody>{streams_rows}</tbody>
</table>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3200_monte_carlo_stress.py · Rule Zero · real cube calibration · {cfg['rng_seed']} seed
</p>
</body></html>"""


if __name__ == "__main__":
    main()
