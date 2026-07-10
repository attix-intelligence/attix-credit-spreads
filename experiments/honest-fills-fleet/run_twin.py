#!/usr/bin/env python3
"""Honest-fills fleet twins — EXP-3303B / EXP-3309 / EXP-3311 (FIX #3 re-run).

Backtest twins of the three paper-deployed champion-family scanners, built for
the naive-vs-marketable fill-model comparison (FIX #3, commit 11f140c). Modeled
on experiments/EXP-800-BT-safe-kelly/run.py but WITHOUT the Kelly overlay —
these three size flat off a fixed $100k account_size per their paper yamls.

Shared core (all three inherit paper_champion.yaml): SPY credit spreads,
DTE 15 (window 15-25), 2% OTM, $12 wide, PT 55% of credit, SL 1.25x credit,
combo regime direction selection (bull->bull_put, neutral->iron_condor,
bear->bear_call), regime_config passed VERBATIM from each yaml (detector
defaults fill the rest — including cooldown_days=10, unlike EXP-800's 3).

Per-experiment differentiators (ported from the LIVE gate call sites in
main.py scan_opportunities):

  3303b — risk.regime_gate (shared/regime_gate.should_gate_for_regime), gated
          regimes ['transition','high_stress']. Ported VERBATIM — which means
          it can never fire: the live pipeline feeds it the ComboRegimeDetector
          output ('bull'|'neutral'|'bear'), a vocabulary that does not contain
          the gated states. The twin counts evaluations/fires to demonstrate
          the deployed gate is a structural no-op.
  3309  — execution.window_only 15:30-16:00 ET: entries allowed only at scan
          slots 15:30..15:55 (engine 5-min slot grid). Exits are NOT window-
          gated, matching live (PositionMonitor runs on its own cadence; only
          scan_opportunities is gated).
  3311  — entry_gate.nfp_filter: skip entries when tomorrow (next CALENDAR
          day, per shared/entry_gate.should_skip_entry_for_nfp) is an NFP
          release. Dates: published calendar for 2026
          (compass/orchestrator/calendars/nfp_2026.csv), deterministic BLS
          schedule reconstruction for 2020-2025 (first Friday of month;
          July-4-holiday Fridays shift to the Thursday before; a Jan-1 Friday
          shifts to the second Friday — validated 12/12 against the published
          2026 file).

Fidelity notes (documented in each report):
  - min_credit_pct=0: the live champion entry path has NO minimum-credit floor
    (only credit>0) — strategies/credit_spread.py's 10%-of-width floor is in
    the BS-fallback branch, unreachable with a data provider. The engine
    default (15) would be stricter than live.
  - vix_max_entry: absent from all three yamls -> disabled (engine 0).
  - momentum_filter_pct: in the yamls but never applied by the deployed
    scanner (same note as EXP-800-BT) -> disabled.
  - iron_condor: engine fallback IC (same DTE/PT/SL as spreads, sized off
    max_risk_per_trade). The live IC class's separate params (target_dte 30,
    min_dte 20, otm 4%/3%, PT 0.3, SL 2.5, max_risk_pct 3.5, rsi/iv-rank
    gates) are NOT modeled — divergence limited to neutral-regime trades.
  - drawdown_cb_pct: the yamls say 40, but the engine's CB LATCHES — once DD
    from HWM exceeds 40% it blocks entries for the rest of the run (a -70%
    2020 hole never recovers to within 40% of HWM). The DEPLOYED CB is
    in-memory (HWM resets on every scheduler restart) and fail-open, and the
    broker record proves it never fired live (EXP-3303B/-3311 kept entering
    daily through -40%+ June-2026 drawdowns). Fidelity to deployed code, not
    config aspiration (EXP-800-BT precedent): engine CB disabled (1000).
  - stop_loss_pct_of_width: dead key (no reader anywhere) — ignored.

Usage:  .venv/bin/python experiments/honest-fills-fleet/run_twin.py 3311 marketable
        exp in {3303b, 3309, 3311}; fill_model in {naive, marketable}
Offline only (options_cache.db real marks): never touches brokers/live configs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WINDOW = ("2020-01-02", "2026-04-02")  # EXP-800-BT parity window

YAMLS = {
    "3303b": "configs/paper_exp3303b.yaml",
    "3309": "configs/paper_exp3309.yaml",
    "3311": "configs/paper_exp3311.yaml",
}


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── NFP calendar (EXP-3311) ──────────────────────────────────────────────────

def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _nfp_schedule_rule(release_year: int, release_month: int) -> date:
    """Deterministic BLS release-schedule reconstruction (calendar, not market
    data): first Friday of the release month, with the two schedule exceptions
    validated against the published 2026 calendar:
      - first Friday is Jan 1 (holiday)  -> second Friday (e.g. 2021-01-08)
      - first Friday is Jul 3/Jul 4 (Independence-Day holiday/observance)
        -> Thursday before (e.g. 2020-07-02, 2025-07-03, 2026-07-02)
    """
    d = _first_friday(release_year, release_month)
    if d.month == 1 and d.day == 1:
        return d + timedelta(days=7)
    if d.month == 7 and d.day in (3, 4):
        return d - timedelta(days=1)
    return d


def build_nfp_dates(start_year: int, end_year: int) -> set[date]:
    dates: set[date] = set()
    published_years = set()
    try:
        from compass.orchestrator.calendars import nfp_dates as published_nfp
        for y in range(start_year, end_year + 1):
            try:
                ds = published_nfp(y)
                dates.update(ds)
                published_years.add(y)
            except Exception:
                pass
    except Exception:
        pass
    for y in range(start_year, end_year + 1):
        if y in published_years:
            continue
        for m in range(1, 13):
            dates.add(_nfp_schedule_rule(y, m))
    return dates


# ── Gate overlay ─────────────────────────────────────────────────────────────

class GateOverlay:
    """Ports the live main.py scan_opportunities gates onto the engine's
    per-slot entry finders. Entries only — exits/management untouched, matching
    the live scheduler (gates live inside scan_opportunities; PositionMonitor
    is not gated)."""

    WINDOW_START = (15, 30)
    WINDOW_END_MINS = 16 * 60  # exclusive

    def __init__(self, bt, exp: str, yaml_cfg: dict):
        self.bt = bt
        self.exp = exp
        self.counters = {
            "nfp_blocked_days": set(),
            "window_blocked_slot_attempts": 0,
            "window_allowed_slot_attempts": 0,
            "regime_gate_evaluations": 0,
            "regime_gate_fires": 0,
        }
        self.nfp_dates: set[date] = set()
        self.gate_cfg = {}

        if exp == "3311":
            y0 = int(WINDOW[0][:4])
            y1 = int(WINDOW[1][:4])
            self.nfp_dates = build_nfp_dates(y0, y1)
        elif exp == "3303b":
            self.gate_cfg = (yaml_cfg.get("risk", {}) or {}).get("regime_gate", {}) or {}

        for name in ("_find_backtest_opportunity",
                     "_find_bear_call_opportunity",
                     "_find_iron_condor_opportunity"):
            setattr(bt, name, self._wrap(getattr(bt, name)))

    def _wrap(self, orig):
        def fn(*a, **kw):
            # bound-method call convention: a = (ticker, date, price, ...)
            ticker = a[0]
            when = a[1]
            scan_hour = kw.get("scan_hour")
            scan_minute = kw.get("scan_minute")

            if self.exp == "3311":
                d = when.date() if hasattr(when, "date") else when
                if d + timedelta(days=1) in self.nfp_dates:
                    self.counters["nfp_blocked_days"].add(d.isoformat())
                    return None

            elif self.exp == "3309":
                if scan_hour is None or scan_minute is None:
                    self.counters["window_blocked_slot_attempts"] += 1
                    return None
                mins = scan_hour * 60 + scan_minute
                if not (self.WINDOW_START[0] * 60 + self.WINDOW_START[1] <= mins < self.WINDOW_END_MINS):
                    self.counters["window_blocked_slot_attempts"] += 1
                    return None
                self.counters["window_allowed_slot_attempts"] += 1

            elif self.exp == "3303b":
                import pandas as pd
                from shared.regime_gate import should_gate_for_regime
                d = when.date() if hasattr(when, "date") else when
                regime = self.bt._regime_by_date.get(pd.Timestamp(d))
                self.counters["regime_gate_evaluations"] += 1
                skip, _reason = should_gate_for_regime(
                    regime=regime, ticker=ticker,
                    config={"risk": {"regime_gate": self.gate_cfg}},
                )
                if skip:
                    self.counters["regime_gate_fires"] += 1
                    return None

            return orig(*a, **kw)
        return fn

    def summary(self) -> dict:
        out = dict(self.counters)
        out["nfp_blocked_days"] = sorted(out["nfp_blocked_days"])
        out["nfp_blocked_day_count"] = len(out["nfp_blocked_days"])
        out["nfp_calendar_size"] = len(self.nfp_dates)
        return out


# ── metrics helpers (copied from EXP-800-BT run.py) ──────────────────────────

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
    exp = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    assert exp in YAMLS, f"unknown experiment {exp!r} — use one of {sorted(YAMLS)}"
    fill_model = sys.argv[2] if len(sys.argv) > 2 else "naive"
    assert fill_model in ("naive", "marketable"), f"unknown fill_model {fill_model!r}"
    # optional 3rd arg: window end override for smoke tests
    end_override = sys.argv[3] if len(sys.argv) > 3 else None

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for SPY daily bars only

    import yaml as _yaml
    yaml_cfg = _yaml.safe_load((ROOT / YAMLS[exp]).read_text())
    strat = yaml_cfg["strategy"]
    risk = yaml_cfg["risk"]

    start = datetime.fromisoformat(WINDOW[0])
    end = datetime.fromisoformat(end_override or WINDOW[1])

    engine_config = {
        "backtest": {
            "starting_capital": 100000,
            "commission_per_contract": 0.65,
            "slippage": 0.05,
            "exit_slippage": 0.10,
            "sizing_mode": "flat",
            "compound": bool(risk.get("compound", False)),
            "fill_model": fill_model,
        },
        "strategy": {
            "direction": strat["direction"],
            "target_dte": strat["target_dte"],
            "min_dte": strat["min_dte"],
            "max_dte": strat["max_dte"],
            "use_delta_selection": False,
            "spread_width": strat["spread_width"],
            "regime_mode": strat["regime_mode"],
            "regime_config": strat["regime_config"],  # verbatim; detector defaults fill the rest
            "iron_condor": {"enabled": bool(strat.get("iron_condor", {}).get("enabled", False)),
                            "neutral_regime_only": True},
            "min_credit_pct": 0,     # live entry path has no credit floor (credit>0 only)
            "vix_max_entry": 0,      # absent from yaml -> disabled, matching live
            "momentum_filter_pct": None,  # never applied by the deployed scanner
            "trend_ma_period": int(strat["regime_config"].get("ma_slow_period", 80)),
            "max_positions_per_expiration": int(
                (risk.get("portfolio_risk", {}) or {}).get("max_same_expiration", 4)),
        },
        "risk": {
            "max_risk_per_trade": float(risk["max_risk_per_trade"]),
            "max_contracts": int(risk["max_contracts"]),
            "max_positions": int(risk["max_positions"]),
            "profit_target": float(risk["profit_target"]),
            "stop_loss_multiplier": float(risk["stop_loss_multiplier"]),
            # yaml says 40, but the engine CB latches permanently after 2020's
            # -40% DD while the deployed CB (in-memory HWM, fail-open, resets
            # every scheduler restart) never fired live through -40%+ DDs on
            # the broker record. Disabled — fidelity to deployed behavior.
            "drawdown_cb_pct": 1000,
        },
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(strat["otm_pct"]))
    overlay = GateOverlay(bt, exp, yaml_cfg)

    results = bt.run_backtest(ticker="SPY", start_date=start, end_date=end)
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
    trades_by_type = {}
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1
        trades_by_type[t.get("type", "?")] = trades_by_type.get(t.get("type", "?"), 0) + 1

    summary = {
        "experiment": f"EXP-{exp.upper()}-BT",
        "twin_of": f"EXP-{exp.upper()}",
        "fill_model": fill_model,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "fill_model_naive_fallbacks": results.get("fill_model_naive_fallbacks", 0),
        "window": [start.date().isoformat(), end.date().isoformat()],
        "source_yaml": YAMLS[exp],
        "metrics": {
            "cagr_pct": round(cagr, 2),
            "return_pct": results.get("return_pct"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "win_rate": results.get("win_rate"),
            "total_trades": results.get("total_trades"),
            "total_pnl": results.get("total_pnl"),
            "ending_capital": results.get("ending_capital"),
            "ruin_triggered": bool(getattr(bt, "_ruin_triggered", False)),
        },
        "gate": overlay.summary(),
        "per_year_returns_pct": _per_year_returns(bt.equity_curve),
        "exit_reasons": exit_reasons,
        "trades_by_type": trades_by_type,
        "equity_curve": equity,
        "trades": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()}
            for t in results.get("trades", [])
        ],
    }
    suffix = "" if fill_model == "naive" else f"_{fill_model}"
    out = OUT / f"EXP-{exp.upper()}_SPY{suffix}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    m = summary["metrics"]
    print(f"[EXP-{exp}/{fill_model}] trades={m['total_trades']} total={m['return_pct']}% "
          f"CAGR={m['cagr_pct']}% sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown_pct']}% "
          f"winrate={m['win_rate']}% unfilled={summary['unfilled_entries']} "
          f"naive_fallbacks={summary['fill_model_naive_fallbacks']}")
    print(f"gate: {summary['gate']}")
    print(f"per-year: {summary['per_year_returns_pct']}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
