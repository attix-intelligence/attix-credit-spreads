"""MSR-001 — Multi-Signal Rotation theme strategy.

Long-only theme rotation driven by daily LLM theme categorisations from
``compass.analysis.llm_categorizer`` (cached in ``data/llm_analysis/``).
Reference spec: ``reports/MULTI_SIGNAL_STRATEGY.md``.

This module contains *only* the entry / exit / sizing decision logic. It is
driven by ``backtest/equity_backtester.py`` (MSR-105) at backtest time and
by a live runner in production. No I/O happens here — themes, prices, and
signal values are passed in by the caller. That makes the rules unit-testable
and prevents Rule Zero drift (no fabricated data can leak in when there is no
data fetch).

Decision surface
----------------
* :func:`evaluate_entry`  — per-theme gate (bull, confidence, momentum, dark flow)
* :func:`evaluate_exit`   — per-position gate (time, decay, inversion, stop)
* :func:`size_position`   — vol-targeted notional inside the MSR slot
* :func:`book_can_open`   — book-level circuit breakers (positions, MTD, DD, VIX)

Exit codes are stable strings (used in CSV outputs) — do not rename without
updating downstream report tooling.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, Literal, Optional

# Stable exit-reason strings (do not rename — referenced in trade logs).
EXIT_TIME_STOP = "time_stop_7d"
EXIT_CONFIDENCE_DECAY = "confidence_decay"
EXIT_THEME_INVERSION = "theme_inversion"
EXIT_PRICE_STOP = "price_stop_2pct"

# Spec defaults — overridable via MSRParams. Locked here so tests can assert
# the canonical values match the strategy doc.
DEFAULT_ENTRY_CONFIDENCE = 0.50
DEFAULT_EXIT_CONFIDENCE = 0.40
DEFAULT_MOMENTUM_Z_MIN = 1.0
DEFAULT_DARK_FLOW_Z_MIN = 0.0
DEFAULT_HOLD_DAYS_MAX = 7
DEFAULT_STOP_LOSS_PCT = -0.02
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_SIZE_PCT_MIN = 0.05
DEFAULT_SIZE_PCT_MAX = 0.10
DEFAULT_VOL_TARGET_DAILY = 0.005  # 0.5% daily target → ~8% annual position vol
DEFAULT_VIX_MAX = 35.0
DEFAULT_BOOK_FREEZE_MTD = -0.05
DEFAULT_BOOK_FLATTEN_MTD = -0.10
DEFAULT_CORR_MAX_VS_V8A = 0.40

Direction = Literal["bull", "bear", "neutral"]


@dataclass(frozen=True)
class ThemeRecord:
    """One LLM category record (a single row of the daily themes file).

    Mirrors :class:`compass.analysis.llm_categorizer.Category` but flattened
    to plain types so this module has zero compass imports.
    """
    name: str
    direction: Direction
    confidence: float                # 0..1
    tickers: tuple[str, ...]
    supporting_signals: tuple[str, ...] = ()
    narrative: str = ""


@dataclass(frozen=True)
class VehicleSignals:
    """Per-vehicle (ETF or stock) signal snapshot on the entry date.

    Provided by the equity_backtester after looking the vehicle up in
    ``strategies/msr_etf_map.yaml`` and joining it to the day's signals.
    """
    ticker: str
    momentum_z: float
    dark_flow_z: float
    realised_vol_21d: float          # daily stdev of log-returns, e.g. 0.012
    last_price: float


@dataclass(frozen=True)
class MSRParams:
    """All thresholds for the strategy — overridable per backtest."""
    entry_confidence: float = DEFAULT_ENTRY_CONFIDENCE
    exit_confidence: float = DEFAULT_EXIT_CONFIDENCE
    momentum_z_min: float = DEFAULT_MOMENTUM_Z_MIN
    dark_flow_z_min: float = DEFAULT_DARK_FLOW_Z_MIN
    hold_days_max: int = DEFAULT_HOLD_DAYS_MAX
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    size_pct_min: float = DEFAULT_SIZE_PCT_MIN
    size_pct_max: float = DEFAULT_SIZE_PCT_MAX
    vol_target_daily: float = DEFAULT_VOL_TARGET_DAILY
    vix_max: float = DEFAULT_VIX_MAX
    book_freeze_mtd: float = DEFAULT_BOOK_FREEZE_MTD
    book_flatten_mtd: float = DEFAULT_BOOK_FLATTEN_MTD
    corr_max_vs_v8a: float = DEFAULT_CORR_MAX_VS_V8A


@dataclass
class MSRPosition:
    """Open theme position tracked by the backtester."""
    theme_name: str
    ticker: str
    entry_date: date
    entry_price: float
    shares: int
    notional: float
    entry_confidence: float
    entry_momentum_z: float
    entry_dark_flow_z: float
    days_held: int = 0
    last_price: float = 0.0

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.last_price - self.entry_price) / self.entry_price

    @property
    def pnl_dollars(self) -> float:
        return self.shares * (self.last_price - self.entry_price)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntryDecision:
    """Result of evaluating a (theme, vehicle) pair for entry."""
    accept: bool
    reason: str                      # "ok" or first failing gate
    theme_name: str
    ticker: str


def evaluate_entry(
    theme: ThemeRecord,
    vehicle: Optional[VehicleSignals],
    params: MSRParams = MSRParams(),
) -> EntryDecision:
    """Apply the four-gate entry rule from the spec.

    Order matters for reason reporting — each gate is the *first* one to fail.
    """
    if theme.direction != "bull":
        return EntryDecision(False, f"direction={theme.direction}", theme.name, "")
    if theme.confidence < params.entry_confidence:
        return EntryDecision(False, f"confidence={theme.confidence:.2f}",
                             theme.name, "")
    if vehicle is None:
        return EntryDecision(False, "no_vehicle_mapped", theme.name, "")
    if not math.isfinite(vehicle.momentum_z) or vehicle.momentum_z <= params.momentum_z_min:
        return EntryDecision(False, f"momentum_z={vehicle.momentum_z:.2f}",
                             theme.name, vehicle.ticker)
    if not math.isfinite(vehicle.dark_flow_z) or vehicle.dark_flow_z <= params.dark_flow_z_min:
        return EntryDecision(False, f"dark_flow_z={vehicle.dark_flow_z:.2f}",
                             theme.name, vehicle.ticker)
    return EntryDecision(True, "ok", theme.name, vehicle.ticker)


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitDecision:
    close: bool
    reason: Optional[str]            # one of EXIT_* or None


def evaluate_exit(
    position: MSRPosition,
    todays_theme: Optional[ThemeRecord],
    params: MSRParams = MSRParams(),
) -> ExitDecision:
    """First-firing exit wins.

    Priority order (spec §4):
      1. price_stop_2pct   (intraday-equivalent EOD check)
      2. theme_inversion   (today's theme flipped to bear/neutral)
      3. confidence_decay  (confidence dropped below exit_confidence)
      4. time_stop_7d      (held >= hold_days_max)

    Stop-loss is checked before theme signals so that a sharp move forces
    exit even if the LLM still likes the theme.
    """
    if position.pnl_pct <= params.stop_loss_pct:
        return ExitDecision(True, EXIT_PRICE_STOP)

    if todays_theme is not None:
        if todays_theme.direction != "bull":
            return ExitDecision(True, EXIT_THEME_INVERSION)
        if todays_theme.confidence < params.exit_confidence:
            return ExitDecision(True, EXIT_CONFIDENCE_DECAY)

    if position.days_held >= params.hold_days_max:
        return ExitDecision(True, EXIT_TIME_STOP)

    return ExitDecision(False, None)


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def size_position(
    msr_slot_capital: float,
    vehicle: VehicleSignals,
    params: MSRParams = MSRParams(),
) -> tuple[int, float]:
    """Vol-target an entry inside the MSR slot.

    Formula (spec §5)::

        target_notional = min(
            params.size_pct_max * slot,
            (params.vol_target_daily / vol_21d) * slot,
        )
        target_notional = max(target_notional, params.size_pct_min * slot)
        shares          = floor(target_notional / price)
        notional        = shares * price

    Returns ``(shares, notional)``. ``(0, 0.0)`` if price/vol invalid or
    capital insufficient for a single share.
    """
    if msr_slot_capital <= 0 or vehicle.last_price <= 0:
        return (0, 0.0)
    vol = vehicle.realised_vol_21d
    if not math.isfinite(vol) or vol <= 0:
        # No vol estimate → fall back to size_pct_min so we don't oversize.
        target_notional = params.size_pct_min * msr_slot_capital
    else:
        vol_target_notional = (params.vol_target_daily / vol) * msr_slot_capital
        target_notional = min(params.size_pct_max * msr_slot_capital,
                              vol_target_notional)
        target_notional = max(target_notional,
                              params.size_pct_min * msr_slot_capital)

    shares = int(target_notional // vehicle.last_price)
    if shares <= 0:
        return (0, 0.0)
    return (shares, shares * vehicle.last_price)


# ---------------------------------------------------------------------------
# Book-level circuit breakers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookState:
    """Snapshot of book-level risk metrics on the current trading day."""
    open_positions: int
    mtd_pnl_pct: float               # month-to-date PnL as fraction of slot
    nav_drawdown_pct: float          # 0..1, distance from all-time-high
    vix: float
    corr_60d_vs_v8a: float


@dataclass(frozen=True)
class BookGate:
    can_open: bool
    reason: str                      # "ok" or first failing gate


def book_can_open(
    book: BookState,
    params: MSRParams = MSRParams(),
) -> BookGate:
    """Aggregate book-level entry gates from spec §6.

    Order matters for reason reporting. Each gate fails closed if its input
    is non-finite.
    """
    if book.open_positions >= params.max_concurrent:
        return BookGate(False, f"max_concurrent={book.open_positions}")
    if not math.isfinite(book.vix) or book.vix >= params.vix_max:
        return BookGate(False, f"vix={book.vix:.1f}")
    if book.mtd_pnl_pct <= params.book_freeze_mtd:
        return BookGate(False, f"mtd_freeze={book.mtd_pnl_pct:.3f}")
    if book.nav_drawdown_pct >= 0.15:
        return BookGate(False, f"nav_dd={book.nav_drawdown_pct:.3f}")
    if (math.isfinite(book.corr_60d_vs_v8a)
            and book.corr_60d_vs_v8a > params.corr_max_vs_v8a):
        return BookGate(False, f"corr_vs_v8a={book.corr_60d_vs_v8a:.2f}")
    return BookGate(True, "ok")


def book_must_flatten(
    book: BookState,
    params: MSRParams = MSRParams(),
) -> Optional[str]:
    """Return a non-None reason string if the book should be force-closed.

    Triggered by MTD ≤ flatten threshold or NAV DD ≥ 15%.
    """
    if book.mtd_pnl_pct <= params.book_flatten_mtd:
        return f"book_flatten_mtd={book.mtd_pnl_pct:.3f}"
    if book.nav_drawdown_pct >= 0.15:
        return f"book_flatten_nav_dd={book.nav_drawdown_pct:.3f}"
    return None


# ---------------------------------------------------------------------------
# Driver helper — used by the equity_backtester
# ---------------------------------------------------------------------------

def select_entries(
    themes: Iterable[ThemeRecord],
    vehicle_lookup: Dict[str, Optional[VehicleSignals]],
    book: BookState,
    open_theme_names: set[str],
    params: MSRParams = MSRParams(),
) -> list[EntryDecision]:
    """Walk today's themes and return accepted entry decisions, capped by
    ``max_concurrent``. ``vehicle_lookup`` maps theme.name → VehicleSignals
    (or None if no mapping). Themes already open are skipped to avoid
    re-pyramiding into the same exposure.
    """
    gate = book_can_open(book, params)
    if not gate.can_open:
        return []

    slots_available = max(0, params.max_concurrent - book.open_positions)
    if slots_available == 0:
        return []

    # Rank themes by confidence (desc) — highest-conviction first.
    ranked = sorted(themes, key=lambda t: t.confidence, reverse=True)
    accepted: list[EntryDecision] = []
    for theme in ranked:
        if len(accepted) >= slots_available:
            break
        if theme.name in open_theme_names:
            continue
        veh = vehicle_lookup.get(theme.name)
        decision = evaluate_entry(theme, veh, params)
        if decision.accept:
            accepted.append(decision)
    return accepted


__all__ = [
    "EXIT_TIME_STOP",
    "EXIT_CONFIDENCE_DECAY",
    "EXIT_THEME_INVERSION",
    "EXIT_PRICE_STOP",
    "MSRParams",
    "MSRPosition",
    "ThemeRecord",
    "VehicleSignals",
    "BookState",
    "EntryDecision",
    "ExitDecision",
    "BookGate",
    "evaluate_entry",
    "evaluate_exit",
    "size_position",
    "book_can_open",
    "book_must_flatten",
    "select_entries",
]
