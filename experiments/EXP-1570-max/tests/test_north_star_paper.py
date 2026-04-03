"""Tests for EXP-1570 North Star paper trading config and launcher."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Paths
EXP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = EXP_DIR / "paper_north_star.yaml"
SCRIPTS_DIR = EXP_DIR / "scripts"

# Import launcher module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "launch_north_star_paper",
    SCRIPTS_DIR / "launch_north_star_paper.py",
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Load the actual paper_north_star.yaml config."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture
def config_path(tmp_path, config):
    """Write config to a temp file and return the path."""
    path = tmp_path / "paper_north_star.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


# ── Config Structure Tests ──────────────────────────────────────────────────

class TestConfigStructure:
    """Validate the YAML config file structure and values."""

    def test_config_loads(self, config):
        assert config is not None
        assert isinstance(config, dict)

    def test_paper_mode_enabled(self, config):
        assert config["paper_mode"] is True

    def test_experiment_id(self, config):
        assert config["experiment_id"] == "EXP-1570"

    def test_parent_experiment(self, config):
        assert config["parent_experiment"] == "EXP-1470"

    def test_created_by(self, config):
        assert config["created_by"] == "maximus"


class TestPortfolioWeights:
    """Validate the 4-strategy portfolio weights."""

    def test_four_strategies(self, config):
        strategies = config["portfolio"]["strategies"]
        assert len(strategies) == 4

    def test_weights_sum_to_one(self, config):
        strategies = config["portfolio"]["strategies"]
        total = sum(s["weight"] for s in strategies)
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected 1.0"

    def test_ml_cs_860_weight(self, config):
        strategies = config["portfolio"]["strategies"]
        ml_cs = next(s for s in strategies if s["name"] == "ML-CS-860")
        assert ml_cs["weight"] == 0.405
        assert ml_cs["source_experiment"] == "EXP-860"

    def test_regime_leverage_weight(self, config):
        strategies = config["portfolio"]["strategies"]
        regime = next(s for s in strategies if s["name"] == "Regime-Leverage")
        assert regime["weight"] == 0.209
        assert regime["source_experiment"] == "EXP-840"

    def test_intraday_meanrev_weight(self, config):
        strategies = config["portfolio"]["strategies"]
        intraday = next(s for s in strategies if s["name"] == "Intraday-MeanRev")
        assert intraday["weight"] == 0.205
        assert intraday["source_experiment"] == "EXP-1000"

    def test_combined_cs_vol_weight(self, config):
        strategies = config["portfolio"]["strategies"]
        combined = next(s for s in strategies if s["name"] == "Combined-CS-Vol")
        assert combined["weight"] == 0.181
        assert combined["source_experiment"] == "EXP-750"

    def test_leverage_target(self, config):
        assert config["portfolio"]["leverage_target"] == 3.6


class TestCircuitBreakers:
    """Validate circuit breaker configuration."""

    def test_max_drawdown(self, config):
        assert config["circuit_breakers"]["max_drawdown_pct"] == 12.0

    def test_daily_loss_limit(self, config):
        assert config["circuit_breakers"]["daily_loss_limit_pct"] == 3.0

    def test_correlation_spike_enabled(self, config):
        cs = config["circuit_breakers"]["correlation_spike"]
        assert cs["enabled"] is True
        assert cs["threshold"] == 0.80
        assert cs["lookback_days"] == 20

    def test_vix_halt_threshold(self, config):
        assert config["circuit_breakers"]["vix_halt_threshold"] == 35.0

    def test_per_strategy_dd_limit(self, config):
        assert config["circuit_breakers"]["per_strategy_max_dd_pct"] == 8.0


class TestRebalanceSchedule:
    """Validate rebalance configuration."""

    def test_weekly_frequency(self, config):
        assert config["rebalance"]["frequency"] == "weekly"

    def test_monday_rebalance(self, config):
        assert config["rebalance"]["day_of_week"] == "Monday"

    def test_drift_threshold(self, config):
        assert config["rebalance"]["drift_threshold_pct"] == 5.0

    def test_timezone(self, config):
        assert config["rebalance"]["timezone"] == "America/New_York"


class TestAlpacaConfig:
    """Validate Alpaca paper trading configuration."""

    def test_alpaca_enabled(self, config):
        assert config["alpaca"]["enabled"] is True

    def test_alpaca_paper_mode(self, config):
        assert config["alpaca"]["paper"] is True

    def test_alpaca_paper_url(self, config):
        assert "paper" in config["alpaca"]["base_url"]
        assert config["alpaca"]["base_url"] == "https://paper-api.alpaca.markets"

    def test_alpaca_uses_env_vars(self, config):
        assert config["alpaca"]["api_key"] == "${ALPACA_API_KEY}"
        assert config["alpaca"]["api_secret"] == "${ALPACA_API_SECRET}"


class TestRiskManagement:
    """Validate risk management settings."""

    def test_account_size(self, config):
        assert config["risk"]["account_size"] == 100000

    def test_drawdown_matches_circuit_breaker(self, config):
        assert config["risk"]["drawdown_cb_pct"] == config["circuit_breakers"]["max_drawdown_pct"]

    def test_max_positions(self, config):
        assert config["risk"]["max_positions"] == 20

    def test_sizing_mode(self, config):
        assert config["risk"]["sizing_mode"] == "proportional"


# ── Pre-Flight Check Tests ──────────────────────────────────────────────────

class TestPreFlightChecks:
    """Test individual pre-flight check functions."""

    def test_check_paper_mode_pass(self, config):
        result = launcher.check_paper_mode(config)
        assert result.passed is True

    def test_check_paper_mode_fail(self):
        result = launcher.check_paper_mode({"paper_mode": False})
        assert result.passed is False

    def test_check_alpaca_config_pass(self, config):
        result = launcher.check_alpaca_config(config)
        assert result.passed is True

    def test_check_alpaca_config_fail_live(self):
        cfg = {"alpaca": {"paper": False, "base_url": "https://api.alpaca.markets"}}
        result = launcher.check_alpaca_config(cfg)
        assert result.passed is False

    def test_check_portfolio_weights_pass(self, config):
        result = launcher.check_portfolio_weights(config)
        assert result.passed is True

    def test_check_portfolio_weights_fail(self):
        cfg = {"portfolio": {"strategies": [
            {"weight": 0.5}, {"weight": 0.3},
        ]}}
        result = launcher.check_portfolio_weights(cfg)
        assert result.passed is False

    def test_check_leverage_target_pass(self, config):
        result = launcher.check_leverage_target(config)
        assert result.passed is True

    def test_check_leverage_target_too_high(self):
        cfg = {"portfolio": {"leverage_target": 10.0}}
        result = launcher.check_leverage_target(cfg)
        assert result.passed is False

    def test_check_circuit_breakers_pass(self, config):
        result = launcher.check_circuit_breakers(config)
        assert result.passed is True

    def test_check_strategy_count_pass(self, config):
        result = launcher.check_strategy_count(config)
        assert result.passed is True

    def test_check_strategy_count_wrong(self):
        cfg = {"portfolio": {"strategies": [{"weight": 0.5}, {"weight": 0.5}]}}
        result = launcher.check_strategy_count(cfg)
        assert result.passed is False

    def test_check_rebalance_config_pass(self, config):
        result = launcher.check_rebalance_config(config)
        assert result.passed is True

    def test_check_drawdown_consistency_pass(self, config):
        result = launcher.check_drawdown_consistency(config)
        assert result.passed is True

    def test_check_drawdown_consistency_mismatch(self):
        cfg = {
            "circuit_breakers": {"max_drawdown_pct": 12.0},
            "risk": {"drawdown_cb_pct": 15.0},
        }
        result = launcher.check_drawdown_consistency(cfg)
        assert result.passed is False

    @patch.dict(os.environ, {
        "ALPACA_API_KEY": "test",
        "ALPACA_API_SECRET": "test",
        "POLYGON_API_KEY": "test",
    })
    def test_check_env_vars_pass(self):
        result = launcher.check_env_vars({})
        assert result.passed is True

    @patch.dict(os.environ, {}, clear=True)
    def test_check_env_vars_missing(self):
        result = launcher.check_env_vars({})
        assert result.passed is False
        assert "ALPACA_API_KEY" in result.message


class TestPreFlightRunner:
    """Test the preflight runner and pass/fail logic."""

    def test_run_preflight_returns_results(self, config):
        # Patch PROJECT_ROOT so filesystem checks pass in test env
        with patch.object(launcher, "PROJECT_ROOT", Path(os.getcwd())):
            results = launcher.run_preflight(config)
        assert len(results) == len(launcher.ALL_CHECKS)

    def test_preflight_result_repr(self):
        r = launcher.PreFlightResult("test", True, "all good")
        assert "[PASS]" in repr(r)

        r = launcher.PreFlightResult("test", False, "broken")
        assert "[FAIL]" in repr(r)

        r = launcher.PreFlightResult("test", False, "optional", required=False)
        assert "[WARN]" in repr(r)

    def test_preflight_passed_all_required(self):
        results = [
            launcher.PreFlightResult("a", True, "ok"),
            launcher.PreFlightResult("b", True, "ok"),
            launcher.PreFlightResult("c", False, "skip", required=False),
        ]
        assert launcher.preflight_passed(results) is True

    def test_preflight_failed_required(self):
        results = [
            launcher.PreFlightResult("a", True, "ok"),
            launcher.PreFlightResult("b", False, "broken", required=True),
        ]
        assert launcher.preflight_passed(results) is False


# ── Launcher Integration Tests ──────────────────────────────────────────────

class TestLauncherMain:
    """Test the main() entry point."""

    def test_check_only_mode(self, config_path):
        """--check-only should return 0 if preflight passes (env vars may fail)."""
        with patch.dict(os.environ, {
            "ALPACA_API_KEY": "test",
            "ALPACA_API_SECRET": "test",
            "POLYGON_API_KEY": "test",
        }), patch.object(launcher, "PROJECT_ROOT", Path(os.getcwd())):
            exit_code = launcher.main([
                "--config", str(config_path),
                "--check-only",
            ])
            assert exit_code == 0

    def test_dry_run_mode(self, config_path):
        """--dry-run should pass preflight and print command without executing."""
        with patch.dict(os.environ, {
            "ALPACA_API_KEY": "test",
            "ALPACA_API_SECRET": "test",
            "POLYGON_API_KEY": "test",
        }), patch.object(launcher, "PROJECT_ROOT", Path(os.getcwd())):
            exit_code = launcher.main([
                "--config", str(config_path),
                "--dry-run",
            ])
            assert exit_code == 0

    def test_missing_config_file(self):
        exit_code = launcher.main(["--config", "/nonexistent/config.yaml", "--check-only"])
        assert exit_code == 1

    def test_preflight_failure_blocks_launch(self):
        """If preflight fails, main should return 1 without launching."""
        bad_config = {
            "paper_mode": False,
            "alpaca": {},
            "portfolio": {"strategies": [], "leverage_target": 0},
            "circuit_breakers": {},
            "risk": {},
            "rebalance": {},
            "data": {},
        }
        with patch.object(launcher, "load_config", return_value=bad_config), \
             patch.object(launcher, "PROJECT_ROOT", Path(os.getcwd())):
            exit_code = launcher.main(["--check-only"])
            assert exit_code == 1


class TestStartPaperTrading:
    """Test the paper trading launcher function."""

    def test_dry_run_returns_zero(self, config):
        assert launcher.start_paper_trading(config, dry_run=True) == 0

    @patch("subprocess.run")
    def test_launches_main_scheduler(self, mock_run, config):
        mock_run.return_value = MagicMock(returncode=0)
        result = launcher.start_paper_trading(config, dry_run=False)
        assert result == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "main.py" in cmd[1]
        assert "scheduler" in cmd
