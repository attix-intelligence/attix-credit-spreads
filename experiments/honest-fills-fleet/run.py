#!/usr/bin/env python3
"""Honest-fills fleet re-run (FIX #3) — engine twins for EXP-1220 / EXP-400 / EXP-401-core.

Runs the real engine (backtest/backtester.py) on offline Polygon marks
(data/options_cache.db), SPY 2020-01-02..2026-04-02, real VIX/VIX3M via the
post-8f1bc8c indices loader — the same window/data as EXP-800-BT so results
are comparable across the fleet. Naive vs marketable fill models (FIX #3).

Twin configs are transcribed from the deployed paper YAMLs:
  exp400     — configs/paper_champion.yaml  (CS+IC champion core, 17% flat)
  exp401core — configs/paper_exp401.yaml    CS+IC core ONLY. NOT a faithful
               EXP-401 twin: the engine cannot represent the straddle_strangle
               post-FOMC/CPI overlay or the regime_scale_* risk multipliers.
               Run and reported as a labeled PROXY of the shared champion core.
  exp1220    — configs/paper_exp1220.yaml   (bull puts, 30 DTE, 5% OTM, 5-wide,
               9.35% flat) + two harness shims the engine lacks:
                 * Monday-only entries (risk.scan_days [0])
                 * manage_dte 5 — force-close positions under 5 DTE at real marks
               Remaining fidelity gaps are documented in the report, not shimmed.

Usage:  .venv/bin/python experiments/honest-fills-fleet/run.py exp1220 marketable
Offline only: never touches Tradier/Alpaca/paper workers. New file — no
existing code modified.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WINDOW = ("2020-01-02", "2026-04-02")

# ── HOLDOUT SEAL ─────────────────────────────────────────────────────────────
# The 2025-01-01+ holdout is single-use and sealed until Carlos's explicit
# written signature (relayed by Maximus). The cache physically contains
# post-2024 bars (PROG0 extension backfills), so the seal must be enforced
# here, not assumed. Every runner in this directory calls assert_holdout_seal
# before touching the engine. Lift ONLY by setting HOLDOUT_SPEND_SIGNED with
# the signature reference in the calling environment.
HOLDOUT_SEAL_END = "2024-12-31"

def assert_holdout_seal(end_date_iso: str) -> None:
    import os
    if end_date_iso[:10] <= HOLDOUT_SEAL_END:
        return
    sig = os.environ.get("HOLDOUT_SPEND_SIGNED", "")
    if not sig:
        raise SystemExit(
            f"HOLDOUT SEAL: end_date {end_date_iso} exceeds {HOLDOUT_SEAL_END} and no "
            "Carlos-signed spend is recorded (HOLDOUT_SPEND_SIGNED unset). Refusing to run."
        )
BACKTEST_BLOCK = {
    "starting_capital": 100000,
    "commission_per_contract": 0.65,
    "slippage": 0.05,
    "exit_slippage": 0.1,
    "sizing_mode": "flat",
    "compound": False,  # paper YAMLs: fixed sizing off account_size (compound: false)
}

REGIME_CHAMPION = {  # champion-family combo config (G21 parity, ma_slow 80)
    "signals": ["price_vs_ma200", "rsi_momentum", "vix_structure"],
    "ma_slow_period": 80,
    "ma200_neutral_band_pct": 0.5,
    "rsi_period": 14,
    "rsi_bull_threshold": 50.0,
    "rsi_bear_threshold": 45.0,
    "vix_structure_bull": 0.95,
    "vix_structure_bear": 1.05,
    "bear_requires_unanimous": True,
    "cooldown_days": 3,
    "vix_extreme": 40.0,
    "vix_extreme_regime": "NEUTRAL",
}
REGIME_1220 = {**REGIME_CHAMPION, "ma_slow_period": 50}  # paper_exp1220 regime_config

EXPERIMENTS = {
    "exp400": {
        "label": "EXP-400",
        "otm_pct": 0.02,
        "strategy": {
            "direction": "both",
            "target_dte": 15, "min_dte": 15, "max_dte": 25,
            "use_delta_selection": False,
            "spread_width": 12,
            "regime_mode": "combo",
            "regime_config": REGIME_CHAMPION,
            "iron_condor": {"enabled": True, "neutral_regime_only": True},
            "min_credit_pct": 5,
            "vix_max_entry": 0,   # paper_champion.yaml has no VIX entry gate
            "momentum_filter_pct": None,  # in yaml, never applied by deployed scanner
            "trend_ma_period": 80,
            "max_positions_per_expiration": 4,  # risk.portfolio_risk.max_same_expiration
        },
        "risk": {
            "max_risk_per_trade": 17.0,
            "max_contracts": 30,
            "max_positions": 10,
            "profit_target": 55,
            "stop_loss_multiplier": 1.25,
            "drawdown_cb_pct": 40,  # paper yaml risk.drawdown_cb_pct
        },
        "monday_only": False,
        "manage_dte": 0,
    },
    "exp401core": {
        "label": "EXP-401-core (PROXY — see report)",
        "otm_pct": 0.02,
        "strategy": {
            "direction": "both",
            "target_dte": 15, "min_dte": 15, "max_dte": 25,
            "use_delta_selection": False,
            "spread_width": 12,
            "regime_mode": "combo",
            "regime_config": REGIME_CHAMPION,
            "iron_condor": {"enabled": True, "neutral_regime_only": True},
            "min_credit_pct": 5,  # paper_exp401.yaml risk.min_credit_pct
            "vix_max_entry": 0,
            "momentum_filter_pct": None,
            "trend_ma_period": 80,
            "max_positions_per_expiration": 4,
        },
        "risk": {
            "max_risk_per_trade": 17.0,
            "max_contracts": 30,
            "max_positions": 12,
            "profit_target": 55,
            "stop_loss_multiplier": 1.25,
            "drawdown_cb_pct": 40,
        },
        "monday_only": False,
        "manage_dte": 0,
    },
    # Fidelity-gap re-test (Rev 2 of cc1 proposal, 2026-07-10): live-code audit
    # showed scan_days, drawdown_cb_pct, and technical.use_trend_filter are ALL
    # dead config (no references in the deployed scan path; broker record shows
    # daily entries). Faithful twin therefore: no Monday gate, engine breaker
    # disabled. manage_dte (live, credit_spread.py:301) and vix_max_entry
    # (live, compass/risk_gate.py:264 rule 7.5) retained.
    "exp1220_faithful": {
        "label": "EXP-1220-faithful",
        "otm_pct": 0.05,
        "strategy": {
            "direction": "both",
            "target_dte": 30, "min_dte": 21, "max_dte": 45,
            "use_delta_selection": False,
            "spread_width": 5,
            "regime_mode": "combo",
            "regime_config": REGIME_1220,
            "iron_condor": {"enabled": False},
            "min_credit_pct": 6,
            "vix_max_entry": 35.0,
            "momentum_filter_pct": None,
            "trend_ma_period": 50,
            "max_positions_per_expiration": 3,
        },
        "risk": {
            "max_risk_per_trade": 9.35,
            "max_contracts": 20,
            "max_positions": 5,
            "profit_target": 50,
            "stop_loss_multiplier": 2.0,
            "drawdown_cb_pct": 1000,  # dead config live: no per-experiment breaker exists
        },
        "monday_only": False,  # scan_days [0] is dead config; live entered daily (broker record)
        "manage_dte": 5,
    },
    "exp1220": {
        "label": "EXP-1220",
        "otm_pct": 0.05,
        "strategy": {
            "direction": "both",  # yaml says both; combo regime decides. IC disabled.
            "target_dte": 30, "min_dte": 21, "max_dte": 45,
            "use_delta_selection": False,
            "spread_width": 5,
            "regime_mode": "combo",
            "regime_config": REGIME_1220,
            "iron_condor": {"enabled": False},
            "min_credit_pct": 6,  # yaml 0.06 of width = 6% (engine divides by 100)
            "vix_max_entry": 35.0,
            "momentum_filter_pct": None,
            "trend_ma_period": 50,
            "max_positions_per_expiration": 3,
        },
        "risk": {
            "max_risk_per_trade": 9.35,
            "max_contracts": 20,
            "max_positions": 5,
            "profit_target": 50,
            "stop_loss_multiplier": 2.0,
            "drawdown_cb_pct": 10,
        },
        "monday_only": True,   # risk.scan_days: [0]
        "manage_dte": 5,       # strategy.manage_dte: 5
    },
}


class FidelityShims:
    """Harness-level shims for deployed behaviors the engine lacks.

    monday_only — gate all entry finders to weekday()==0 (paper scan_days [0]).
    manage_dte  — force-close open positions when DTE < N at real marks
                  (paper manage_dte; gamma-risk exit), exit reason 'manage_dte'.
    """

    def __init__(self, bt, monday_only: bool, manage_dte: int):
        self.bt = bt
        self.manage_dte = int(manage_dte)
        self.monday_blocked = 0
        self.dte_closes = 0
        if monday_only:
            for name in ("_find_backtest_opportunity", "_find_bear_call_opportunity",
                         "_find_iron_condor_opportunity"):
                setattr(bt, name, self._weekday_gate(getattr(bt, name)))
        if self.manage_dte > 0:
            self._orig_manage = bt._manage_positions
            bt._manage_positions = self._wrapped_manage

    def _weekday_gate(self, orig):
        def fn(*a, **kw):
            date = kw.get("date", a[1] if len(a) > 1 else None)
            if date is not None and date.weekday() != 0:
                self.monday_blocked += 1
                return None
            return orig(*a, **kw)
        return fn

    def _wrapped_manage(self, positions, current_date, current_price, ticker=""):
        positions = self._orig_manage(positions, current_date, current_price, ticker)
        keep = []
        for pos in positions:
            dte = (pos["expiration"] - current_date).days
            if dte > self.manage_dte:  # live closes at dte <= manage_dte (credit_spread.py:301-305)
                keep.append(pos)
                continue
            # force-close at real marks (same pattern as EXP-800-BT flatten)
            date_str = current_date.strftime("%Y-%m-%d")
            prices = self.bt.historical_data.get_spread_prices(
                pos["ticker"], pos["expiration"],
                pos["short_strike"], pos["long_strike"],
                pos.get("option_type", "P"), date_str)
            if prices is not None:
                exit_cost = prices["spread_value"] + self.bt._vix_scaled_exit_slippage()
                pnl = (pos["credit"] - exit_cost) * pos["contracts"] * 100 - pos["commission"]
                reason = "manage_dte"
            else:
                slip = self.bt._vix_scaled_exit_slippage() * pos["contracts"] * 100
                pnl = pos.get("current_value", 0) - slip - pos["commission"]
                reason = "manage_dte_marked"
            self.bt._record_close(pos, current_date, pnl, reason)
            self.dte_closes += 1
        return keep


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _per_year_returns(equity_curve):
    import pandas as pd
    s = pd.Series({pd.Timestamp(d): v for d, v in equity_curve}).sort_index()
    out = {}
    for year, grp in s.groupby(s.index.year):
        prior = s[s.index < grp.index[0]]
        base = prior.iloc[-1] if len(prior) else grp.iloc[0]
        out[int(year)] = round((grp.iloc[-1] / base - 1) * 100, 2)
    return out


def main() -> None:
    exp = sys.argv[1]
    fill_model = sys.argv[2] if len(sys.argv) > 2 else "naive"
    assert exp in EXPERIMENTS, f"unknown experiment {exp}"
    assert fill_model in ("naive", "marketable"), f"unknown fill_model {fill_model}"
    spec = EXPERIMENTS[exp]

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for SPY daily bars only

    start = datetime.fromisoformat(WINDOW[0])
    end = datetime.fromisoformat(WINDOW[1])
    engine_config = {
        "backtest": {**BACKTEST_BLOCK, "fill_model": fill_model},
        "strategy": dict(spec["strategy"]),
        "risk": dict(spec["risk"]),
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    assert_holdout_seal(end.date().isoformat())
    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(spec["otm_pct"]))
    shims = FidelityShims(bt, spec["monday_only"], spec["manage_dte"])

    results = bt.run_backtest(ticker="SPY", start_date=start, end_date=end)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    equity = [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
              for d, v in bt.equity_curve]
    years = (end - start).days / 365.25
    ending = float(results["ending_capital"])
    cagr = ((ending / BACKTEST_BLOCK["starting_capital"]) ** (1 / years) - 1) * 100 if ending > 0 else -100.0

    exit_reasons = {}
    by_type = {}
    for t in results.get("trades", []):
        exit_reasons[str(t.get("exit_reason", "?"))] = exit_reasons.get(str(t.get("exit_reason", "?")), 0) + 1
        by_type[t.get("type", "?")] = by_type.get(t.get("type", "?"), 0) + 1

    summary = {
        "experiment": spec["label"],
        "runner_key": exp,
        "fill_model": fill_model,
        "window": [WINDOW[0], WINDOW[1]],
        "unfilled_entries": results.get("unfilled_entries", 0),
        "fill_model_naive_fallbacks": results.get("fill_model_naive_fallbacks", 0),
        "shims": {"monday_blocked_calls": shims.monday_blocked, "manage_dte_closes": shims.dte_closes},
        "metrics": {
            "cagr_pct": round(cagr, 2),
            "return_pct": results.get("return_pct"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "win_rate": results.get("win_rate"),
            "total_trades": results.get("total_trades"),
            "total_pnl": results.get("total_pnl"),
            "ending_capital": results.get("ending_capital"),
        },
        "per_year_returns_pct": _per_year_returns(bt.equity_curve),
        "exit_reasons": exit_reasons,
        "trades_by_type": by_type,
        "equity_curve": equity,
        "trades": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()}
            for t in results.get("trades", [])
        ],
    }
    out = OUT / f"{exp}_{fill_model}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    m = summary["metrics"]
    print(f"[{exp}/{fill_model}] trades={m['total_trades']} total={m['return_pct']}% "
          f"CAGR={m['cagr_pct']}% sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown_pct']}% "
          f"winrate={m['win_rate']}% unfilled={summary['unfilled_entries']} "
          f"fallbacks={summary['fill_model_naive_fallbacks']} shims={summary['shims']}")


if __name__ == "__main__":
    main()
