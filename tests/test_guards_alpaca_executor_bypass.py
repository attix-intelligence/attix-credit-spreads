"""
Tests for the config-aware Alpaca health check in sentinel/guards.py.

Behavior under test:
- alpaca.enabled=true (or absent)  → existing Alpaca creds/health check runs
- alpaca.enabled=false             → Alpaca check skipped (executor-routed sink)
- config=None                      → defaults to existing behavior (back-compat)
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel import guards  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _executor_routed_config():
    """Mirrors live_exp800_tradier.yaml's relevant shape."""
    return {
        "alpaca": {"enabled": False, "paper": False},
        "tradier_live": {
            "enabled": True,
            "account_id": "tradier_6YA42569",
            "account_type": "live",
            "sink_type": "executor",
        },
    }


def _alpaca_routed_config():
    return {"alpaca": {"enabled": True}}


# ---------------------------------------------------------------------------
# _check_alpaca_health — direct behavior
# ---------------------------------------------------------------------------

def test_executor_routed_bypasses_alpaca_check(monkeypatch):
    """alpaca.enabled=false -> the function returns without touching env or net."""
    # No Alpaca env vars set; no requests should be issued.
    monkeypatch.delenv("ALPACA_API_KEY_EXP800TRADIER", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_EXP800TRADIER", raising=False)

    with patch("requests.get") as mock_get:
        # Must not sys.exit, must not call requests.get.
        guards._check_alpaca_health("EXP-800-TRADIER", config=_executor_routed_config())
        assert not mock_get.called, "requests.get must not be called when alpaca.enabled=false"


def test_alpaca_enabled_with_missing_creds_still_halts(monkeypatch):
    """Existing Alpaca safety preserved: enabled=true + missing creds -> sys.exit."""
    monkeypatch.delenv("ALPACA_API_KEY_EXPV8A", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_EXPV8A", raising=False)

    with patch("sentinel.guards._send_alert"):
        with pytest.raises(SystemExit) as excinfo:
            guards._check_alpaca_health("EXP-V8A", config=_alpaca_routed_config())
    assert excinfo.value.code == 1


def test_config_none_defaults_to_existing_behavior(monkeypatch):
    """Back-compat: config=None means Alpaca check still runs (and halts on missing creds)."""
    monkeypatch.delenv("ALPACA_API_KEY_EXP800", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_EXP800", raising=False)

    with patch("sentinel.guards._send_alert"):
        with pytest.raises(SystemExit):
            guards._check_alpaca_health("EXP-800")  # no config kwarg


def test_alpaca_missing_section_treated_as_enabled(monkeypatch):
    """A config with no 'alpaca' section -> behave as if alpaca is enabled (safe default)."""
    monkeypatch.delenv("ALPACA_API_KEY_EXP800", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_EXP800", raising=False)

    with patch("sentinel.guards._send_alert"):
        with pytest.raises(SystemExit):
            guards._check_alpaca_health("EXP-800", config={"experiment_id": "EXP-800"})


def test_alpaca_enabled_explicit_true_with_missing_creds_halts(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_EXP800", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_EXP800", raising=False)

    with patch("sentinel.guards._send_alert"):
        with pytest.raises(SystemExit):
            guards._check_alpaca_health(
                "EXP-800", config={"alpaca": {"enabled": True}}
            )


# ---------------------------------------------------------------------------
# pre_scan_check — end-to-end threading
# ---------------------------------------------------------------------------

def test_pre_scan_check_threads_config_to_alpaca_check():
    """pre_scan_check(config=...) -> _check_alpaca_health receives the same config."""
    sentinel_cfg = _executor_routed_config()

    with patch("sentinel.guards._check_registry_status"), \
         patch("sentinel.guards._load_state", return_value={}), \
         patch("sentinel.guards._check_alpaca_health") as mock_alpaca:
        guards.pre_scan_check("EXP-800-TRADIER", config=sentinel_cfg)

    mock_alpaca.assert_called_once_with("EXP-800-TRADIER", config=sentinel_cfg)


def test_pre_scan_check_without_config_passes_none():
    """Back-compat: pre_scan_check called without config kwarg -> Alpaca check gets None."""
    with patch("sentinel.guards._check_registry_status"), \
         patch("sentinel.guards._load_state", return_value={}), \
         patch("sentinel.guards._check_alpaca_health") as mock_alpaca:
        guards.pre_scan_check("EXP-800")

    mock_alpaca.assert_called_once_with("EXP-800", config=None)
