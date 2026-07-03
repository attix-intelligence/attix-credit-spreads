"""Tests for scripts/preflight_check.validate — paper + live config branches."""
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import preflight_check  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

def _paper_config():
    """Minimum paper config that should pass validate()."""
    return {
        "paper_mode": True,
        "db_path": "data/x.db",
        "experiment_id": "EXP-X",
        "logging": {"level": "INFO", "file": "logs/x.log"},
        "strategy": {
            "use_delta_selection": True,
            "min_delta": 0.15,
            "max_delta": 0.30,
        },
        "risk": {},
    }


def _live_config():
    """Minimum live config (mirrors live_exp800_tradier.yaml shape)."""
    return {
        "paper_mode": False,
        "db_path": "data/x.db",
        "experiment_id": "EXP-800-TRADIER",
        "logging": {"level": "INFO", "file": "logs/x.log"},
        "strategy": {
            "use_delta_selection": False,
            "otm_pct": 0.02,
        },
        "risk": {"max_contracts": 30},
        "tradier_live": {
            "enabled": True,
            "account_id": "tradier_6YA42569",
            "account_type": "live",
            "sink_type": "executor",
            "base_url": "https://api.tradier.com",
            "token_env": "TRADIER_PROD_TOKEN",
        },
    }


# ---------------------------------------------------------------------------
# Paper happy-path — unchanged behavior
# ---------------------------------------------------------------------------

def test_paper_config_passes():
    assert preflight_check.validate(_paper_config()) == []


def test_paper_mode_missing_still_fails():
    cfg = _paper_config()
    cfg.pop("paper_mode")
    errors = preflight_check.validate(cfg)
    assert any("paper_mode must be true" in e for e in errors)


def test_paper_mode_non_bool_still_fails():
    cfg = _paper_config()
    cfg["paper_mode"] = "yes"
    errors = preflight_check.validate(cfg)
    assert any("paper_mode must be true" in e for e in errors)


def test_paper_delta_fields_required_when_delta_selection_enabled():
    cfg = _paper_config()
    cfg["strategy"].pop("min_delta")
    cfg["strategy"].pop("max_delta")
    errors = preflight_check.validate(cfg)
    assert any("min_delta" in e for e in errors)
    assert any("max_delta" in e for e in errors)


def test_otm_config_does_not_require_delta_fields():
    """EXP-800-family: use_delta_selection=False, otm_pct-based."""
    cfg = _paper_config()
    cfg["strategy"] = {"use_delta_selection": False, "otm_pct": 0.02}
    errors = preflight_check.validate(cfg)
    assert not any("min_delta" in e or "max_delta" in e for e in errors)


# ---------------------------------------------------------------------------
# Live branch — strict checks
# ---------------------------------------------------------------------------

def test_live_config_passes():
    assert preflight_check.validate(_live_config()) == []


def test_live_missing_tradier_block_fails():
    cfg = _live_config()
    cfg.pop("tradier_live")
    errors = preflight_check.validate(cfg)
    assert any("tradier_live" in e for e in errors)


def test_live_sink_type_must_be_executor():
    cfg = _live_config()
    cfg["tradier_live"]["sink_type"] = "alpaca"
    errors = preflight_check.validate(cfg)
    assert any("sink_type must be 'executor'" in e for e in errors)


def test_live_account_id_required():
    cfg = _live_config()
    cfg["tradier_live"]["account_id"] = ""
    errors = preflight_check.validate(cfg)
    assert any("account_id must be set" in e for e in errors)


def test_live_account_type_must_be_live():
    cfg = _live_config()
    cfg["tradier_live"]["account_type"] = "paper"
    errors = preflight_check.validate(cfg)
    assert any("account_type must be 'live'" in e for e in errors)


def test_live_enabled_must_be_true():
    cfg = _live_config()
    cfg["tradier_live"]["enabled"] = False
    errors = preflight_check.validate(cfg)
    assert any("tradier_live.enabled must be true" in e for e in errors)


def test_live_max_contracts_must_match_approved_cap():
    cfg = _live_config()
    cfg["risk"]["max_contracts"] = 5
    errors = preflight_check.validate(cfg)
    assert any("max_contracts must be 30" in e for e in errors)


def test_live_max_contracts_missing_fails():
    cfg = _live_config()
    cfg["risk"].pop("max_contracts")
    errors = preflight_check.validate(cfg)
    assert any("max_contracts must be 30" in e for e in errors)


# ---------------------------------------------------------------------------
# Integration: shipped configs validate as expected
# ---------------------------------------------------------------------------

def _load_shipped(path):
    import yaml
    with open(ROOT / path) as f:
        return yaml.safe_load(f)


def test_shipped_live_exp800_tradier_passes():
    cfg = _load_shipped("configs/live_exp800_tradier.yaml")
    assert preflight_check.validate(cfg) == []


def test_shipped_paper_exp800_passes():
    """EXP-800 paper config (otm_pct-based) — previously blocked by the latent
    delta-fields bug, should now validate cleanly."""
    cfg = _load_shipped("configs/paper_exp800.yaml")
    assert preflight_check.validate(cfg) == []
