"""Walk-forward equity/ETF backtester for the MSR theme rotation.

Drives ``strategies.msr_theme_rotation`` over a date range using:

* daily themes from ``data/llm_analysis/{date}.json`` (via
  ``strategies.msr_theme_loader``)
* theme → vehicle resolution via ``strategies.msr_etf_map``
* real daily OHLCV bars from Polygon via ``backtest.market_history``

All vehicle signals (``momentum_z``, ``dark_flow_z``, ``realised_vol_21d``,
``last_price``) are supplied by an injected :class:`SignalProvider` so this
module never fabricates inputs.  Rule Zero: when a signal is unavailable,
the entry is dropped — never defaulted.

Outputs
-------
* ``trades.csv`` — one row per closed trade
* ``equity.csv`` — daily NAV curve
* ``summary.json`` — Sharpe / CAGR / max_dd / win_rate / num_trades

The runner does **not** attempt to compute momentum_z / dark_flow_z from
raw sources here — that orchestration lives in MSR-201 (signal regen).
Phase 1 just provides the harness.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Protocol

import pandas as pd

from backtest.market_history import load_market_history
from strategies.msr_etf_map import ThemeMap, load_map, resolve_vehicle
from strategies.msr_theme_loader import (
    CachedThemeDay,
    DEFAULT_CACHE_DIR,
    load_themes_safe,
)
from strategies.msr_theme_rotation import (
    BookState,
    EXIT_TIME_STOP,
    MSRParams,
    MSRPosition,
    ThemeRecord,
    VehicleSignals,
    book_can_open,
    book_must_flatten,
    evaluate_exit,
    select_entries,
    size_position,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider protocols (injected — tests supply stubs with real fixture data)
# ---------------------------------------------------------------------------


class SignalProvider(Protocol):
    """Returns the per-vehicle signal snapshot needed for the entry gate."""

    def vehicle_signals(self, ticker: str, as_of: date) -> Optional[VehicleSignals]:
        """Return today's signals for ``ticker``, or None if unavailable."""
        ...


class PriceProvider(Protocol):
    """Returns daily OHLCV for a ticker over an inclusive date window."""

    def get_bars(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        ...


class PolygonPriceProvider:
    """Default :class:`PriceProvider` — wraps ``backtest.market_history``."""

    def get_bars(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        return load_market_history(ticker, start, end)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ClosedTrade:
    theme_name: str
    ticker: str
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    shares: int
    notional: float
    pnl_dollars: float
    pnl_pct: float
    days_held: int
    exit_reason: str
    entry_confidence: float


@dataclass
class BacktestResult:
    start: date
    end: date
    initial_capital: float
    trades: List[ClosedTrade]
    equity_curve: pd.Series                 # index: date; value: NAV
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trading_dates(start: date, end: date, bars: pd.DataFrame) -> List[date]:
    """Use the index of a benchmark price-bars frame to enumerate trading
    days. The caller supplies a frame for any liquid US-equity ticker over
    the window (we use SPY by convention).
    """
    days = [d.date() if hasattr(d, "date") else d for d in bars.index]
    return [d for d in days if start <= d <= end]


def _vix_close(vix_bars: pd.DataFrame, as_of: date) -> float:
    """Return the VIX close on or before ``as_of``. Falls back to ``nan``
    if the bars frame doesn't contain ``as_of`` or any earlier date."""
    if vix_bars is None or vix_bars.empty:
        return float("nan")
    # Allow either date- or Timestamp-indexed frames
    idx = vix_bars.index
    mask = pd.Index(idx).map(lambda d: (d.date() if hasattr(d, "date") else d) <= as_of)
    if not mask.any():
        return float("nan")
    return float(vix_bars.loc[mask].iloc[-1]["Close"])


def _mtd_pnl_pct(equity_curve: pd.Series, as_of: date, slot: float) -> float:
    """Month-to-date PnL as fraction of the MSR slot."""
    if equity_curve.empty or slot <= 0:
        return 0.0
    month_start = date(as_of.year, as_of.month, 1)
    earlier = equity_curve[equity_curve.index < pd.Timestamp(month_start)]
    if earlier.empty:
        anchor = float(equity_curve.iloc[0])
    else:
        anchor = float(earlier.iloc[-1])
    today_nav = float(equity_curve.loc[: pd.Timestamp(as_of)].iloc[-1])
    return (today_nav - anchor) / slot


def _nav_drawdown(equity_curve: pd.Series, as_of: date) -> float:
    """Distance from all-time-high NAV as a positive fraction."""
    if equity_curve.empty:
        return 0.0
    series = equity_curve.loc[: pd.Timestamp(as_of)]
    if series.empty:
        return 0.0
    peak = float(series.cummax().iloc[-1])
    cur = float(series.iloc[-1])
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - cur) / peak)


def _close_on(bars: pd.DataFrame, as_of: date) -> Optional[float]:
    """Return the close for ``as_of`` if present, else None.

    We do NOT look forward — if no bar exists exactly on ``as_of`` the
    caller treats it as a market-closed day and leaves positions
    untouched.
    """
    if bars is None or bars.empty:
        return None
    target = pd.Timestamp(as_of)
    if target in bars.index:
        return float(bars.loc[target, "Close"])
    # Some sources return python.date objects in the index
    for idx in bars.index:
        idx_d = idx.date() if hasattr(idx, "date") else idx
        if idx_d == as_of:
            return float(bars.loc[idx, "Close"])
    return None


def _theme_today(themes: Optional[CachedThemeDay], name: str) -> Optional[ThemeRecord]:
    if themes is None:
        return None
    for t in themes.themes:
        if t.name == name:
            return t
    return None


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


def run_backtest(
    start: date,
    end: date,
    initial_capital: float,
    signals: SignalProvider,
    *,
    params: Optional[MSRParams] = None,
    prices: Optional[PriceProvider] = None,
    theme_cache_dir: Path = DEFAULT_CACHE_DIR,
    etf_map: Optional[ThemeMap] = None,
    msr_slot_pct: float = 0.25,
    benchmark_ticker: str = "SPY",
    vix_ticker: str = "^VIX",
    v8a_returns: Optional[pd.Series] = None,
) -> BacktestResult:
    """Run the MSR walk-forward.

    Args:
        start, end: inclusive backtest window.
        initial_capital: total NAV. The MSR book runs on
            ``msr_slot_pct * initial_capital`` (default 25% per spec).
        signals: :class:`SignalProvider` returning per-vehicle signal
            snapshots. Must use real, non-look-ahead data.
        params: strategy thresholds (defaults to :class:`MSRParams`).
        prices: :class:`PriceProvider` (defaults to Polygon via
            :class:`PolygonPriceProvider`).
        theme_cache_dir: path to ``data/llm_analysis/``.
        etf_map: pre-loaded ThemeMap; defaults to the canonical YAML.
        msr_slot_pct: fraction of capital allocated to the MSR book.
        benchmark_ticker: used to enumerate trading days.
        vix_ticker: used for the book-level VIX gate.
        v8a_returns: optional v8a daily-return series for the correlation
            gate. When None, the correlation gate is skipped.

    Returns:
        :class:`BacktestResult` with trades, equity curve, and metrics.
    """
    params = params or MSRParams()
    prices = prices or PolygonPriceProvider()
    etf_map = etf_map or load_map()

    msr_slot = msr_slot_pct * initial_capital
    if msr_slot <= 0:
        raise ValueError("msr_slot_pct * initial_capital must be > 0")

    # Pre-load benchmark + VIX bars for the full window
    bench = prices.get_bars(benchmark_ticker, start, end)
    if bench.empty:
        raise RuntimeError(f"no benchmark bars for {benchmark_ticker} {start}..{end}")
    try:
        vix_bars = prices.get_bars(vix_ticker, start, end)
    except Exception as e:  # noqa: BLE001 — VIX is non-critical; fail open with nan
        logger.warning("VIX fetch failed (%s); VIX gate will be skipped", e)
        vix_bars = pd.DataFrame()

    trading_days = _trading_dates(start, end, bench)
    if not trading_days:
        raise RuntimeError(f"no trading days in [{start}, {end}]")

    # Price-bar cache to avoid refetching the same ticker
    bar_cache: dict[str, pd.DataFrame] = {}

    def _bars_for(ticker: str) -> pd.DataFrame:
        if ticker not in bar_cache:
            bar_cache[ticker] = prices.get_bars(ticker, start, end)
        return bar_cache[ticker]

    open_positions: List[MSRPosition] = []
    closed_trades: List[ClosedTrade] = []
    nav_history: dict[date, float] = {}
    nav = float(initial_capital)
    # Realised PnL accumulator (cash side); unrealised is added each MTM step
    realised_pnl = 0.0

    for day in trading_days:
        # --- mark-to-market open positions, then evaluate exits -----------
        themes = load_themes_safe(day, theme_cache_dir)
        unrealised_pnl = 0.0
        survivors: List[MSRPosition] = []

        for pos in open_positions:
            bars = _bars_for(pos.ticker)
            close = _close_on(bars, day)
            if close is None:
                # No bar today — leave the position untouched
                survivors.append(pos)
                continue
            pos.last_price = close
            pos.days_held = (day - pos.entry_date).days

            today_theme = _theme_today(themes, pos.theme_name)
            decision = evaluate_exit(pos, today_theme, params)
            if decision.close:
                exit_pnl = pos.pnl_dollars
                realised_pnl += exit_pnl
                closed_trades.append(ClosedTrade(
                    theme_name=pos.theme_name,
                    ticker=pos.ticker,
                    entry_date=pos.entry_date,
                    entry_price=pos.entry_price,
                    exit_date=day,
                    exit_price=close,
                    shares=pos.shares,
                    notional=pos.notional,
                    pnl_dollars=exit_pnl,
                    pnl_pct=pos.pnl_pct,
                    days_held=pos.days_held,
                    exit_reason=decision.reason or "unknown",
                    entry_confidence=pos.entry_confidence,
                ))
            else:
                survivors.append(pos)
                unrealised_pnl += pos.pnl_dollars

        open_positions = survivors
        nav = float(initial_capital) + realised_pnl + unrealised_pnl
        nav_history[day] = nav

        # --- book-level circuit breakers ---------------------------------
        equity_series = pd.Series(nav_history).sort_index()
        equity_series.index = pd.to_datetime(equity_series.index)
        mtd_pct = _mtd_pnl_pct(equity_series, day, msr_slot)
        nav_dd = _nav_drawdown(equity_series, day)
        vix = _vix_close(vix_bars, day)
        corr_vs_v8a = _correlation_60d(v8a_returns, equity_series)

        book = BookState(
            open_positions=len(open_positions),
            mtd_pnl_pct=mtd_pct,
            nav_drawdown_pct=nav_dd,
            vix=vix,
            corr_60d_vs_v8a=corr_vs_v8a,
        )

        # Flatten gate trumps everything
        flatten_reason = book_must_flatten(book, params)
        if flatten_reason and open_positions:
            for pos in open_positions:
                close = _close_on(_bars_for(pos.ticker), day) or pos.last_price
                pos.last_price = close
                exit_pnl = pos.pnl_dollars
                realised_pnl += exit_pnl
                closed_trades.append(ClosedTrade(
                    theme_name=pos.theme_name, ticker=pos.ticker,
                    entry_date=pos.entry_date, entry_price=pos.entry_price,
                    exit_date=day, exit_price=close,
                    shares=pos.shares, notional=pos.notional,
                    pnl_dollars=exit_pnl, pnl_pct=pos.pnl_pct,
                    days_held=(day - pos.entry_date).days,
                    exit_reason=flatten_reason,
                    entry_confidence=pos.entry_confidence,
                ))
            open_positions = []
            nav = float(initial_capital) + realised_pnl
            nav_history[day] = nav

        # --- new entries -------------------------------------------------
        if themes is None or not themes.themes:
            continue
        if not book_can_open(book, params).can_open:
            continue

        # Build vehicle lookup per accepted theme
        open_theme_names = {p.theme_name for p in open_positions}
        vehicle_lookup: dict[str, Optional[VehicleSignals]] = {}
        for theme in themes.themes:
            if theme.name in open_theme_names:
                continue
            resolved = resolve_vehicle(theme.name, theme.tickers, etf_map)
            if resolved is None:
                vehicle_lookup[theme.name] = None
                continue
            primary_ticker = resolved.primary_ticker
            if not primary_ticker:
                vehicle_lookup[theme.name] = None
                continue
            vehicle_lookup[theme.name] = signals.vehicle_signals(primary_ticker, day)

        accepted = select_entries(
            themes.themes, vehicle_lookup, book, open_theme_names, params,
        )

        for decision in accepted:
            veh = vehicle_lookup.get(decision.theme_name)
            if veh is None:
                continue
            theme = _theme_today(themes, decision.theme_name)
            if theme is None:
                continue
            shares, notional = size_position(msr_slot, veh, params)
            if shares <= 0:
                continue
            open_positions.append(MSRPosition(
                theme_name=decision.theme_name,
                ticker=decision.ticker,
                entry_date=day,
                entry_price=veh.last_price,
                shares=shares,
                notional=notional,
                entry_confidence=theme.confidence,
                entry_momentum_z=veh.momentum_z,
                entry_dark_flow_z=veh.dark_flow_z,
                last_price=veh.last_price,
            ))
            logger.info(
                "%s OPEN %-12s -> %-5s @ $%.2f x %d (notional $%.0f, conf %.2f)",
                day, decision.theme_name[:12], decision.ticker,
                veh.last_price, shares, notional, theme.confidence,
            )

    # Final equity curve
    equity = pd.Series(nav_history).sort_index()
    equity.index = pd.to_datetime(equity.index)

    return BacktestResult(
        start=start,
        end=end,
        initial_capital=initial_capital,
        trades=closed_trades,
        equity_curve=equity,
        metrics=compute_metrics(equity, closed_trades, initial_capital),
    )


# ---------------------------------------------------------------------------
# Correlation gate helper
# ---------------------------------------------------------------------------


def _correlation_60d(
    v8a_returns: Optional[pd.Series],
    nav_history: pd.Series,
) -> float:
    """Pearson correlation of MSR daily returns vs v8a's, over last 60 obs.

    Returns ``nan`` when fewer than 30 overlapping return observations
    exist — the book gate fails open in that case (correlation cannot be
    estimated meaningfully).
    """
    if v8a_returns is None or v8a_returns.empty or nav_history.empty:
        return float("nan")
    if len(nav_history) < 2:
        return float("nan")
    msr_returns = nav_history.pct_change().dropna()
    aligned = pd.concat([msr_returns, v8a_returns], axis=1, join="inner").dropna()
    if len(aligned) < 30:
        return float("nan")
    tail = aligned.tail(60)
    return float(tail.iloc[:, 0].corr(tail.iloc[:, 1]))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_metrics(
    equity: pd.Series,
    trades: List[ClosedTrade],
    initial_capital: float,
) -> dict:
    """Standard backtest metrics. All annualisations use 252 trading days."""
    if equity.empty:
        return {"num_trades": 0}

    returns = equity.pct_change().dropna()
    final = float(equity.iloc[-1])
    total_ret = (final - initial_capital) / initial_capital

    n_years = max(len(equity) / 252.0, 1e-9)
    cagr = (final / initial_capital) ** (1 / n_years) - 1 if final > 0 else -1.0

    if returns.std() > 0:
        sharpe = float((returns.mean() / returns.std()) * math.sqrt(252))
    else:
        sharpe = 0.0

    drawdown = (equity / equity.cummax() - 1.0).min()

    wins = [t for t in trades if t.pnl_dollars > 0]
    losses = [t for t in trades if t.pnl_dollars <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win = (sum(t.pnl_dollars for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t.pnl_dollars for t in losses) / len(losses)) if losses else 0.0

    return {
        "num_trades":     len(trades),
        "win_rate":       round(win_rate, 4),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "total_return":   round(total_ret, 4),
        "cagr":           round(cagr, 4),
        "sharpe":         round(sharpe, 3),
        "max_drawdown":   round(float(drawdown), 4),
        "final_nav":      round(final, 2),
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def save_results(result: BacktestResult, out_dir: Path) -> None:
    """Write trades.csv, equity.csv, summary.json to ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trades_df = pd.DataFrame([t.__dict__ for t in result.trades])
    trades_df.to_csv(out_dir / "trades.csv", index=False)

    eq = result.equity_curve.copy()
    eq.index.name = "date"
    eq.name = "nav"
    eq.to_csv(out_dir / "equity.csv")

    summary = {
        "start":            result.start.isoformat(),
        "end":              result.end.isoformat(),
        "initial_capital":  result.initial_capital,
        **result.metrics,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))


__all__ = [
    "SignalProvider",
    "PriceProvider",
    "PolygonPriceProvider",
    "ClosedTrade",
    "BacktestResult",
    "run_backtest",
    "compute_metrics",
    "save_results",
]
