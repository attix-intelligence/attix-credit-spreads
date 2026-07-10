#!/usr/bin/env python3
"""EXP-V8A-BT — per-stream honest-fill (FIX #3) backtests of the 4 live VRP
credit-spread streams (exp1220 / qqq_cs / xlf_cs / xli_cs).

WHY PER-STREAM: EXP-V8A has NO full-portfolio backtest twin runnable under
FIX #3. The registry's backtest_config is null; the Sharpe-6.39 v8a figures
came from compass-level portfolio backtests over stream return series, not
from backtest/backtester.py where the fill_model flag lives; the live
allocator (Ledoit-Wolf risk parity + 12% vol target + dollar-notional sizer)
and 4 of the 8 designed streams (gld_cal/slv_cal futures basis, cross_vol,
v5_hedge) are outside the options credit-spread engine entirely. What CAN be
run honestly is each live credit-spread stream through the real engine on
real marks (data/options_cache.db), naive vs marketable, then a documented
fixed-weight aggregation (aggregate.py). See report fidelity notes.

Stream rules ported from compass/exp2690_signal_generators.py (the live
signal source):
  exp1220 — SPY, short-delta 0.30, DTE 28, $5 width, Monday entries,
            VIX>40 block, VIX>VIX3M term-inversion block, VoV z>2 block,
            VoV 1<z<=2 half size (EXP-1970 panel, causal prior-day closes)
  qqq_cs  — QQQ, delta 0.25, DTE 30, $5, Monday, VIX>40 block
  xlf_cs  — XLF, delta 0.20, DTE 30, $5, Monday, VIX>40 block
  xli_cs  — XLI, delta 0.20, DTE 30, $5, Monday, VIX>40 block
Exits per configs/paper_expv8a.yaml vrp_position_monitor (documented spec):
  profit target 50% of credit, stop 2x credit, close at <=7 DTE,
  crisis close-all when VIX > 45. One open position per stream.

Sizing is flat 5% max-loss per trade on $100k (NOT live-faithful — live uses
the vol-target allocator; see fidelity notes). Both fill models share it, so
the naive-vs-marketable delta is unaffected.

Window: 2020-01-02 .. 2025-12-19 for ALL streams (common window; QQQ option
marks in options_cache.db end 2025-12-19).

Usage:  .venv/bin/python experiments/EXP-V8A-BT-honest-fills/run_stream.py exp1220 naive
        .venv/bin/python experiments/EXP-V8A-BT-honest-fills/run_stream.py qqq_cs marketable
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WINDOW = ("2020-01-02", "2025-12-19")

STREAMS = {
    # stream: (ticker, short_delta, target_dte, extra exp1220 gates?)
    "exp1220": ("SPY", 0.30, 28, True),
    "qqq_cs":  ("QQQ", 0.25, 30, False),
    "xlf_cs":  ("XLF", 0.20, 30, False),
    "xli_cs":  ("XLI", 0.20, 30, False),
}

CRISIS_VIX = 45.0   # vrp_position_monitor.crisis_vix
ROLL_DTE = 7        # vrp_position_monitor.roll_dte
BASE_RISK_PCT = 5.0  # flat per-trade max-loss %, shared by both fill models


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_index_closes(symbol: str):
    """Daily closes for I:VIX / I:VIX3M from data/historical_indices.sqlite."""
    import pandas as pd
    con = sqlite3.connect(ROOT / "data" / "historical_indices.sqlite")
    rows = con.execute(
        "SELECT date, close FROM historical_indices WHERE ticker=? ORDER BY date",
        (symbol,),
    ).fetchall()
    con.close()
    s = pd.Series({pd.Timestamp(d): float(c) for d, c in rows}).sort_index()
    return s


class StreamOverlay:
    """Ports the exp2690 stream gates + vrp_position_monitor exits onto the
    engine. All gates use PRIOR-day index closes (the live 9:25 ET generator
    only has the previous session's completed bar)."""

    def __init__(self, bt, exp1220_gates: bool):
        import pandas as pd
        self.bt = bt
        self.exp1220_gates = exp1220_gates
        self.vix = _load_index_closes("I:VIX")
        self.vix3m = _load_index_closes("I:VIX3M")
        self.vvol_z = None
        if exp1220_gates:
            from compass.exp1970_vol_of_vol import build_vvol_panel
            self.vvol_z = build_vvol_panel(self.vix)["vvol_z"]

        self.block_entries = True
        self.gate_log = {"not_monday": 0, "vix40": 0, "term_inversion": 0,
                         "vov_block": 0, "vov_half": 0, "crisis_close": 0,
                         "roll_dte_close": 0}

        # Kill the engine's legacy-mode trend-MA gate: the live stream
        # generators have no trend filter (VIX gates only).
        bt._compute_trend_ma = lambda closes: 0.0

        self._orig_manage = bt._manage_positions
        bt._manage_positions = self._wrapped_manage
        self._orig_find = bt._find_backtest_opportunity
        bt._find_backtest_opportunity = self._gated_find

    def _prior(self, series, date):
        """Last value strictly before `date` (causal: prior session close)."""
        import pandas as pd
        s = series[series.index < pd.Timestamp(date.date() if hasattr(date, "date") else date)]
        return float(s.iloc[-1]) if len(s) else None

    def _gated_find(self, *a, **kw):
        if self.block_entries:
            return None
        return self._orig_find(*a, **kw)

    def _close_at_marks(self, pos, current_date, reason):
        date_str = current_date.strftime("%Y-%m-%d")
        prices = self.bt.historical_data.get_spread_prices(
            pos["ticker"], pos["expiration"],
            pos["short_strike"], pos["long_strike"],
            pos.get("option_type", "P"), date_str)
        if prices is not None:
            exit_cost = prices["spread_value"] + self.bt._vix_scaled_exit_slippage()
            pnl = (pos["credit"] - exit_cost) * pos["contracts"] * 100 - pos["commission"]
        else:
            slip = self.bt._vix_scaled_exit_slippage() * pos["contracts"] * 100
            pnl = pos.get("current_value", 0) - slip - pos["commission"]
            reason += "_marked"
        self.bt._record_close(pos, current_date, pnl, reason)

    def _wrapped_manage(self, positions, current_date, current_price, ticker=""):
        positions = self._orig_manage(positions, current_date, current_price, ticker)

        vix_prior = self._prior(self.vix, current_date)

        # vrp_position_monitor exits not native to the engine:
        # crisis close-all (VIX > 45) and roll/close at <= 7 DTE.
        keep = []
        for pos in positions:
            dte = (pos["expiration"] - current_date).days
            if vix_prior is not None and vix_prior > CRISIS_VIX:
                self._close_at_marks(pos, current_date, "crisis_vix_close")
                self.gate_log["crisis_close"] += 1
            elif dte <= ROLL_DTE:
                self._close_at_marks(pos, current_date, "roll_dte_close")
                self.gate_log["roll_dte_close"] += 1
            else:
                keep.append(pos)
        positions = keep

        # ── entry gates for today (live generator logic, causal) ──
        block, risk_mult = False, 1.0
        if current_date.weekday() != 0:
            block = True
            self.gate_log["not_monday"] += 1
        elif vix_prior is None or vix_prior > 40.0:
            block = True
            self.gate_log["vix40"] += 1
        elif self.exp1220_gates:
            vix3m_prior = self._prior(self.vix3m, current_date)
            if vix3m_prior is not None and vix_prior > vix3m_prior:
                block = True
                self.gate_log["term_inversion"] += 1
            else:
                z = self._prior(self.vvol_z, current_date)
                if z is not None:
                    if z > 2.0:
                        block = True
                        self.gate_log["vov_block"] += 1
                    elif z > 1.0:
                        risk_mult = 0.5
                        self.gate_log["vov_half"] += 1

        self.block_entries = block
        self.bt.risk_params["max_risk_per_trade"] = BASE_RISK_PCT * risk_mult
        return positions


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
    stream = sys.argv[1] if len(sys.argv) > 1 else "exp1220"
    assert stream in STREAMS, f"unknown stream {stream} — one of {list(STREAMS)}"
    fill_model = sys.argv[2] if len(sys.argv) > 2 else "naive"
    assert fill_model in ("naive", "marketable"), f"unknown fill_model {fill_model}"

    ticker, short_delta, target_dte, exp1220_gates = STREAMS[stream]

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for underlying daily bars only

    start = datetime.fromisoformat(WINDOW[0])
    end = datetime.fromisoformat(WINDOW[1])

    engine_config = {
        "backtest": {
            "starting_capital": 100000,
            "commission_per_contract": 0.65,
            "slippage": 0.05,
            "exit_slippage": 0.10,
            "sizing_mode": "flat",
            "compound": False,
            "fill_model": fill_model,
        },
        "strategy": {
            "direction": "bull_put",          # streams are put-credit-spread only
            "target_dte": target_dte,
            "min_dte": 25,                    # vrp_engine.dte_range [25, 50]
            "max_dte": 50,
            "use_delta_selection": True,
            "target_delta": short_delta,
            "spread_width": 5,
            "iron_condor": {"enabled": False},
            "min_credit_pct": 0,              # streams have no credit floor
            "vix_max_entry": 0,               # gate handled by overlay (prior-day close)
            "momentum_filter_pct": None,      # no momentum filter in stream generators
            "trend_ma_period": 20,            # neutralized by overlay (no trend filter live)
            "max_positions_per_expiration": 1,
        },
        "risk": {
            "max_risk_per_trade": BASE_RISK_PCT,  # overlay rescales (VoV half-size)
            "max_contracts": 50,
            "max_positions": 1,               # stream_gates.max_open_per_stream = 1
            "profit_target": 50,              # vrp_position_monitor.profit_target_pct
            "stop_loss_multiplier": 2.0,      # vrp_position_monitor.stop_loss_mult
            "drawdown_cb_pct": 1000,          # no per-stream breaker live
        },
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist)
    overlay = StreamOverlay(bt, exp1220_gates=exp1220_gates)

    results = bt.run_backtest(ticker=ticker, start_date=start, end_date=end)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    equity = [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
              for d, v in bt.equity_curve]
    years = (end - start).days / 365.25
    ending = float(results["ending_capital"])
    cagr = ((ending / 100000) ** (1 / years) - 1) * 100 if ending > 0 else -100.0

    exit_reasons = {}
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    summary = {
        "experiment": "EXP-V8A-BT",
        "stream": stream,
        "ticker": ticker,
        "fill_model": fill_model,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "fill_model_naive_fallbacks": results.get("fill_model_naive_fallbacks", 0),
        "window": [start.date().isoformat(), end.date().isoformat()],
        "stream_params": {"short_delta": short_delta, "target_dte": target_dte,
                          "width": 5, "risk_pct_flat": BASE_RISK_PCT},
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
        "gate_log": overlay.gate_log,
        "exit_reasons": exit_reasons,
        "equity_curve": equity,
        "trades": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()}
            for t in results.get("trades", [])
        ],
    }
    out = OUT / f"{stream}_{fill_model}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    m = summary["metrics"]
    print(f"[EXP-V8A-BT/{stream}/{fill_model}] unfilled={summary['unfilled_entries']} "
          f"naive_fallbacks={summary['fill_model_naive_fallbacks']} gates={overlay.gate_log}")
    print(f"trades={m['total_trades']} CAGR={m['cagr_pct']}% total={m['return_pct']}% "
          f"sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown_pct']}% winrate={m['win_rate']}%")
    print(f"per-year: {summary['per_year_returns_pct']}")
    print(f"exits: {exit_reasons}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
