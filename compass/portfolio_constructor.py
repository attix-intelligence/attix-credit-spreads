"""
Advanced portfolio construction with multiple optimisation methods.

Methods:
  1. Mean-variance with Ledoit-Wolf shrinkage
  2. Black-Litterman (views from ML confidence scores)
  3. Risk parity (inverse-vol)
  4. Hierarchical Risk Parity — HRP (dendrogram clustering)
  5. Minimum CVaR portfolio
  6. Maximum diversification
  7. Regime-conditional (different method per regime)

Constraints:  sector limits, position limits, turnover limits.

All methods work on pre-loaded return data — no network calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

logger = logging.getLogger(__name__)

TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------

class OptMethod(str, Enum):
    MEAN_VARIANCE = "mean_variance"
    BLACK_LITTERMAN = "black_litterman"
    RISK_PARITY = "risk_parity"
    HRP = "hrp"
    MIN_CVAR = "min_cvar"
    MAX_DIVERSIFICATION = "max_diversification"


@dataclass
class PortfolioWeights:
    """Optimisation result."""
    weights: Dict[str, float]
    method: str
    expected_return: float = 0.0
    expected_vol: float = 0.0
    sharpe: float = 0.0
    cvar_95: float = 0.0
    diversification_ratio: float = 0.0


@dataclass
class Constraints:
    """Portfolio constraints."""
    max_position: float = 0.40
    min_position: float = 0.0
    max_sector_weight: float = 0.60
    max_turnover: float = 1.0      # max sum(|delta_w|) per rebalance
    sector_map: Dict[str, str] = field(default_factory=dict)


@dataclass
class BLView:
    """Single Black-Litterman view."""
    asset: str
    expected_return: float
    confidence: float           # 0-1 (higher = more certain)


@dataclass
class RiskContribution:
    """Per-asset risk contribution."""
    asset: str
    weight: float
    marginal_risk: float
    pct_contribution: float


@dataclass
class ConstructionResult:
    """Full construction output."""
    portfolio: PortfolioWeights
    risk_contributions: List[RiskContribution] = field(default_factory=list)
    efficient_frontier: Optional[pd.DataFrame] = None


# ---------------------------------------------------------------------------
# Covariance estimators
# ---------------------------------------------------------------------------

def ledoit_wolf_shrinkage(returns: pd.DataFrame) -> np.ndarray:
    """Ledoit-Wolf shrinkage estimator for the covariance matrix.

    Shrinks sample covariance toward scaled identity (constant correlation).
    """
    X = returns.values
    n, p = X.shape
    if n < 2 or p < 1:
        return np.eye(max(p, 1))

    S = np.cov(X, rowvar=False, ddof=1)
    mu = np.trace(S) / p
    delta = S - mu * np.eye(p)

    # Squared Frobenius norms
    sum_sq = (delta ** 2).sum()

    # Compute optimal shrinkage intensity
    X_centered = X - X.mean(axis=0)
    y = X_centered ** 2
    sum_sq_y = 0.0
    for i in range(p):
        for j in range(p):
            sum_sq_y += ((y[:, i] * y[:, j]).mean() - S[i, j] ** 2)

    intensity = max(0.0, min(1.0, sum_sq_y / (n * sum_sq))) if sum_sq > 0 else 1.0
    return intensity * mu * np.eye(p) + (1 - intensity) * S


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class PortfolioConstructor:
    """Advanced portfolio construction engine.

    Args:
        risk_free_rate: Annualised risk-free rate.
        cvar_alpha: Confidence level for CVaR (0.95 = 95%).
    """

    def __init__(
        self,
        risk_free_rate: float = 0.045,
        cvar_alpha: float = 0.95,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.cvar_alpha = cvar_alpha

    # ------------------------------------------------------------------
    # 1. Mean-variance with Ledoit-Wolf
    # ------------------------------------------------------------------

    def mean_variance(
        self,
        returns: pd.DataFrame,
        constraints: Optional[Constraints] = None,
    ) -> PortfolioWeights:
        """Mean-variance optimisation with shrinkage covariance."""
        c = constraints or Constraints()
        assets = returns.columns.tolist()
        n = len(assets)
        if n == 0:
            return PortfolioWeights(weights={}, method="mean_variance")

        mu = returns.mean().values * TRADING_DAYS
        cov = ledoit_wolf_shrinkage(returns)

        def neg_sharpe(w):
            ret = w @ mu
            vol = np.sqrt(w @ cov @ w * TRADING_DAYS)
            return -(ret - self.risk_free_rate) / vol if vol > 1e-12 else 0.0

        x0 = np.ones(n) / n
        bounds = [(c.min_position, c.max_position)] * n
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        res = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds,
                        constraints=cons, options={"maxiter": 500})

        w = res.x if res.success else x0
        w = np.maximum(w, 0)
        w /= w.sum()

        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w * TRADING_DAYS))
        sharpe = (ret - self.risk_free_rate) / vol if vol > 1e-12 else 0.0

        return PortfolioWeights(
            weights=dict(zip(assets, w.tolist())),
            method="mean_variance",
            expected_return=ret, expected_vol=vol, sharpe=sharpe,
        )

    # ------------------------------------------------------------------
    # 2. Black-Litterman
    # ------------------------------------------------------------------

    def black_litterman(
        self,
        returns: pd.DataFrame,
        views: List[BLView],
        tau: float = 0.05,
        constraints: Optional[Constraints] = None,
    ) -> PortfolioWeights:
        """Black-Litterman model with ML-derived views."""
        c = constraints or Constraints()
        assets = returns.columns.tolist()
        n = len(assets)
        if n == 0:
            return PortfolioWeights(weights={}, method="black_litterman")

        cov = ledoit_wolf_shrinkage(returns) * TRADING_DAYS
        mkt_weights = np.ones(n) / n
        delta = 2.5  # risk aversion
        pi = delta * cov @ mkt_weights  # equilibrium returns

        # Build P (pick matrix) and Q (view returns)
        if not views:
            mu_bl = pi
        else:
            k = len(views)
            P = np.zeros((k, n))
            Q = np.zeros(k)
            omega_diag = np.zeros(k)
            for i, v in enumerate(views):
                if v.asset in assets:
                    j = assets.index(v.asset)
                    P[i, j] = 1.0
                    Q[i] = v.expected_return
                    omega_diag[i] = (1 - v.confidence) / max(v.confidence, 0.01) * (tau * cov[j, j])

            Omega = np.diag(omega_diag)
            tau_cov = tau * cov
            inv_tau_cov = np.linalg.inv(tau_cov + 1e-8 * np.eye(n))
            inv_omega = np.linalg.inv(Omega + 1e-8 * np.eye(k))
            mu_bl = np.linalg.inv(inv_tau_cov + P.T @ inv_omega @ P) @ (
                inv_tau_cov @ pi + P.T @ inv_omega @ Q)

        # Optimise using BL returns
        def neg_sharpe(w):
            ret = w @ mu_bl
            vol = np.sqrt(w @ cov @ w)
            return -(ret - self.risk_free_rate) / vol if vol > 1e-12 else 0.0

        x0 = np.ones(n) / n
        bounds = [(c.min_position, c.max_position)] * n
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        res = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds,
                        constraints=cons, options={"maxiter": 500})

        w = res.x if res.success else x0
        w = np.maximum(w, 0)
        w /= w.sum()

        ret = float(w @ mu_bl)
        vol = float(np.sqrt(w @ cov @ w))
        sharpe = (ret - self.risk_free_rate) / vol if vol > 1e-12 else 0.0

        return PortfolioWeights(
            weights=dict(zip(assets, w.tolist())),
            method="black_litterman",
            expected_return=ret, expected_vol=vol, sharpe=sharpe,
        )

    # ------------------------------------------------------------------
    # 3. Risk parity
    # ------------------------------------------------------------------

    @staticmethod
    def risk_parity(returns: pd.DataFrame) -> PortfolioWeights:
        """Inverse-volatility risk parity."""
        assets = returns.columns.tolist()
        if not assets:
            return PortfolioWeights(weights={}, method="risk_parity")

        vols = returns.std().values * np.sqrt(TRADING_DAYS)
        vols = np.maximum(vols, 1e-8)
        inv_vol = 1.0 / vols
        w = inv_vol / inv_vol.sum()

        mu = returns.mean().values * TRADING_DAYS
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ np.cov(returns.values, rowvar=False) @ w * TRADING_DAYS))

        return PortfolioWeights(
            weights=dict(zip(assets, w.tolist())),
            method="risk_parity",
            expected_return=ret, expected_vol=vol,
        )

    # ------------------------------------------------------------------
    # 4. Hierarchical Risk Parity (HRP)
    # ------------------------------------------------------------------

    @staticmethod
    def hrp(returns: pd.DataFrame) -> PortfolioWeights:
        """Hierarchical Risk Parity via dendrogram clustering."""
        assets = returns.columns.tolist()
        n = len(assets)
        if n <= 1:
            w = {a: 1.0 for a in assets}
            return PortfolioWeights(weights=w, method="hrp")

        corr = returns.corr().values
        # Distance matrix from correlation
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist, 0.0)
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="single")
        order = leaves_list(link).tolist()

        # Recursive bisection
        cov = returns.cov().values
        weights = np.ones(n)

        def _get_cluster_var(idx_list):
            sub_cov = cov[np.ix_(idx_list, idx_list)]
            inv_diag = 1.0 / np.diag(sub_cov)
            inv_diag /= inv_diag.sum()
            return float(inv_diag @ sub_cov @ inv_diag)

        def _bisect(items):
            if len(items) <= 1:
                return
            mid = len(items) // 2
            left = items[:mid]
            right = items[mid:]
            var_l = _get_cluster_var(left)
            var_r = _get_cluster_var(right)
            total = var_l + var_r
            alpha_l = 1 - var_l / total if total > 0 else 0.5
            for i in left:
                weights[i] *= alpha_l
            for i in right:
                weights[i] *= (1 - alpha_l)
            _bisect(left)
            _bisect(right)

        _bisect(order)
        weights /= weights.sum()

        mu = returns.mean().values * TRADING_DAYS
        ret = float(weights @ mu)
        vol = float(np.sqrt(weights @ cov @ weights * TRADING_DAYS))

        return PortfolioWeights(
            weights=dict(zip(assets, weights.tolist())),
            method="hrp",
            expected_return=ret, expected_vol=vol,
        )

    # ------------------------------------------------------------------
    # 5. Minimum CVaR
    # ------------------------------------------------------------------

    def min_cvar(
        self,
        returns: pd.DataFrame,
        constraints: Optional[Constraints] = None,
    ) -> PortfolioWeights:
        """Minimum Conditional Value-at-Risk portfolio."""
        c = constraints or Constraints()
        assets = returns.columns.tolist()
        n = len(assets)
        if n == 0:
            return PortfolioWeights(weights={}, method="min_cvar")

        R = returns.values
        T = R.shape[0]
        alpha = self.cvar_alpha
        cutoff = int(T * (1 - alpha))
        if cutoff < 1:
            cutoff = 1

        def cvar_obj(w):
            port_ret = R @ w
            sorted_ret = np.sort(port_ret)
            return -float(sorted_ret[:cutoff].mean())

        x0 = np.ones(n) / n
        bounds = [(c.min_position, c.max_position)] * n
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        res = minimize(cvar_obj, x0, method="SLSQP", bounds=bounds,
                        constraints=cons, options={"maxiter": 500})

        w = res.x if res.success else x0
        w = np.maximum(w, 0)
        w /= w.sum()

        port_ret = R @ w
        sorted_ret = np.sort(port_ret)
        cvar = float(-sorted_ret[:cutoff].mean())

        mu = returns.mean().values * TRADING_DAYS
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ np.cov(R, rowvar=False) @ w * TRADING_DAYS))

        return PortfolioWeights(
            weights=dict(zip(assets, w.tolist())),
            method="min_cvar",
            expected_return=ret, expected_vol=vol, cvar_95=cvar,
        )

    # ------------------------------------------------------------------
    # 6. Maximum diversification
    # ------------------------------------------------------------------

    @staticmethod
    def max_diversification(
        returns: pd.DataFrame,
        constraints: Optional[Constraints] = None,
    ) -> PortfolioWeights:
        """Maximum diversification ratio portfolio.

        DR = (w' @ sigma_i) / sqrt(w' @ Cov @ w)
        """
        c = constraints or Constraints()
        assets = returns.columns.tolist()
        n = len(assets)
        if n == 0:
            return PortfolioWeights(weights={}, method="max_diversification")

        cov = returns.cov().values * TRADING_DAYS
        vols = np.sqrt(np.diag(cov))

        def neg_dr(w):
            weighted_vol = w @ vols
            port_vol = np.sqrt(w @ cov @ w)
            return -(weighted_vol / port_vol) if port_vol > 1e-12 else 0.0

        x0 = np.ones(n) / n
        bounds = [(c.min_position, c.max_position)] * n
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        res = minimize(neg_dr, x0, method="SLSQP", bounds=bounds,
                        constraints=cons, options={"maxiter": 500})

        w = res.x if res.success else x0
        w = np.maximum(w, 0)
        w /= w.sum()

        dr = float((w @ vols) / np.sqrt(w @ cov @ w)) if np.sqrt(w @ cov @ w) > 1e-12 else 1.0
        mu = returns.mean().values * TRADING_DAYS
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))

        return PortfolioWeights(
            weights=dict(zip(assets, w.tolist())),
            method="max_diversification",
            expected_return=ret, expected_vol=vol,
            diversification_ratio=dr,
        )

    # ------------------------------------------------------------------
    # 7. Regime-conditional construction
    # ------------------------------------------------------------------

    def regime_construct(
        self,
        returns: pd.DataFrame,
        regimes: pd.Series,
        method_map: Optional[Dict[str, OptMethod]] = None,
        constraints: Optional[Constraints] = None,
    ) -> Dict[str, PortfolioWeights]:
        """Run different optimiser per regime."""
        default_map = {
            "bull": OptMethod.MEAN_VARIANCE,
            "bear": OptMethod.MIN_CVAR,
            "high_vol": OptMethod.RISK_PARITY,
            "low_vol": OptMethod.MAX_DIVERSIFICATION,
            "crash": OptMethod.MIN_CVAR,
        }
        mm = method_map or default_map
        aligned = pd.DataFrame(returns).assign(regime=regimes).dropna()

        results: Dict[str, PortfolioWeights] = {}
        for regime, grp in aligned.groupby("regime"):
            regime_str = str(regime)
            method = mm.get(regime_str, OptMethod.RISK_PARITY)
            regime_ret = grp.drop(columns="regime")
            if len(regime_ret) < 5:
                results[regime_str] = self.risk_parity(regime_ret)
                continue
            results[regime_str] = self.construct(regime_ret, method, constraints=constraints)

        return results

    # ------------------------------------------------------------------
    # Unified construct
    # ------------------------------------------------------------------

    def construct(
        self,
        returns: pd.DataFrame,
        method: OptMethod = OptMethod.MEAN_VARIANCE,
        constraints: Optional[Constraints] = None,
        views: Optional[List[BLView]] = None,
    ) -> PortfolioWeights:
        """Dispatch to the chosen method."""
        if method == OptMethod.MEAN_VARIANCE:
            return self.mean_variance(returns, constraints)
        if method == OptMethod.BLACK_LITTERMAN:
            return self.black_litterman(returns, views or [], constraints=constraints)
        if method == OptMethod.RISK_PARITY:
            return self.risk_parity(returns)
        if method == OptMethod.HRP:
            return self.hrp(returns)
        if method == OptMethod.MIN_CVAR:
            return self.min_cvar(returns, constraints)
        if method == OptMethod.MAX_DIVERSIFICATION:
            return self.max_diversification(returns, constraints)
        return self.risk_parity(returns)

    # ------------------------------------------------------------------
    # Constraint enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def apply_turnover_limit(
        current: Dict[str, float],
        target: Dict[str, float],
        max_turnover: float,
    ) -> Dict[str, float]:
        """Limit total turnover between current and target allocations."""
        all_assets = set(current) | set(target)
        deltas = {a: target.get(a, 0.0) - current.get(a, 0.0) for a in all_assets}
        total_turnover = sum(abs(d) for d in deltas.values())

        if total_turnover <= max_turnover:
            return dict(target)

        scale = max_turnover / total_turnover
        result = {a: current.get(a, 0.0) + deltas[a] * scale for a in all_assets}
        total = sum(result.values())
        if total > 0:
            result = {a: v / total for a, v in result.items()}
        return result

    @staticmethod
    def apply_sector_limits(
        weights: Dict[str, float],
        sector_map: Dict[str, str],
        max_sector: float,
    ) -> Dict[str, float]:
        """Cap total weight per sector, redistributing excess to others."""
        result = dict(weights)

        for _ in range(5):  # iterate to handle cascading
            sector_totals: Dict[str, float] = {}
            for a, w in result.items():
                sec = sector_map.get(a, "other")
                sector_totals[sec] = sector_totals.get(sec, 0.0) + w

            capped_any = False
            excess = 0.0
            uncapped_total = 0.0
            for sec, total in sector_totals.items():
                if total > max_sector:
                    scale = max_sector / total
                    for a in result:
                        if sector_map.get(a, "other") == sec:
                            old = result[a]
                            result[a] = old * scale
                            excess += old - result[a]
                    capped_any = True
                else:
                    uncapped_total += total

            if not capped_any or excess <= 0 or uncapped_total <= 0:
                break

            # Redistribute excess to uncapped sectors proportionally
            for a in result:
                sec = sector_map.get(a, "other")
                if sector_totals.get(sec, 0) <= max_sector:
                    result[a] += result[a] / uncapped_total * excess

        # Final normalise
        total = sum(result.values())
        if total > 0:
            result = {a: v / total for a, v in result.items()}
        return result

    # ------------------------------------------------------------------
    # Risk contributions
    # ------------------------------------------------------------------

    @staticmethod
    def risk_contributions(
        returns: pd.DataFrame,
        weights: Dict[str, float],
    ) -> List[RiskContribution]:
        """Compute marginal risk contribution per asset."""
        assets = returns.columns.tolist()
        w = np.array([weights.get(a, 0.0) for a in assets])
        cov = returns.cov().values * TRADING_DAYS
        port_vol = np.sqrt(w @ cov @ w) if w @ cov @ w > 0 else 1e-8

        cov_w = cov @ w
        results: List[RiskContribution] = []
        for i, a in enumerate(assets):
            mrc = float(w[i] * cov_w[i] / port_vol)
            pct = mrc / port_vol if port_vol > 1e-12 else 0.0
            results.append(RiskContribution(
                asset=a, weight=float(w[i]),
                marginal_risk=mrc, pct_contribution=pct,
            ))
        return results

    # ------------------------------------------------------------------
    # Efficient frontier
    # ------------------------------------------------------------------

    def efficient_frontier(
        self,
        returns: pd.DataFrame,
        n_points: int = 20,
    ) -> pd.DataFrame:
        """Compute efficient frontier points."""
        assets = returns.columns.tolist()
        n = len(assets)
        if n == 0:
            return pd.DataFrame()

        mu = returns.mean().values * TRADING_DAYS
        cov = ledoit_wolf_shrinkage(returns) * TRADING_DAYS

        target_rets = np.linspace(float(mu.min()), float(mu.max()), n_points)
        rows = []

        for tr in target_rets:
            def obj(w):
                return float(w @ cov @ w)

            x0 = np.ones(n) / n
            bounds = [(0.0, 0.40)] * n
            cons = [
                {"type": "eq", "fun": lambda w: w.sum() - 1.0},
                {"type": "eq", "fun": lambda w, t=tr: w @ mu - t},
            ]
            res = minimize(obj, x0, method="SLSQP", bounds=bounds,
                            constraints=cons, options={"maxiter": 300})
            if res.success:
                vol = float(np.sqrt(res.fun))
                rows.append({"return": tr, "volatility": vol})

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Full construction
    # ------------------------------------------------------------------

    def full_construct(
        self,
        returns: pd.DataFrame,
        method: OptMethod = OptMethod.MEAN_VARIANCE,
        constraints: Optional[Constraints] = None,
        views: Optional[List[BLView]] = None,
        compute_frontier: bool = False,
    ) -> ConstructionResult:
        """Run construction + risk decomposition + optional frontier."""
        portfolio = self.construct(returns, method, constraints, views)
        rc = self.risk_contributions(returns, portfolio.weights)

        ef = None
        if compute_frontier:
            ef = self.efficient_frontier(returns)

        return ConstructionResult(
            portfolio=portfolio,
            risk_contributions=rc,
            efficient_frontier=ef,
        )

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    @staticmethod
    def _svg_pie(
        slices: List[Tuple[str, float, str]],
        width: int = 280, height: int = 280, title: str = "",
    ) -> str:
        if not slices or all(f <= 0 for _, f, _ in slices):
            return ""
        cx, cy, r = width // 2, height // 2 - 8, min(width, height) // 2 - 35
        p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" style="background:#fff;border:1px solid #ddd;'
             f'border-radius:6px;margin:.5rem 0">']
        if title:
            p.append(f'<text x="{cx}" y="16" text-anchor="middle" font-size="12" '
                     f'font-weight="bold" fill="#1a1a2e">{title}</text>')
        angle = -90.0
        for label, frac, color in slices:
            if frac <= 0:
                continue
            s_rad = np.radians(angle)
            sweep = frac * 360
            e_rad = np.radians(angle + sweep)
            lg = 1 if sweep > 180 else 0
            x1 = cx + r * np.cos(s_rad)
            y1 = cy + r * np.sin(s_rad)
            x2 = cx + r * np.cos(e_rad)
            y2 = cy + r * np.sin(e_rad)
            p.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
                     f'A{r},{r} 0 {lg} 1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>')
            mid = np.radians(angle + sweep / 2)
            lx = cx + r * 0.55 * np.cos(mid)
            ly = cy + r * 0.55 * np.sin(mid)
            p.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" '
                     f'font-size="9" fill="#fff" font-weight="bold">{frac:.0%}</text>')
            angle += sweep
        lx, ly = 5, height - 14
        for label, frac, color in slices:
            if frac <= 0:
                continue
            p.append(f'<rect x="{lx}" y="{ly}" width="8" height="8" fill="{color}"/>')
            p.append(f'<text x="{lx + 11}" y="{ly + 7}" font-size="9" fill="#333">{label}</text>')
            lx += max(len(label) * 6 + 18, 50)
        p.append("</svg>")
        return "\n".join(p)

    @staticmethod
    def _svg_frontier(
        ef: pd.DataFrame, port_ret: float, port_vol: float,
        width: int = 500, height: int = 280,
    ) -> str:
        if ef.empty:
            return ""
        xs = ef["volatility"].tolist()
        ys = ef["return"].tolist()
        xmin, xmax = min(xs) * 0.9, max(xs) * 1.1
        ymin, ymax = min(ys) * 0.9, max(ys) * 1.1
        if xmax <= xmin:
            xmax = xmin + 0.01
        if ymax <= ymin:
            ymax = ymin + 0.01
        pad_l, pad_r, pad_t, pad_b = 55, 15, 28, 30
        pw = width - pad_l - pad_r
        ph = height - pad_t - pad_b

        def tx(v): return pad_l + (v - xmin) / (xmax - xmin) * pw
        def ty(v): return pad_t + (1 - (v - ymin) / (ymax - ymin)) * ph

        p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" style="background:#fff;border:1px solid #ddd;'
             f'border-radius:6px;margin:.5rem 0">']
        p.append(f'<text x="{width // 2}" y="16" text-anchor="middle" font-size="12" '
                 f'font-weight="bold" fill="#1a1a2e">Efficient Frontier</text>')
        d = " ".join(f"{'M' if i == 0 else 'L'}{tx(xs[i]):.1f},{ty(ys[i]):.1f}"
                      for i in range(len(xs)))
        p.append(f'<path d="{d}" fill="none" stroke="#2980b9" stroke-width="2"/>')
        # Current portfolio dot
        p.append(f'<circle cx="{tx(port_vol):.1f}" cy="{ty(port_ret):.1f}" r="5" '
                 f'fill="#e74c3c" stroke="#fff" stroke-width="1.5"/>')
        p.append(f'<text x="{tx(port_vol) + 8:.0f}" y="{ty(port_ret) + 4:.0f}" '
                 f'font-size="9" fill="#e74c3c">Portfolio</text>')
        p.append("</svg>")
        return "\n".join(p)

    def generate_report(
        self,
        result: ConstructionResult,
        regime_portfolios: Optional[Dict[str, PortfolioWeights]] = None,
        output_path: str = "reports/portfolio_construction.html",
    ) -> str:
        """HTML report: frontier, pie, risk contribution, regime allocations."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        pw = result.portfolio
        palette = ["#2980b9", "#e74c3c", "#27ae60", "#e67e22", "#8e44ad",
                    "#1abc9c", "#d35400", "#2c3e50", "#f39c12", "#c0392b"]
        slices = [(a, w, palette[i % len(palette)])
                   for i, (a, w) in enumerate(pw.weights.items()) if w > 0.001]
        pie_svg = self._svg_pie(slices, title="Allocation")

        # Frontier
        frontier_svg = ""
        if result.efficient_frontier is not None:
            frontier_svg = self._svg_frontier(
                result.efficient_frontier, pw.expected_return, pw.expected_vol)

        # Risk contribution table
        rc_rows = []
        for rc in result.risk_contributions:
            rc_rows.append(
                f"<tr><td>{rc.asset}</td><td>{rc.weight:.2%}</td>"
                f"<td>{rc.marginal_risk:.6f}</td><td>{rc.pct_contribution:.1%}</td></tr>")

        # Regime allocations
        regime_html = ""
        if regime_portfolios:
            rows = []
            for regime, rpw in sorted(regime_portfolios.items()):
                top = sorted(rpw.weights.items(), key=lambda x: x[1], reverse=True)[:3]
                top_str = ", ".join(f"{a}: {w:.0%}" for a, w in top)
                rows.append(
                    f"<tr><td>{regime}</td><td>{rpw.method}</td>"
                    f"<td>{rpw.sharpe:.2f}</td><td>{top_str}</td></tr>")
            regime_html = f"""
<h2>Regime Allocations</h2>
<table><tr><th>Regime</th><th>Method</th><th>Sharpe</th><th>Top Weights</th></tr>
{''.join(rows)}</table>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Portfolio Construction</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 2rem; background: #f5f5f5; color: #1a1a2e; }}
h1 {{ color: #1a1a2e; border-bottom: 2px solid #16213e; padding-bottom: .5rem; }}
h2 {{ color: #16213e; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; background: #fff;
         border-radius: 6px; overflow: hidden; }}
table.m {{ width: auto; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
th {{ background: #16213e; color: #fff; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #fff; padding: 1.2rem 1.5rem; border-radius: 8px;
            margin: 1rem 0; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.charts {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
</style></head><body>
<h1>Portfolio Construction Report</h1>
<div class="summary">
<p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<p><strong>Method:</strong> {pw.method} |
   <strong>Sharpe:</strong> {pw.sharpe:.2f} |
   <strong>Return:</strong> {pw.expected_return:.2%} |
   <strong>Vol:</strong> {pw.expected_vol:.2%}</p>
</div>

<div class="charts">
{pie_svg}
{frontier_svg}
</div>

<h2>Risk Contributions</h2>
<table><tr><th>Asset</th><th>Weight</th><th>Marginal Risk</th><th>% Contribution</th></tr>
{''.join(rc_rows)}</table>

{regime_html}
</body></html>"""

        path.write_text(html, encoding="utf-8")
        logger.info("Portfolio construction report -> %s", path)
        return str(path)
