"""Safe Kelly 9/7/4 sizing — shared port of the EXP-800 scanner's Kelly engine.

Ported verbatim-behavior from ``scripts/exp800_safe_kelly_scanner.py`` so the
``main.py scheduler`` path (AlertPositionSizer) can size with the same regime
fractions and 3-tier circuit breakers that produced the EXP-800 paper track
record. Any behavioral divergence from the scanner is a bug — the parity test
in ``tests/test_kelly_sizing.py`` runs both implementations side by side.

State is persisted per-experiment in the ``kelly_state`` table of the
experiment DB (one row, id=1), exactly like the scanner.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

KELLY_DEFAULTS = {
    "regime_fractions": {"bull": 9.0, "neutral": 7.0, "bear": 4.0},
    "sizing_base": "current_equity",
    "circuit_breakers": {
        "tier1_dd": -8.0,
        "tier2_dd": -10.0,
        "tier3_dd": -12.0,
        "min_fraction": 2.0,
        "tier3_halt_trades": 30,
        "recovery_dd": -7.0,
    },
}

# The engine's structure names imply the regime that selected them:
# bull regime → directional bull puts, bear → bear calls, neutral → condors.
STRUCTURE_REGIME = {
    "bull_put": "bull",
    "bull_put_spread": "bull",
    "bear_call": "bear",
    "bear_call_spread": "bear",
    "iron_condor": "neutral",
}


def regime_for_structure(spread_type: str) -> str:
    key = str(spread_type or "").lower()
    if "condor" in key:
        return "neutral"
    return STRUCTURE_REGIME.get(key, "neutral")


def size_contracts(
    equity: float,
    kelly_pct: float,
    spread_width: float,
    credit_per_share: float,
    max_contracts: int,
) -> int:
    """Scanner's ``_size_contracts`` verbatim (exp800_safe_kelly_scanner.py:389)."""
    risk_dollars = equity * kelly_pct / 100.0
    max_loss = (spread_width - credit_per_share) * 100.0
    if max_loss <= 0:
        return 1
    return max(1, min(int(risk_dollars / max_loss), max_contracts))


_KELLY_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kelly_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    hwm             REAL    NOT NULL,
    current_equity  REAL    NOT NULL,
    drawdown_pct    REAL    NOT NULL,
    cb_tier         INTEGER NOT NULL DEFAULT 0,
    halt_remaining  INTEGER NOT NULL DEFAULT 0,
    last_updated    TEXT    NOT NULL
)
"""


class KellyStateDB:
    """Persist Kelly high-water mark and circuit-breaker state across scans.

    Port of the scanner's KellyStateDB (exp800_safe_kelly_scanner.py:416-513).
    """

    def __init__(self, db_path: Path, account_size: float):
        self.db_path = Path(db_path)
        self.account_size = account_size
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(_KELLY_STATE_SCHEMA)
            conn.commit()
            row = conn.execute("SELECT id FROM kelly_state WHERE id=1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO kelly_state (id, hwm, current_equity, drawdown_pct, cb_tier, halt_remaining, last_updated) "
                    "VALUES (1, ?, ?, 0.0, 0, 0, ?)",
                    (account_size, account_size, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                logger.info("KellyStateDB: bootstrapped HWM=%.2f", account_size)

    def load(self) -> Dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT hwm, current_equity, drawdown_pct, cb_tier, halt_remaining, last_updated "
                "FROM kelly_state WHERE id=1"
            ).fetchone()
        if row is None:
            return {"hwm": self.account_size, "current_equity": self.account_size,
                    "drawdown_pct": 0.0, "cb_tier": 0, "halt_remaining": 0, "last_updated": ""}
        keys = ["hwm", "current_equity", "drawdown_pct", "cb_tier", "halt_remaining", "last_updated"]
        return dict(zip(keys, row))

    def save(self, state: Dict) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE kelly_state SET hwm=?, current_equity=?, drawdown_pct=?, "
                "cb_tier=?, halt_remaining=?, last_updated=? WHERE id=1",
                (state["hwm"], state["current_equity"], state["drawdown_pct"],
                 state["cb_tier"], state["halt_remaining"],
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def update_equity(self, current_equity: float, cb_cfg: Dict) -> Dict:
        """Update HWM/drawdown/CB tier from live equity. Returns updated state dict."""
        state = self.load()
        hwm = state["hwm"]

        if current_equity > hwm:
            hwm = current_equity
            logger.info("KellyState: new HWM=%.2f", hwm)

        dd_pct = (current_equity - hwm) / hwm * 100.0  # negative when below HWM

        tier1_dd = float(cb_cfg.get("tier1_dd", -8.0))
        tier2_dd = float(cb_cfg.get("tier2_dd", -10.0))
        tier3_dd = float(cb_cfg.get("tier3_dd", -12.0))
        recovery = float(cb_cfg.get("recovery_dd", -7.0))
        halt_count = int(cb_cfg.get("tier3_halt_trades", 30))

        prev_tier = state["cb_tier"]
        prev_halt = state["halt_remaining"]

        if dd_pct <= tier3_dd:
            new_tier = 3
            new_halt = halt_count if prev_tier < 3 else prev_halt  # only reset on fresh Tier 3 trigger
        elif dd_pct <= tier2_dd:
            new_tier = 2
            new_halt = prev_halt if prev_tier == 3 else 0
        elif dd_pct <= tier1_dd:
            new_tier = 1
            new_halt = 0
        else:
            if prev_tier >= 2 and dd_pct > recovery:
                new_tier = 0
                new_halt = 0
                logger.info("KellyState: recovered from Tier %d (DD=%.2f%% > %.2f%%)",
                            prev_tier, dd_pct, recovery)
            elif prev_tier == 1 and dd_pct > tier1_dd:
                new_tier = 0
                new_halt = 0
            else:
                new_tier = prev_tier
                new_halt = prev_halt

        if new_tier != prev_tier:
            logger.warning("KellyState: CB tier %d → %d  DD=%.2f%%  equity=%.2f  HWM=%.2f",
                           prev_tier, new_tier, dd_pct, current_equity, hwm)

        state.update({
            "hwm": hwm,
            "current_equity": current_equity,
            "drawdown_pct": round(dd_pct, 4),
            "cb_tier": new_tier,
            "halt_remaining": new_halt,
        })
        self.save(state)
        return state

    def decrement_halt(self) -> None:
        """Decrement halt counter for Tier 3 when a trade slot is consumed."""
        state = self.load()
        if state["cb_tier"] >= 3 and state["halt_remaining"] > 0:
            state["halt_remaining"] = state["halt_remaining"] - 1
            if state["halt_remaining"] == 0:
                logger.info("KellyState: Tier 3 halt counter exhausted — resuming normal sizing")
            self.save(state)


def kelly_fraction(regime: str, kelly_cfg: Dict, state: Dict) -> Tuple[float, str]:
    """Return (effective_kelly_pct, sizing_note). Returns (0.0, reason) to skip.

    Port of the scanner's ``_kelly_fraction`` (exp800_safe_kelly_scanner.py:520).
    """
    fractions = kelly_cfg.get("regime_fractions", KELLY_DEFAULTS["regime_fractions"])
    cb_cfg = kelly_cfg.get("circuit_breakers", KELLY_DEFAULTS["circuit_breakers"])

    base_frac = float(fractions.get(regime, fractions.get("neutral", 7.0)))
    tier = state["cb_tier"]
    halt = state["halt_remaining"]
    min_frac = float(cb_cfg.get("min_fraction", 2.0))

    if tier >= 3 and halt > 0:
        return 0.0, f"cb_tier3_halted: {halt} slots remaining"

    if tier == 2:
        return min_frac, f"cb_tier2: floor={min_frac}%"

    if tier == 1:
        eff = base_frac * 0.5
        return eff, f"cb_tier1: 0.5× base={base_frac}% → {eff}%"

    return base_frac, f"cb_tier0: full Kelly={base_frac}%"
