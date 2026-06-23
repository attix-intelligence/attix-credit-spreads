#!/usr/bin/env python3
"""Preflight config validator — exits 1 on any missing required field.

Usage:
    python scripts/preflight_check.py configs/paper_champion.yaml
    python scripts/preflight_check.py configs/paper_exp401.yaml
    python scripts/preflight_check.py configs/live_expv8a_tradier.yaml

Mode dispatch:
    - paper_mode: true  → standard paper safety check (unchanged).
    - paper_mode: false → live config; requires a fully-formed `tradier_live`
      routing block (sink_type=executor, account_id set, account_type=live,
      enabled=true) AND risk.max_contracts==1 (Phase 1 cap). A live config
      missing any of these fails preflight.
    - paper_mode unset / non-bool → fails (safety check, unchanged).
"""

import sys
from pathlib import Path

import yaml


def _validate_live_routing(config: dict) -> list:
    """Return error strings for a live config. Empty list = ok."""
    errors = []
    tradier = config.get("tradier_live")
    if not isinstance(tradier, dict):
        errors.append(
            "paper_mode is false but no 'tradier_live' routing section present"
        )
        return errors

    if tradier.get("enabled") is not True:
        errors.append("tradier_live.enabled must be true for a live config")
    if tradier.get("sink_type") != "executor":
        errors.append(
            f"tradier_live.sink_type must be 'executor' (got {tradier.get('sink_type')!r})"
        )
    if not tradier.get("account_id"):
        errors.append(
            "tradier_live.account_id must be set (e.g. 'tradier_6YA42569')"
        )
    if tradier.get("account_type") != "live":
        errors.append(
            f"tradier_live.account_type must be 'live' (got {tradier.get('account_type')!r})"
        )

    risk = config.get("risk")
    cap = risk.get("max_contracts") if isinstance(risk, dict) else None
    if cap != 1:
        errors.append(
            f"risk.max_contracts must be 1 for Phase 1 LIVE cap (got {cap!r})"
        )

    return errors


def validate(config: dict) -> list:
    """Return list of error strings. Empty list means all checks passed."""
    errors = []

    # Top-level required fields
    if not config.get("db_path"):
        errors.append("Missing required field: db_path")

    if not config.get("experiment_id"):
        errors.append("Missing required field: experiment_id")

    # Mode dispatch
    paper_mode = config.get("paper_mode")
    if paper_mode is True:
        pass  # paper happy-path — unchanged
    elif paper_mode is False:
        errors.extend(_validate_live_routing(config))
    else:
        errors.append("paper_mode must be true (safety check)")

    # Logging section
    logging_cfg = config.get("logging")
    if not isinstance(logging_cfg, dict):
        errors.append("Missing required section: logging")
    else:
        if not logging_cfg.get("level"):
            errors.append("logging.level is required")
        if not logging_cfg.get("file"):
            errors.append("logging.file is required")

    # Strategy section
    strategy = config.get("strategy")
    if not isinstance(strategy, dict):
        errors.append("Missing required section: strategy")
    else:
        # min_delta/max_delta only meaningful when delta-based strike selection
        # is enabled. EXP-800-family configs use otm_pct and explicitly disable
        # delta selection — requiring those fields was a latent bug.
        if strategy.get("use_delta_selection", True):
            if "min_delta" not in strategy:
                errors.append("strategy.min_delta is required")
            if "max_delta" not in strategy:
                errors.append("strategy.max_delta is required")

    # Risk section
    risk = config.get("risk")
    if not isinstance(risk, dict):
        errors.append("Missing required section: risk")
    else:
        # Validate regime scales if present (EXP-401 blend)
        if "regime_scale_crash" in risk and risk.get("regime_scale_crash") != 0:
            errors.append(
                "risk.regime_scale_crash should be 0 (no trading during crash regime)"
            )

    # Straddle/strangle config validation (optional section)
    ss_config = strategy.get("straddle_strangle") if isinstance(strategy, dict) else None
    if ss_config and isinstance(ss_config, dict) and ss_config.get("enabled"):
        if "profit_target_pct" not in ss_config:
            errors.append("strategy.straddle_strangle.profit_target_pct is required when enabled")
        if "stop_loss_pct" not in ss_config:
            errors.append("strategy.straddle_strangle.stop_loss_pct is required when enabled")
        if "max_risk_pct" not in ss_config:
            errors.append("strategy.straddle_strangle.max_risk_pct is required when enabled")
        if isinstance(risk, dict) and "straddle_strangle_risk_pct" not in risk:
            errors.append("risk.straddle_strangle_risk_pct is required when straddle_strangle is enabled")

    return errors


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"FAIL: config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    errors = validate(config)
    if errors:
        print(f"PREFLIGHT FAILED for {config_path}:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"PREFLIGHT OK: {config_path}")


if __name__ == "__main__":
    main()
