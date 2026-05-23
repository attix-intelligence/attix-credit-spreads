"""Live regime gate consumed by the SPX stream sizer.

Wires the EXP-3303b live composite-stress signal into the production
sizing path. Callers ask::

    from shared.regime_gate import RegimeGate
    gate = RegimeGate(theta=2.5)
    if gate.should_gate_spx_streams():
        # scale stream notional down per EXP-3303b
        ...

The default ``theta`` (2.5) mirrors the value EXP-3303b sweeps over and
ships as the production setting. Override per-environment via the
``REGIME_GATE_THETA`` env var without code changes.

Failure semantics
-----------------
When the composite-stress reading is unavailable we follow the backtest's
``apply_regime_gate`` warm-up handling: ``leverage = 1.0`` (do not gate).
The composite itself still returns ``None`` per Rule Zero — fail-closed
applies to the value, not to the gate decision (which intentionally
mirrors the backtest to keep live ≡ research).

Integration point (PR #30 follow-up)
------------------------------------
This module is the single seam the sizer should call. The previous
``compass/archive/regime_gate.py`` is unrelated (it gated on regime
labels — bull/bear/etc., not on composite stress) and stays archived.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from compass.live_composite_stress import (
    get_current_composite_stress,
    should_gate_spx_streams as _should_gate_from_composite,
)

logger = logging.getLogger(__name__)

DEFAULT_THETA = 2.5


def _theta_from_env(default: float = DEFAULT_THETA) -> float:
    raw = os.environ.get("REGIME_GATE_THETA")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "REGIME_GATE_THETA=%r is not a float; falling back to %.2f",
            raw, default,
        )
        return default


@dataclass
class RegimeGate:
    """Thin façade over ``compass.live_composite_stress``.

    Holds the gate threshold so the sizer reads a single object rather
    than reaching into the composite module directly.
    """

    theta: float = DEFAULT_THETA

    @classmethod
    def from_env(cls) -> "RegimeGate":
        return cls(theta=_theta_from_env())

    def current_stress(self) -> Optional[float]:
        return get_current_composite_stress()

    def should_gate_spx_streams(self) -> bool:
        """Return True iff the SPX streams should be scaled down right now."""
        return _should_gate_from_composite(theta=self.theta)
