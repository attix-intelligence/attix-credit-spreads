#!/usr/bin/env python3
"""EXP-800-BT — standalone backtest twin of EXP-800 Safe Kelly 4/7/9.

Clears the sentinel GRANDFATHERED debt (EXP-800.backtest_config was null).

Real engine (backtest/backtester.py) on offline Polygon marks
(data/options_cache.db), SPY 2020-01-02..2026-04-02, real VIX/VIX3M via the
post-8f1bc8c indices loader (data/historical_indices.sqlite fallback — no
monkeypatch needed).

Strategy = EXP-400 champion signals (DTE 15 / window 15-25, OTM 2%, width $12,
PT 55% of credit, SL 1.25x) with combo regime direction selection
(bull->bull_put, neutral->iron_condor, bear->bear_call) and the Safe Kelly
sizing layer ported verbatim from scripts/exp800_safe_kelly_scanner.py
(KellyStateDB.update_equity + _kelly_fraction):

  Kelly fractions (% of current MTM equity): bull 9 / neutral 7 / bear 4
  Circuit breakers off rolling HWM (never reset):
    Tier 1  DD <= -8%   -> 0.5x fraction
    Tier 2  DD <= -10%  -> floor to 2%
    Tier 3  DD <= -12%  -> halt entries 30 trading days
                           (+ flatten opens in the 'flatten' variant)
    Recovery: tier releases to 0 when DD > -7% (from tier>=2) / > -8% (tier 1)
  Caps: 30 contracts, 17% risk/trade.

Variants (positional arg):
  flatten   — tier-3 flattens open positions at real marks, as DOCUMENTED in
              paper_exp800.yaml. Uses EXP-3540 anti-thrash semantics: after the
              30-day halt expires while DD stays pinned below -12% (realized
              loss), sizing resumes at the 2% floor; a re-flatten fires only on
              a NEW DD low >= 1pp below the last flatten.
  haltonly  — tier-3 only halts entries, as ACTUALLY DEPLOYED (the scanner has
              no flatten code); positions stay open and can bleed or recover
              MTM. Models the CURRENT deployed state machine (post the
              2026-07-03 deadlock fix, tests/test_exp800_tier3_deadlock.py):
              the halt is finite (30 scan slots, one consumed per blocked
              day); once exhausted, entries resume at the 2% floor even while
              DD stays pinned <= -12%; recovery above -7% restores full Kelly.
              (The pre-fix unconditional tier>=3 block deadlocked forever —
              that historical run is preserved in
              results/SPY_haltonly_prefix_deadlock.json.)
  notiers   — Safe Kelly 9/7/4 regime sizing with circuit breakers DISABLED.
              Unprotected baseline to quantify what the breakers add.

Fidelity deviations from the deployed scanner are documented in
configs/backtest_exp800.json fidelity_notes.

Usage:  .venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py flatten
        .venv/bin/python experiments/EXP-800-BT-safe-kelly/run.py haltonly
Offline only: never touches Tradier/Alpaca/paper workers.
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

CONFIG_PATH = ROOT / "configs" / "backtest_exp800.json"


def _load_env(env_path: Path) -> None:
    """Minimal .env loader — only needs POLYGON_API_KEY for SPY daily bars."""
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class SafeKellyOverlay:
    """EXP-800 Kelly sizing + 3-tier circuit breakers wrapped around the engine.

    State machine is a verbatim port of KellyStateDB.update_equity plus
    _kelly_fraction and the scanner's extra tier>=3 entry block
    (exp800_safe_kelly_scanner.py lines ~457-541 and ~693-704), evaluated once
    per trading day AFTER position management (matching the live 10:00 ET scan
    which reads same-morning Alpaca equity).
    """

    def __init__(self, bt, cfg: dict, flatten_enabled: bool, tiers_enabled: bool = True):
        kelly = cfg["kelly"]
        cb = kelly["circuit_breakers"]
        self.bt = bt
        self.flatten_enabled = flatten_enabled
        self.tiers_enabled = tiers_enabled
        self.fractions = kelly["regime_fractions"]
        self.t1 = float(cb["tier1_dd"])
        self.t2 = float(cb["tier2_dd"])
        self.t3 = float(cb["tier3_dd"])
        self.min_fraction = float(cb["min_fraction"])
        self.halt_trades = int(cb["tier3_halt_trades"])
        self.recovery = float(cb["recovery_dd"])
        self.max_risk_cap = float(cfg["max_risk_per_trade"])
        self.spread_width = float(cfg["spread_width"])
        self.max_contracts = int(cfg["max_contracts"])

        self.hwm = bt.starting_capital
        self.tier = 0
        self.halt_remaining = 0
        self.last_flatten_dd = None  # anti-thrash: re-flatten only on a new low
        self.block_entries = False
        self.today_eff_pct = 0.0
        self.today_equity = bt.starting_capital

        self.events = []                    # tier transitions + flattens
        self.tier_fires = {1: 0, 2: 0, 3: 0}  # upward transitions into each tier
        self.flatten_count = 0
        self.blocked_days = 0
        self.min_dd = 0.0
        self.dd_series = []                 # (date, dd_pct, tier, eff_pct)

        self._orig_manage = bt._manage_positions
        bt._manage_positions = self._wrapped_manage
        for name in ("_find_backtest_opportunity", "_find_bear_call_opportunity"):
            setattr(bt, name, self._gate(getattr(bt, name)))
        bt._find_iron_condor_opportunity = self._gate_ic(bt._find_iron_condor_opportunity)

    # ── entry gates ─────────────────────────────────────────────────────────
    def _gate(self, orig):
        def fn(*a, **kw):
            if self.block_entries:
                return None
            return orig(*a, **kw)
        return fn

    def _gate_ic(self, orig):
        """IC gate + live-exact resize: the deployed scanner sizes iron condors
        on ONE wing with put-side credit only (contracts = equity*kelly% /
        ((width - put_credit)*100)), unlike the engine's two-wing convention."""
        def fn(*a, **kw):
            if self.block_entries:
                return None
            pos = orig(*a, **kw)
            if pos is None:
                return None
            put_credit = float(pos.get("put_credit", pos["credit"] / 2.0))
            max_loss_live = (self.spread_width - put_credit) * 100.0
            if max_loss_live > 0:
                risk_dollars = self.today_equity * self.today_eff_pct / 100.0
                live_contracts = max(1, min(int(risk_dollars // max_loss_live),
                                            self.max_contracts))
                old = pos["contracts"]
                if live_contracts != old:
                    new_comm = self.bt.commission * 4 * live_contracts
                    self.bt.capital += pos["commission"] - new_comm  # re-book entry commission
                    pos["contracts"] = live_contracts
                    pos["commission"] = new_comm
            return pos
        return fn

    # ── tier-3 flatten (documented variant) ─────────────────────────────────
    def _flatten(self, positions, current_date):
        date_str = current_date.strftime("%Y-%m-%d")
        for pos in list(positions):
            spread_value = None
            slip_legs = 1
            if pos.get("type") == "iron_condor":
                pp = self.bt.historical_data.get_spread_prices(
                    pos["ticker"], pos["expiration"],
                    pos["short_strike"], pos["long_strike"], "P", date_str)
                cp = self.bt.historical_data.get_spread_prices(
                    pos["ticker"], pos["expiration"],
                    pos["call_short_strike"], pos["call_long_strike"], "C", date_str)
                if pp is not None and cp is not None:
                    spread_value = pp["spread_value"] + cp["spread_value"]
                    slip_legs = 2
            else:
                prices = self.bt.historical_data.get_spread_prices(
                    pos["ticker"], pos["expiration"],
                    pos["short_strike"], pos["long_strike"],
                    pos.get("option_type", "P"), date_str)
                if prices is not None:
                    spread_value = prices["spread_value"]
            if spread_value is not None:
                exit_cost = spread_value + slip_legs * self.bt._vix_scaled_exit_slippage()
                pnl = (pos["credit"] - exit_cost) * pos["contracts"] * 100 - pos["commission"]
                reason = "dd_flatten"
            else:
                # no marks today — close at the carried mark minus exit friction
                slip = self.bt._vix_scaled_exit_slippage() * pos["contracts"] * 100
                pnl = pos.get("current_value", 0) - slip - pos["commission"]
                reason = "dd_flatten_marked"
            self.bt._record_close(pos, current_date, pnl, reason)
        return []

    # ── daily hook ───────────────────────────────────────────────────────────
    def _wrapped_manage(self, positions, current_date, current_price, ticker=""):
        import pandas as pd

        positions = self._orig_manage(positions, current_date, current_price, ticker)

        equity = self.bt.capital + sum(p.get("current_value", 0) for p in positions)
        if equity > self.hwm:
            self.hwm = equity
        dd = (equity - self.hwm) / self.hwm * 100.0
        self.min_dd = min(self.min_dd, dd)

        # ── KellyStateDB.update_equity transition rules (verbatim port) ──
        prev_tier, prev_halt = self.tier, self.halt_remaining
        if not self.tiers_enabled:
            new_tier, new_halt = 0, 0
        elif dd <= self.t3:
            new_tier = 3
            new_halt = self.halt_trades if prev_tier < 3 else prev_halt
        elif dd <= self.t2:
            new_tier = 2
            new_halt = prev_halt if prev_tier == 3 else 0
        elif dd <= self.t1:
            new_tier = 1
            new_halt = 0
        else:
            if prev_tier >= 2 and dd > self.recovery:
                new_tier, new_halt = 0, 0
            elif prev_tier == 1:
                new_tier, new_halt = 0, 0
            else:
                new_tier, new_halt = prev_tier, prev_halt

        if new_tier > prev_tier:
            for t in range(prev_tier + 1, new_tier + 1):
                self.tier_fires[t] += 1
        if new_tier != prev_tier:
            self.events.append({"date": str(current_date.date()),
                                "dd_pct": round(dd, 2),
                                "equity": round(equity, 2),
                                "transition": f"tier{prev_tier}->tier{new_tier}"})

        # ── tier-3 flatten (documented variant only) ──
        if self.flatten_enabled and new_tier == 3:
            # anti-thrash (EXP-3540): flatten on the first tier-3 trigger, then
            # only again on a NEW DD low >= 1pp below the last flatten
            new_low = (self.last_flatten_dd is None
                       or dd <= self.last_flatten_dd - 1.0)
            if positions and new_low:
                self.events.append({"date": str(current_date.date()),
                                    "dd_pct": round(dd, 2),
                                    "transition": f"tier3_flatten_{len(positions)}pos"})
                positions = self._flatten(positions, current_date)
                self.flatten_count += 1
                self.last_flatten_dd = dd
                new_halt = self.halt_trades
                equity = self.bt.capital  # nothing open post-flatten

        # ── _kelly_fraction + scanner tier>=3 entry block (verbatim port) ──
        regime = self.bt._regime_by_date.get(pd.Timestamp(current_date.date()))
        base_frac = float(self.fractions.get(regime, self.fractions.get("neutral", 7.0)))

        if new_tier >= 3:
            if new_halt <= 0:
                # Finite, self-clearing halt — matches the deployed scanner
                # post-deadlock-fix (_kelly_fraction/_tier3_entry_blocked,
                # tests/test_exp800_tier3_deadlock.py): once the 30-slot halt
                # exhausts, sizing resumes at the tier-2 floor even while DD
                # stays pinned <= -12%. In the flatten variant a NEW DD low
                # >= 1pp below the last flatten re-flattens above (EXP-3540).
                eff, blocked = self.min_fraction, False
            else:
                eff, blocked = 0.0, True
                new_halt -= 1  # one scan-day slot consumed (live: _decrement_halt)
        elif new_tier == 2:
            eff, blocked = self.min_fraction, False
        elif new_tier == 1:
            eff, blocked = base_frac * 0.5, False
        else:
            eff, blocked = base_frac, False

        eff = min(eff, self.max_risk_cap)  # hard cap: 17% of equity per trade
        self.tier, self.halt_remaining = new_tier, new_halt
        self.block_entries = blocked
        if blocked:
            self.blocked_days += 1
        self.today_eff_pct = eff
        self.today_equity = equity

        # Engine flat sizing risks eff% of CASH capital; live risks eff% of MTM
        # equity (Alpaca portfolio_value). Scale so account_base*pct == equity*eff.
        if self.bt.capital > 0:
            adj = eff * equity / self.bt.capital
        else:
            adj = eff
        self.bt.risk_params["max_risk_per_trade"] = max(adj, 0.0)

        self.dd_series.append((str(current_date.date()), round(dd, 3), new_tier, eff))
        return positions


def _per_year_returns(equity_curve):
    """Calendar-year returns from the (date, equity) curve."""
    import pandas as pd
    s = pd.Series({pd.Timestamp(d): v for d, v in equity_curve}).sort_index()
    out = {}
    for year, grp in s.groupby(s.index.year):
        prior = s[s.index < grp.index[0]]
        base = prior.iloc[-1] if len(prior) else grp.iloc[0]
        out[int(year)] = round((grp.iloc[-1] / base - 1) * 100, 2)
    return out


def _monthly_returns(equity_curve, months):
    import pandas as pd
    s = pd.Series({pd.Timestamp(d): v for d, v in equity_curve}).sort_index()
    out = {}
    for m in months:
        grp = s[s.index.strftime("%Y-%m") == m]
        if grp.empty:
            continue
        prior = s[s.index < grp.index[0]]
        base = prior.iloc[-1] if len(prior) else grp.iloc[0]
        out[m] = round((grp.iloc[-1] / base - 1) * 100, 2)
    return out


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "flatten"
    assert variant in ("flatten", "haltonly", "notiers"), f"unknown variant {variant}"

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("backtest.backtester").setLevel(logging.WARNING)

    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for SPY daily bars only

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
            "iron_condor": dict(cfg["iron_condor"]),  # no risk_per_trade key: ICs size off max_risk_per_trade
            "min_credit_pct": cfg["min_credit_pct"],
            "vix_max_entry": cfg["vix_max_entry"],
            "momentum_filter_pct": None,   # in paper yaml but never applied by the deployed scanner
            "trend_ma_period": 80,         # unused in combo mode; drives MA warmup fetch window
            "max_positions_per_expiration": cfg["backtest"]["max_positions_per_expiration"],
        },
        "risk": {
            "max_risk_per_trade": cfg["kelly"]["regime_fractions"]["bull"],  # overlay overwrites daily
            "max_contracts": cfg["max_contracts"],
            "max_positions": cfg["max_positions"],
            "profit_target": cfg["profit_target"],
            "stop_loss_multiplier": cfg["stop_loss_multiplier"],
            "drawdown_cb_pct": 1000,  # disable engine's built-in -20% breaker; Kelly tiers own DD
        },
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(cfg["otm_pct"]))
    overlay = SafeKellyOverlay(bt, cfg, flatten_enabled=(variant == "flatten"),
                           tiers_enabled=(variant != "notiers"))

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
    regime_trades = {}
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1
        regime_trades[t.get("type", "?")] = regime_trades.get(t.get("type", "?"), 0) + 1

    summary = {
        "experiment": "EXP-800-BT",
        "variant": variant,
        "window": [start.date().isoformat(), end.date().isoformat()],
        "config": os.path.relpath(str(CONFIG_PATH), str(ROOT)),
        "metrics": {
            "cagr_pct": round(cagr, 2),
            "return_pct": results.get("return_pct"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "kelly_hwm_min_dd_pct": round(overlay.min_dd, 2),
            "win_rate": results.get("win_rate"),
            "total_trades": results.get("total_trades"),
            "total_pnl": results.get("total_pnl"),
            "ending_capital": results.get("ending_capital"),
            "ruin_triggered": bool(getattr(bt, "_ruin_triggered", False)),
        },
        "per_year_returns_pct": _per_year_returns(bt.equity_curve),
        "q1_2026_monthly_pct": _monthly_returns(bt.equity_curve, ["2026-01", "2026-02", "2026-03"]),
        "breaker": {
            "tier_fires": overlay.tier_fires,
            "flatten_count": overlay.flatten_count,
            "blocked_days": overlay.blocked_days,
            "final_tier": overlay.tier,
            "events": overlay.events,
        },
        "exit_reasons": exit_reasons,
        "trades_by_type": regime_trades,
        "equity_curve": equity,
        "dd_series": overlay.dd_series,
        "trades": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()}
            for t in results.get("trades", [])
        ],
    }
    out = OUT / f"SPY_{variant}.json"
    out.write_text(json.dumps(summary, indent=2, default=str))

    m = summary["metrics"]
    print(f"[EXP-800-BT/{variant}] trades={m['total_trades']} CAGR={m['cagr_pct']}% "
          f"total={m['return_pct']}% sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown_pct']}% "
          f"winrate={m['win_rate']}% tiers={overlay.tier_fires} flattens={overlay.flatten_count} "
          f"blocked_days={overlay.blocked_days} ruin={m['ruin_triggered']}")
    print(f"per-year: {summary['per_year_returns_pct']}")
    print(f"exits: {exit_reasons}  types: {regime_trades}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
