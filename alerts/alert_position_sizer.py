"""
AlertPositionSizer — calculates contract count for approved alert opportunities.

Implements flat-risk sizing that matches backtester.py sizing logic (exp_154):
  - Directional spreads (bull_put / bear_call): max_risk_per_trade% of starting_capital
  - Iron condors: ic_risk_per_trade% of starting_capital (separate budget, default 12%)
  - Sizing mode: 'flat' uses starting_capital as base; 'compound' uses current equity
  - VIX dynamic scaling (optional): reduces size at elevated VIX

Portfolio mode (compass_portfolio_mode: true):
  - Capital is split per-ticker based on compass.portfolio_weights config
  - SPY gets compass.portfolio_weights.spy_pct of total capital
  - Sector ETFs split compass.portfolio_weights.sector_pct evenly among active sectors
  - Macro score scaling: score < 45 → 1.2× size; score > 75 → 0.85× size
  - Per-ticker max_contracts is derived from the ticker's capital allocation

Backward compatibility: if config is not injected at construction, falls back to the
legacy IV-rank dynamic sizer (original behaviour for exp_036/exp_059).
"""

import logging
import os
from pathlib import Path
from typing import Optional

from alerts.alert_schema import Alert, AlertType, SizeResult

# Module-level import for testability (allows unittest.mock.patch to replace it)
try:
    from compass.macro_db import get_current_macro_score
except ImportError:  # pragma: no cover
    def get_current_macro_score():  # type: ignore[misc]
        return 50.0

logger = logging.getLogger(__name__)

# Legacy fallback (used when no config injected)
_LEGACY_MAX_CONTRACTS = 5
_LEGACY_BASE_RISK_PCT = 0.02

# Macro score thresholds for position size scaling (COMPASS portfolio mode).
# Mirrors backtester.py lines 607-616 (5-tier scale):
#   ra < 30  → 1.2× (strong fear boost)
#   ra < 45  → 1.1× (mild fear boost)
#   ra > 75  → 0.85× (strong greed reduction)
#   ra > 65  → 0.95× (mild greed reduction)
#   else     → 1.0× (neutral)
_MACRO_STRONG_FEAR_THRESHOLD = 30   # score < this → 1.2×
_MACRO_MILD_FEAR_THRESHOLD = 45     # score < this → 1.1×
_MACRO_MILD_GREED_THRESHOLD = 65    # score > this → 0.95×
_MACRO_STRONG_GREED_THRESHOLD = 75  # score > this → 0.85×
# Backward-compat aliases used in tests
_MACRO_FEAR_SCALE = 1.20
_MACRO_GREED_SCALE = 0.85


class AlertPositionSizer:
    """Account-aware position sizer for the alert pipeline.

    Args:
        config: Full application config dict. If None, uses legacy IV-rank sizer.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config

    def size(
        self,
        alert: Alert,
        account_value: float,
        iv_rank: float,
        current_portfolio_risk: float,
        weekly_loss_breach: bool = False,
        macro_score: Optional[float] = None,
        rrg_quadrant: Optional[str] = None,
    ) -> SizeResult:
        """Calculate position size for an alert.

        When compass_portfolio_mode is enabled, routes to portfolio-aware sizing.
        If config is available but portfolio mode is off, uses flat 5%/12% risk.
        Otherwise falls back to legacy IV-rank dynamic sizing.

        Args:
            alert: The candidate alert.
            account_value: Current account balance in dollars.
            iv_rank: Current IV Rank 0–100 (used by legacy sizer only).
            current_portfolio_risk: Dollar value of open max-loss exposure.
            weekly_loss_breach: If True, cut size by 50%.
            macro_score: COMPASS macro score 0–100. When provided and portfolio
                         mode is enabled, used for fear/greed position scaling.
                         If None, the sizer will attempt to read from macro_state.db.
            rrg_quadrant: RRG quadrant for the underlying (unused currently,
                          reserved for future directional bias scaling).

        Returns:
            SizeResult with risk_pct, contracts, dollar_risk, max_loss.
        """
        if not self.config:
            return self._legacy_size(alert, account_value, iv_rank, current_portfolio_risk, weekly_loss_breach)

        # Safe Kelly 9/7/4 (EXP-800): takes precedence over flat/portfolio when
        # the config carries a kelly.regime_fractions block.
        if self.config.get("kelly", {}).get("regime_fractions"):
            return self._kelly_size(alert, account_value, weekly_loss_breach)

        compass_cfg = self.config.get("compass", {})
        if compass_cfg.get("portfolio_mode", False):
            return self._portfolio_risk_size(
                alert, account_value, weekly_loss_breach, macro_score
            )

        return self._flat_risk_size(alert, account_value, weekly_loss_breach, macro_score)

    # ------------------------------------------------------------------
    # Safe Kelly 9/7/4 sizing (EXP-800 — ported from exp800_safe_kelly_scanner)
    # ------------------------------------------------------------------

    def _kelly_size(
        self,
        alert: Alert,
        account_value: float,
        weekly_loss_breach: bool,
    ) -> SizeResult:
        """Regime-fraction Kelly sizing with 3-tier drawdown circuit breakers.

        Behavior mirrors scripts/exp800_safe_kelly_scanner.py: update the
        Kelly state (HWM/DD/CB tier) from live equity once, derive the
        effective fraction for the regime implied by the alert's structure,
        then contracts = equity × f% ÷ ((width − credit) × 100).

        The plain (width − credit) formula is also the correct iron-condor
        worst case: only one wing can finish ITM while the full combined
        credit is kept, so max loss = wing_width − total_credit.
        """
        from shared.kelly_sizing import (
            KELLY_DEFAULTS,
            KellyStateDB,
            kelly_fraction,
            size_contracts,
        )

        kelly_cfg = self.config.get("kelly", {})
        risk_cfg = self.config.get("risk", {})
        cb_cfg = kelly_cfg.get("circuit_breakers", KELLY_DEFAULTS["circuit_breakers"])
        account_size = float(risk_cfg.get("account_size", 100_000))
        max_contracts = int(risk_cfg.get("max_contracts", 30))

        db_path = os.environ.get("ATTIX_DB_PATH") or self.config.get("db_path")
        if not db_path:
            logger.error(
                "AlertPositionSizer(kelly): no db_path (ATTIX_DB_PATH/config) — "
                "cannot persist Kelly state, refusing to size"
            )
            return SizeResult(risk_pct=0.0, contracts=0, dollar_risk=0.0, max_loss=0.0)
        state_db = KellyStateDB(Path(db_path), account_size)

        # Scanner parity: update_equity runs once per scan before sizing.
        # A missing/zero account_value must not clobber the persisted equity.
        if account_value and account_value > 0:
            state = state_db.update_equity(float(account_value), cb_cfg)
        else:
            state = state_db.load()

        regime = self._regime_for_alert(alert)
        kelly_pct, note = kelly_fraction(regime, kelly_cfg, state)
        if kelly_pct <= 0:
            logger.warning(
                "AlertPositionSizer(kelly): skip %s %s — %s",
                alert.ticker, alert.type.value, note,
            )
            return SizeResult(risk_pct=0.0, contracts=0, dollar_risk=0.0, max_loss=0.0)

        if weekly_loss_breach:
            kelly_pct *= 0.5
            note += " | weekly_loss_breach 0.5×"

        sizing_base = kelly_cfg.get("sizing_base", "current_equity")
        sizing_equity = (
            float(state["current_equity"]) if sizing_base == "current_equity" else account_size
        )

        spread_width, credit = self._extract_spread_params(alert)
        contracts = size_contracts(sizing_equity, kelly_pct, spread_width, credit, max_contracts)

        max_loss_per_spread = max((spread_width - credit) * 100.0, 1.0)
        dollar_risk = contracts * max_loss_per_spread
        risk_pct = dollar_risk / sizing_equity if sizing_equity > 0 else 0.0

        logger.info(
            "AlertPositionSizer(kelly): %s %s regime=%s [%s] equity=$%.0f "
            "width=$%.0f credit=%.2f → %d contracts ($%.0f risk, %.2f%%)",
            alert.ticker, alert.type.value, regime, note, sizing_equity,
            spread_width, credit, contracts, dollar_risk, risk_pct * 100,
        )

        return SizeResult(
            risk_pct=risk_pct,
            contracts=contracts,
            dollar_risk=dollar_risk,
            max_loss=dollar_risk,
        )

    @staticmethod
    def _regime_for_alert(alert: Alert) -> str:
        """Map an alert's structure back to the regime that selected it:
        iron condor → neutral, bullish credit spread (bull put) → bull,
        bearish credit spread (bear call) → bear."""
        if alert.type == AlertType.iron_condor or "condor" in str(alert.type.value).lower():
            return "neutral"
        direction = getattr(alert.direction, "value", str(alert.direction or "")).lower()
        if direction == "bullish":
            return "bull"
        if direction == "bearish":
            return "bear"
        return "neutral"

    # ------------------------------------------------------------------
    # Portfolio-mode sizing (COMPASS multi-underlying)
    # ------------------------------------------------------------------

    def _portfolio_risk_size(
        self,
        alert: Alert,
        account_value: float,
        weekly_loss_breach: bool,
        macro_score: Optional[float],
    ) -> SizeResult:
        """Portfolio-aware sizing: per-ticker capital allocation + macro scaling.

        Allocation logic:
          - SPY: `compass.portfolio_weights.spy_pct` × account_value
          - Sector ETF: `compass.portfolio_weights.sector_pct` / n_active_sectors
            × account_value
          - Unlisted ticker: falls back to flat_risk_size
        """
        compass_cfg = self.config.get("compass", {})
        weights_cfg = compass_cfg.get("portfolio_weights", {})
        risk_cfg = self.config.get("risk", {})
        strategy_cfg = self.config.get("strategy", {})
        backtest_cfg = self.config.get("backtest", {})

        ticker = alert.ticker.upper()

        # Resolve ticker's allocation weight
        spy_pct = float(weights_cfg.get("spy_pct", 0.60))
        sector_pct = float(weights_cfg.get("sector_pct", 0.40))

        # Active sectors list (from config; CC1 populates this at scan time)
        active_sectors = [s.upper() for s in compass_cfg.get("active_sectors", [])]

        # Per-ticker weight
        if ticker == "SPY":
            allocation_weight = spy_pct
        elif ticker in active_sectors and len(active_sectors) > 0:
            allocation_weight = sector_pct / len(active_sectors)
        else:
            # Unknown ticker — fall back to flat sizing
            logger.warning(
                "AlertPositionSizer (portfolio): %s not in active_sectors %s, "
                "falling back to flat sizing",
                ticker, active_sectors,
            )
            return self._flat_risk_size(alert, account_value, weekly_loss_breach)

        # Account base for this ticker's allocation
        account_base = account_value * allocation_weight

        # Sizing mode (flat vs compound)
        sizing_mode = risk_cfg.get("sizing_mode", "flat")
        if sizing_mode == "flat":
            starting_capital = float(
                backtest_cfg.get("starting_capital", risk_cfg.get("account_size", 100_000))
            )
            account_base = starting_capital * allocation_weight

        # Detect iron condor
        is_ic = alert.type.value == "iron_condor" or "condor" in str(alert.type).lower()

        # Risk % per trade (same as flat mode — applied to the allocated slice)
        if is_ic:
            ic_cfg = strategy_cfg.get("iron_condor", {})
            raw_risk_pct = float(ic_cfg.get("ic_risk_per_trade", 12.0)) / 100.0
        else:
            raw_risk_pct = float(risk_cfg.get("max_risk_per_trade", 5.0)) / 100.0

        # Macro score scaling
        effective_risk_pct = raw_risk_pct * self._macro_scale(macro_score)

        dollar_risk = account_base * effective_risk_pct

        # Spread geometry
        spread_width, credit = self._extract_spread_params(alert)
        if is_ic:
            # IC max loss = both wings' width minus combined credit (worst case: both ITM).
            max_loss_per_spread = max((2 * spread_width - credit) * 100, 1.0)
        else:
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)

        contracts = int(dollar_risk / max_loss_per_spread) if max_loss_per_spread > 0 else 1

        # Contract caps: global config cap and per-ticker allocation cap
        min_contracts = int(risk_cfg.get("min_contracts", 1))
        global_max = int(risk_cfg.get("max_contracts", 25))

        # Per-ticker max_contracts derived from full account allocation budget
        # (allocation_budget / max_loss_per_spread, rounded down)
        full_allocation_budget = account_value * allocation_weight
        ticker_max_contracts = int(full_allocation_budget / max_loss_per_spread) if max_loss_per_spread > 0 else global_max
        effective_max = min(global_max, ticker_max_contracts)

        contracts = max(min_contracts, min(contracts, effective_max))

        actual_dollar_risk = contracts * max_loss_per_spread
        actual_risk_pct = actual_dollar_risk / account_base if account_base > 0 else 0.0
        max_loss = actual_dollar_risk

        logger.info(
            "AlertPositionSizer (portfolio): %s %s | alloc=%.1f%% base=$%.0f "
            "risk=%.1f%% macro_scale=%.2f → %d contracts ($%.0f max loss)",
            ticker, alert.type.value,
            allocation_weight * 100, account_base,
            raw_risk_pct * 100,
            self._macro_scale(macro_score),
            contracts, max_loss,
        )

        return SizeResult(
            risk_pct=actual_risk_pct,
            contracts=contracts,
            dollar_risk=actual_dollar_risk,
            max_loss=max_loss,
        )

    def _macro_scale(self, macro_score: Optional[float]) -> float:
        """Return position size scalar based on macro score.

        Mirrors backtester.py lines 607-616 (5-tier scale).
        If macro_score is None, attempts to read from macro_state.db.
        Falls back to 1.0 (no scaling) on any error.

        Returns:
            1.2  (strong fear boost)  if score < 30
            1.1  (mild fear boost)    if 30 <= score < 45
            0.85 (strong greed cut)   if score > 75
            0.95 (mild greed cut)     if 65 < score <= 75
            1.0  (neutral)            otherwise
        """
        score = macro_score
        if score is None:
            try:
                score = get_current_macro_score()
            except Exception as e:
                logger.debug("AlertPositionSizer: macro score fetch failed: %s", e)
                return 1.0

        if score < _MACRO_STRONG_FEAR_THRESHOLD:
            scale = 1.20
            logger.info("AlertPositionSizer: macro_score=%.1f < %d → strong fear boost ×%.2f",
                        score, _MACRO_STRONG_FEAR_THRESHOLD, scale)
            return scale
        if score < _MACRO_MILD_FEAR_THRESHOLD:
            scale = 1.10
            logger.info("AlertPositionSizer: macro_score=%.1f < %d → mild fear boost ×%.2f",
                        score, _MACRO_MILD_FEAR_THRESHOLD, scale)
            return scale
        if score > _MACRO_STRONG_GREED_THRESHOLD:
            scale = 0.85
            logger.info("AlertPositionSizer: macro_score=%.1f > %d → strong greed reduction ×%.2f",
                        score, _MACRO_STRONG_GREED_THRESHOLD, scale)
            return scale
        if score > _MACRO_MILD_GREED_THRESHOLD:
            scale = 0.95
            logger.info("AlertPositionSizer: macro_score=%.1f > %d → mild greed reduction ×%.2f",
                        score, _MACRO_MILD_GREED_THRESHOLD, scale)
            return scale
        return 1.0

    # ------------------------------------------------------------------
    # Flat-risk sizing (exp_154 / backtest-parity mode)
    # ------------------------------------------------------------------

    def _flat_risk_size(
        self,
        alert: Alert,
        account_value: float,
        weekly_loss_breach: bool,
        macro_score: Optional[float] = None,
    ) -> SizeResult:
        """Flat-risk sizing matching backtester.py logic."""
        risk_cfg = self.config.get("risk", {})
        sizing_cfg = self.config.get("sizing", {})
        strategy_cfg = self.config.get("strategy", {})
        backtest_cfg = self.config.get("backtest", {})
        account_cfg = self.config.get("account", {})

        # Merge `sizing:` section as fallback so legacy paper configs (which
        # put position-sizing fields under `sizing:` with names like
        # `leveraged_risk_pct` / `contracts_max`) keep working. The `risk:`
        # section always wins on key collision.
        effective_risk = {**sizing_cfg, **risk_cfg}

        # Sizing base: flat uses starting_capital, compound uses current equity
        sizing_mode = effective_risk.get("sizing_mode", "flat")
        starting_capital = float(
            backtest_cfg.get(
                "starting_capital",
                account_cfg.get(
                    "starting_capital",
                    effective_risk.get("account_size", 100_000),
                ),
            )
        )
        account_base = starting_capital if sizing_mode == "flat" else account_value

        # Detect iron condor
        is_ic = alert.type.value == "iron_condor" or "condor" in str(alert.type).lower()

        # Risk % per trade. Support both the canonical `max_risk_per_trade`
        # key and the legacy `sizing.leveraged_risk_pct` / `base_risk_pct`
        # aliases used by the paper-sweep configs.
        if is_ic:
            ic_cfg = strategy_cfg.get("iron_condor", {})
            raw_risk_pct = float(ic_cfg.get("ic_risk_per_trade", 12.0)) / 100.0
        else:
            raw_risk_pct = float(
                effective_risk.get(
                    "max_risk_per_trade",
                    effective_risk.get(
                        "leveraged_risk_pct",
                        effective_risk.get("base_risk_pct", 5.0),
                    ),
                )
            ) / 100.0

        # VIX dynamic scaling (optional — only if vix_dynamic_sizing configured)
        vix_scale = 1.0
        vix_sizing_cfg = strategy_cfg.get("vix_dynamic_sizing", {})
        if vix_sizing_cfg:
            current_vix = self._get_current_vix()
            vix_scale = self._compute_vix_scale(current_vix, vix_sizing_cfg)
            if vix_scale == 0.0:
                logger.info("AlertPositionSizer: VIX scaling blocked entry (scale=0)")
                return SizeResult(risk_pct=0.0, contracts=0, dollar_risk=0.0, max_loss=0.0)

        effective_risk_pct = raw_risk_pct * vix_scale

        # COMPASS macro score scaling — mirrors backtester lines 1643-1644.
        # Applied when strategy.compass_enabled=true (same key as backtester).
        if strategy_cfg.get("compass_enabled", False):
            effective_risk_pct *= self._macro_scale(macro_score)

        dollar_risk = account_base * effective_risk_pct

        # Spread geometry
        spread_width, credit = self._extract_spread_params(alert)
        if is_ic:
            # IC max loss = both wings' width minus combined credit (worst case: both ITM).
            max_loss_per_spread = max((2 * spread_width - credit) * 100, 1.0)
        else:
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)

        contracts = int(dollar_risk / max_loss_per_spread) if max_loss_per_spread > 0 else 1

        # Config limits — max_contracts from config (not hardcoded). Support
        # `contracts_min` / `contracts_max` aliases from the legacy `sizing:`
        # section.
        min_contracts = int(
            effective_risk.get(
                "min_contracts", effective_risk.get("contracts_min", 1)
            )
        )
        max_contracts = int(
            effective_risk.get(
                "max_contracts", effective_risk.get("contracts_max", 25)
            )
        )
        contracts = max(min_contracts, min(contracts, max_contracts))

        actual_dollar_risk = contracts * max_loss_per_spread
        actual_risk_pct = actual_dollar_risk / account_base if account_base > 0 else 0.0
        max_loss = actual_dollar_risk

        logger.debug(
            "AlertPositionSizer: %s %s | base=$%.0f risk=%.1f%% (×%.2f vix_scale) "
            "width=$%.0f credit=%.4f → %d contracts ($%.0f max loss)",
            alert.ticker, alert.type.value, account_base, raw_risk_pct * 100, vix_scale,
            spread_width, credit, contracts, max_loss,
        )

        return SizeResult(
            risk_pct=actual_risk_pct,
            contracts=contracts,
            dollar_risk=actual_dollar_risk,
            max_loss=max_loss,
        )

    def _get_current_vix(self) -> float:
        """Fetch current VIX from data cache."""
        try:
            from shared.data_cache import DataCache
            cache = DataCache()
            vix_data = cache.get_history("^VIX", period="5d")
            if not vix_data.empty:
                return float(vix_data["Close"].iloc[-1])
        except Exception as e:
            logger.warning("AlertPositionSizer: VIX fetch failed, using default 20: %s", e)
        return 20.0

    @staticmethod
    def _compute_vix_scale(vix: float, vix_cfg: dict) -> float:
        """Return position size scalar based on VIX level.

        Returns 1.0 (full), 0.5 (half), 0.25 (quarter), or 0.0 (block).
        """
        full_below = float(vix_cfg.get("full_below", 18))
        half_below = float(vix_cfg.get("half_below", 22))
        quarter_below = float(vix_cfg.get("quarter_below", 25))

        if vix < full_below:
            return 1.0
        elif vix < half_below:
            return 0.5
        elif vix < quarter_below:
            return 0.25
        else:
            return 0.0  # Block entries at extreme VIX

    # ------------------------------------------------------------------
    # Legacy IV-rank dynamic sizer (backward compat for exp_036/exp_059)
    # ------------------------------------------------------------------

    def _legacy_size(
        self,
        alert: Alert,
        account_value: float,
        iv_rank: float,
        current_portfolio_risk: float,
        weekly_loss_breach: bool,
    ) -> SizeResult:
        """Original IV-rank based dynamic sizing (pre-exp_154).

        Matches backtester: only the 40% portfolio heat cap inside
        calculate_dynamic_risk applies. The MAX_RISK_PER_TRADE extra cap layer
        and weekly-loss breach reduction are removed (backtester has neither).
        """
        from compass.sizing import calculate_dynamic_risk, get_contract_size

        dollar_risk = calculate_dynamic_risk(account_value, iv_rank, current_portfolio_risk)

        risk_pct = dollar_risk / account_value if account_value > 0 else 0.0
        spread_width, credit = self._extract_spread_params(alert)
        contracts = get_contract_size(dollar_risk, spread_width, credit)

        max_loss_per_contract = (spread_width - credit) * 100
        max_loss = max_loss_per_contract * contracts

        return SizeResult(
            risk_pct=risk_pct,
            contracts=contracts,
            dollar_risk=dollar_risk,
            max_loss=max_loss,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_spread_params(alert: Alert) -> tuple:
        """Derive (spread_width, credit) from the alert legs.

        Returns dollar-per-share values.
        """
        credit = alert.entry_price

        if len(alert.legs) >= 2:
            strikes = sorted(leg.strike for leg in alert.legs)
            if len(alert.legs) == 4:
                put_strikes = sorted(
                    leg.strike for leg in alert.legs if leg.option_type == "put"
                )
                call_strikes = sorted(
                    leg.strike for leg in alert.legs if leg.option_type == "call"
                )
                put_width = (put_strikes[-1] - put_strikes[0]) if len(put_strikes) >= 2 else 0
                call_width = (call_strikes[-1] - call_strikes[0]) if len(call_strikes) >= 2 else 0
                spread_width = max(put_width, call_width)
            else:
                spread_width = strikes[-1] - strikes[0]
        else:
            spread_width = 5.0  # fallback

        if spread_width <= 0:
            spread_width = 5.0

        return spread_width, credit
