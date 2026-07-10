#!/usr/bin/env python3
"""EXP-503-BT-CORE — honest-fill (FIX #3) re-run of the EXP-503 credit-spread core.

IMPORTANT: EXP-503 ("ML V2 Aggressive", paper_exp503.yaml) has NO faithful
backtest twin — the ML overlay (RegimeModelRouter multipliers, regime_gate
signal suppression, 25% joblib signal-model blend, min_score_threshold) is
disconnected from the backtest path by design (main.py:139-141), and the
registry's backtest_config (configs/exp_503_lowvol_narrow_spread.json) does
not exist in this repo and referred to a different low-vol-sweep experiment
that shared the number. This runner therefore backtests the CORE ONLY
(the config header's own "EXP-401 core, no ML sizing" baseline) so the
naive-vs-marketable fill-model delta can be measured on the same scan path.
Results must not be quoted as "EXP-503 backtest" without that caveat.
See config.json fidelity_notes.

Real engine (backtest/backtester.py) on offline real marks
(data/options_cache.db), SPY 2020-01-02..2026-04-02, real VIX/VIX3M via the
post-8f1bc8c indices loader. Offline only — no broker/live/deploy changes.

Variants (first arg):
  cb40  — engine drawdown breaker at the yaml's drawdown_cb_pct=40 (config-
          faithful). NOTE: on this window the -40% DD halt latches in 2021 and
          entries never resume, so 2022-2026 is flat.
  nocb  — breaker disabled (drawdown_cb_pct=1000) so the naive-vs-marketable
          fill delta is measured across the full window.

Usage:  .venv/bin/python experiments/EXP-503-BT-honest-fills/run.py cb40 naive
        .venv/bin/python experiments/EXP-503-BT-honest-fills/run.py nocb marketable
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


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
    variant = sys.argv[1] if len(sys.argv) > 1 else "cb40"
    assert variant in ("cb40", "nocb"), f"unknown variant {variant}"
    fill_model = sys.argv[2] if len(sys.argv) > 2 else "naive"
    assert fill_model in ("naive", "marketable"), f"unknown fill_model {fill_model}"

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for underlying daily bars only

    cfg = json.loads(CONFIG_PATH.read_text())
    start = datetime.fromisoformat(cfg["window"]["start"])
    end = datetime.fromisoformat(cfg["window"]["end"])

    engine_config = {
        "backtest": {
            "starting_capital": cfg["backtest"]["starting_capital"],
            "commission_per_contract": cfg["backtest"]["commission_per_contract"],
            "slippage": cfg["backtest"]["slippage"],
            "exit_slippage": cfg["backtest"]["exit_slippage"],
            "sizing_mode": cfg["backtest"]["sizing_mode"],
            "compound": cfg["backtest"]["compound"],
            "fill_model": fill_model,
        },
        "strategy": {
            "direction": cfg["direction"],
            "target_dte": cfg["target_dte"],
            "min_dte": cfg["min_dte"],
            "max_dte": cfg["max_dte"],
            "use_delta_selection": False,
            "spread_width": cfg["spread_width"],
            "regime_mode": cfg["regime_mode"],
            "regime_config": cfg["regime_config"],
            "iron_condor": dict(cfg["iron_condor"]),
            "min_credit_pct": cfg["min_credit_pct"],
            "vix_max_entry": cfg["vix_max_entry"],
            "momentum_filter_pct": None,  # in yaml, never applied by deployed scan path
            "trend_ma_period": 80,        # unused in combo mode; drives warmup window
            "max_positions_per_expiration": cfg["backtest"]["max_positions_per_expiration"],
        },
        "risk": {
            "max_risk_per_trade": cfg["max_risk_per_trade"],
            "max_contracts": cfg["max_contracts"],
            "max_positions": cfg["max_positions"],
            "profit_target": cfg["profit_target"],
            "stop_loss_multiplier": cfg["stop_loss_multiplier"],
            "drawdown_cb_pct": cfg["drawdown_cb_pct"] if variant == "cb40" else 1000,
        },
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(cfg["otm_pct"]))

    results = bt.run_backtest(ticker=cfg["ticker"], start_date=start, end_date=end)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    equity = [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
              for d, v in bt.equity_curve]
    years = (end - start).days / 365.25
    ending = float(results["ending_capital"])
    cagr = ((ending / cfg["backtest"]["starting_capital"]) ** (1 / years) - 1) * 100 if ending > 0 else -100.0

    exit_reasons = {}
    trades_by_type = {}
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1
        trades_by_type[t.get("type", "?")] = trades_by_type.get(t.get("type", "?"), 0) + 1

    summary = {
        "experiment": "EXP-503-BT-CORE",
        "not_a_faithful_twin": True,
        "variant": variant,
        "fill_model": fill_model,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "fill_model_naive_fallbacks": results.get("fill_model_naive_fallbacks", 0),
        "window": [start.date().isoformat(), end.date().isoformat()],
        "config": os.path.relpath(str(CONFIG_PATH), str(ROOT)),
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
        "trades_by_type": trades_by_type,
        "equity_curve": equity,
        "trades": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()}
            for t in results.get("trades", [])
        ],
    }
    out = OUT / f"SPY_core_{variant}_{fill_model}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    m = summary["metrics"]
    print(f"[EXP-503-BT-CORE/{variant}/{fill_model}] unfilled={summary['unfilled_entries']} "
          f"naive_fallbacks={summary['fill_model_naive_fallbacks']}")
    print(f"trades={m['total_trades']} CAGR={m['cagr_pct']}% total={m['return_pct']}% "
          f"sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown_pct']}% winrate={m['win_rate']}%")
    print(f"per-year: {summary['per_year_returns_pct']}")
    print(f"exits: {exit_reasons}  types: {trades_by_type}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
