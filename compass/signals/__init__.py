"""3-family tilt-score signal engine (momentum + flow + sentiment).

Public surface::

    from compass.signals import compute_tilt_score, PolygonSignalDataProvider

    provider = PolygonSignalDataProvider()
    result = compute_tilt_score("SPY", as_of="2026-05-27", provider=provider)
    # result is a dict with: ticker, as_of, momentum_z, flow_z, sentiment_z, tilt_score

See README.md for the data-flow diagram and signal definitions.
"""
from compass.signals._data import PolygonSignalDataProvider
from compass.signals.dark_flow import (
    compute_dark_flow_batch,
    compute_dark_flow_signal,
)
from compass.signals.momentum import compute_momentum_signal
from compass.signals.flow_proxy import compute_flow_signal
from compass.signals.sentiment_proxy import compute_sentiment_signal
from compass.signals.tilt_score import compute_tilt_score

__all__ = [
    "PolygonSignalDataProvider",
    "compute_momentum_signal",
    "compute_flow_signal",
    "compute_sentiment_signal",
    "compute_tilt_score",
    "compute_dark_flow_signal",
    "compute_dark_flow_batch",
]
