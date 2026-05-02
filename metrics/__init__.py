"""Metrics-eligible trade filters and Gate-facing query helpers.

See `docs/metrics_data_pipeline.md` for the architectural rationale.
"""

from metrics.eligible_trades import (
    ELIGIBLE_CTE_NAME,
    OPEN_CTE_NAME,
    metrics_eligible_cte,
    open_eligible_cte,
)

__all__ = [
    "ELIGIBLE_CTE_NAME",
    "OPEN_CTE_NAME",
    "metrics_eligible_cte",
    "open_eligible_cte",
]
