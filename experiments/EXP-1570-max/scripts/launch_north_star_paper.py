#!/usr/bin/env python3
"""Launch the North Star portfolio paper trading session (EXP-1570).

Reads paper_north_star.yaml, validates pre-flight checks, and starts
the paper trading loop via main.py scheduler.

Usage:
    python experiments/EXP-1570-max/scripts/launch_north_star_paper.py
    python experiments/EXP-1570-max/scripts/launch_north_star_paper.py --dry-run
    python experiments/EXP-1570-max/scripts/launch_north_star_paper.py --check-only
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Resolve project root (three levels up from this script)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = Path(__file__).resolve().parent.parent / "paper_north_star.yaml"
ENV_FILE = PROJECT_ROOT / ".env.north_star"

logger = logging.getLogger("north_star_launcher")


# ── Config Loading ──────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    """Load and return the YAML config."""
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


# ── Pre-Flight Checks ──────────────────────────────────────────────────────

class PreFlightResult:
    """Result of a single pre-flight check."""

    def __init__(self, name: str, passed: bool, message: str, required: bool = True):
        self.name = name
        self.passed = passed
        self.message = message
        self.required = required

    def __repr__(self):
        status = "PASS" if self.passed else ("FAIL" if self.required else "WARN")
        return f"[{status}] {self.name}: {self.message}"


def check_paper_mode(config: dict) -> PreFlightResult:
    """Verify paper_mode is explicitly True."""
    paper = config.get("paper_mode", False)
    return PreFlightResult(
        "paper_mode",
        paper is True,
        "paper_mode=True" if paper else "DANGER: paper_mode is not True!",
    )


def check_alpaca_config(config: dict) -> PreFlightResult:
    """Verify Alpaca paper endpoint is configured."""
    alpaca = config.get("alpaca", {})
    is_paper = alpaca.get("paper", False)
    url = alpaca.get("base_url", "")
    ok = is_paper and "paper" in url
    return PreFlightResult(
        "alpaca_paper_endpoint",
        ok,
        f"paper={is_paper}, url={url}",
    )


def check_env_vars(config: dict) -> PreFlightResult:
    """Verify required environment variables are set."""
    required = ["ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY"]
    missing = [v for v in required if not os.environ.get(v)]
    return PreFlightResult(
        "env_vars",
        len(missing) == 0,
        f"Missing: {', '.join(missing)}" if missing else "All required env vars set",
    )


def check_portfolio_weights(config: dict) -> PreFlightResult:
    """Verify portfolio weights sum to ~1.0."""
    portfolio = config.get("portfolio", {})
    strategies = portfolio.get("strategies", [])
    if not strategies:
        return PreFlightResult("portfolio_weights", False, "No strategies defined")
    total = sum(s.get("weight", 0) for s in strategies)
    ok = abs(total - 1.0) < 0.01
    return PreFlightResult(
        "portfolio_weights",
        ok,
        f"Sum={total:.3f} ({'OK' if ok else 'weights must sum to 1.0'})",
    )


def check_leverage_target(config: dict) -> PreFlightResult:
    """Verify leverage target is within safe bounds."""
    leverage = config.get("portfolio", {}).get("leverage_target", 0)
    ok = 0 < leverage <= 5.0
    return PreFlightResult(
        "leverage_target",
        ok,
        f"leverage={leverage}x ({'OK' if ok else 'must be 0 < lev <= 5.0'})",
    )


def check_circuit_breakers(config: dict) -> PreFlightResult:
    """Verify circuit breakers are configured."""
    cb = config.get("circuit_breakers", {})
    checks = [
        cb.get("max_drawdown_pct") is not None,
        cb.get("daily_loss_limit_pct") is not None,
        cb.get("correlation_spike", {}).get("enabled", False),
    ]
    passed = all(checks)
    return PreFlightResult(
        "circuit_breakers",
        passed,
        f"max_dd={cb.get('max_drawdown_pct')}%, daily_loss={cb.get('daily_loss_limit_pct')}%, "
        f"corr_spike={'on' if cb.get('correlation_spike', {}).get('enabled') else 'off'}",
    )


def check_strategy_count(config: dict) -> PreFlightResult:
    """Verify expected number of strategies."""
    strategies = config.get("portfolio", {}).get("strategies", [])
    ok = len(strategies) == 4
    return PreFlightResult(
        "strategy_count",
        ok,
        f"{len(strategies)} strategies (expected 4)",
    )


def check_db_path(config: dict) -> PreFlightResult:
    """Verify db_path parent directory exists."""
    db_path = Path(PROJECT_ROOT / config.get("db_path", ""))
    parent_exists = db_path.parent.exists()
    return PreFlightResult(
        "db_path",
        parent_exists,
        f"{db_path} (parent {'exists' if parent_exists else 'MISSING'})",
    )


def check_data_cache(config: dict) -> PreFlightResult:
    """Verify data cache directory exists."""
    cache_dir = Path(PROJECT_ROOT / config.get("data", {}).get("cache_dir", ""))
    exists = cache_dir.exists()
    return PreFlightResult(
        "data_cache",
        exists,
        f"{cache_dir} ({'exists' if exists else 'MISSING'})",
        required=False,
    )


def check_rebalance_config(config: dict) -> PreFlightResult:
    """Verify rebalance schedule is set."""
    rebalance = config.get("rebalance", {})
    freq = rebalance.get("frequency")
    day = rebalance.get("day_of_week")
    ok = freq is not None and day is not None
    return PreFlightResult(
        "rebalance_schedule",
        ok,
        f"frequency={freq}, day={day}",
    )


def check_drawdown_consistency(config: dict) -> PreFlightResult:
    """Verify circuit breaker DD matches risk DD."""
    cb_dd = config.get("circuit_breakers", {}).get("max_drawdown_pct")
    risk_dd = config.get("risk", {}).get("drawdown_cb_pct")
    ok = cb_dd is not None and risk_dd is not None and cb_dd == risk_dd
    return PreFlightResult(
        "drawdown_consistency",
        ok,
        f"circuit_breaker={cb_dd}%, risk={risk_dd}% ({'match' if ok else 'MISMATCH'})",
    )


ALL_CHECKS = [
    check_paper_mode,
    check_alpaca_config,
    check_env_vars,
    check_portfolio_weights,
    check_leverage_target,
    check_circuit_breakers,
    check_strategy_count,
    check_db_path,
    check_data_cache,
    check_rebalance_config,
    check_drawdown_consistency,
]


def run_preflight(config: dict) -> list[PreFlightResult]:
    """Run all pre-flight checks and return results."""
    return [check(config) for check in ALL_CHECKS]


def preflight_passed(results: list[PreFlightResult]) -> bool:
    """Return True if all required checks passed."""
    return all(r.passed for r in results if r.required)


# ── Paper Trading Loop ──────────────────────────────────────────────────────

def start_paper_trading(config: dict, dry_run: bool = False) -> int:
    """Start the paper trading scheduler via main.py.

    Returns the subprocess exit code.
    """
    config_path = str(CONFIG_PATH)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "main.py"),
        "scheduler",
        "--config", config_path,
    ]

    # Add env file if it exists
    if ENV_FILE.exists():
        cmd.extend(["--env-file", str(ENV_FILE)])

    if dry_run:
        logger.info("DRY RUN — would execute: %s", " ".join(cmd))
        return 0

    logger.info("Starting North Star paper trading: %s", " ".join(cmd))
    logger.info("Experiment: %s (parent: %s)",
                config.get("experiment_id"), config.get("parent_experiment"))
    logger.info("Leverage: %sx, Strategies: %d",
                config.get("portfolio", {}).get("leverage_target"),
                len(config.get("portfolio", {}).get("strategies", [])))

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch North Star (EXP-1570) paper trading session",
    )
    parser.add_argument(
        "--config", type=Path, default=CONFIG_PATH,
        help="Path to config YAML (default: paper_north_star.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run preflight checks and print launch command, but don't start",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Run preflight checks only, don't launch",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load config
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    # Run preflight
    logger.info("=" * 60)
    logger.info("North Star Paper Trading — Pre-Flight Checks")
    logger.info("=" * 60)

    results = run_preflight(config)
    for r in results:
        logger.info("  %s", r)

    passed = preflight_passed(results)
    required_total = sum(1 for r in results if r.required)
    required_passed = sum(1 for r in results if r.required and r.passed)
    logger.info("-" * 60)
    logger.info("Result: %d/%d required checks passed", required_passed, required_total)

    if not passed:
        failed = [r for r in results if r.required and not r.passed]
        logger.error("PREFLIGHT FAILED — %d required check(s) did not pass:", len(failed))
        for r in failed:
            logger.error("  %s", r)
        return 1

    if args.check_only:
        logger.info("All preflight checks passed. (--check-only, not launching)")
        return 0

    # Launch
    logger.info("=" * 60)
    logger.info("Launching paper trading...")
    logger.info("=" * 60)

    return start_paper_trading(config, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
