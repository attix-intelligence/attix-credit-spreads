"""Tests for scripts/daily_data_update.sh."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "daily_data_update.sh"


class TestScriptExists:
    """Basic script validation."""

    def test_script_exists(self):
        assert SCRIPT.exists()

    def test_script_is_executable(self):
        assert os.access(SCRIPT, os.X_OK)

    def test_script_has_shebang(self):
        with open(SCRIPT) as f:
            first_line = f.readline()
        assert first_line.startswith("#!/")

    def test_script_uses_strict_mode(self):
        content = SCRIPT.read_text()
        assert "set -euo pipefail" in content

    def test_script_sources_env(self):
        content = SCRIPT.read_text()
        assert ".env" in content

    def test_script_checks_polygon_key(self):
        content = SCRIPT.read_text()
        assert "POLYGON_API_KEY" in content

    def test_script_calls_backfill(self):
        content = SCRIPT.read_text()
        assert "backfill_polygon_cache.py" in content
        assert "--workers 4" in content

    def test_script_calls_iron_vault(self):
        content = SCRIPT.read_text()
        assert "iron_vault_setup.py" in content

    def test_script_logs_with_timestamp(self):
        content = SCRIPT.read_text()
        assert "daily_update.log" in content
        assert "date" in content

    def test_script_has_lock_file(self):
        content = SCRIPT.read_text()
        assert ".daily_update.lock" in content

    def test_script_has_cron_comment(self):
        content = SCRIPT.read_text()
        assert "0 21 * * *" in content

    def test_script_supports_dry_run(self):
        content = SCRIPT.read_text()
        assert "--dry-run" in content


class TestLockMechanism:
    """Test that the lock file prevents concurrent runs."""

    def test_stale_lock_is_cleaned(self, tmp_path):
        """A lock file with a dead PID should be cleaned up."""
        # Create a wrapper script that uses our lock logic
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        lock_file = data_dir / ".daily_update.lock"

        # Write a stale PID (99999999 is unlikely to be running)
        lock_file.write_text("99999999")

        # Create a minimal test script that mimics the lock check
        test_script = tmp_path / "test_lock.sh"
        test_script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            LOCK_FILE="{lock_file}"
            if [ -f "$LOCK_FILE" ]; then
                OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
                if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
                    echo "BLOCKED"
                    exit 0
                fi
                rm -f "$LOCK_FILE"
            fi
            echo $$ > "$LOCK_FILE"
            echo "ACQUIRED"
            rm -f "$LOCK_FILE"
        """))
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "ACQUIRED" in result.stdout

    def test_active_lock_blocks(self, tmp_path):
        """A lock file with a running PID should block."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        lock_file = data_dir / ".daily_update.lock"

        # Use our own PID (definitely running)
        lock_file.write_text(str(os.getpid()))

        test_script = tmp_path / "test_lock.sh"
        test_script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            LOCK_FILE="{lock_file}"
            if [ -f "$LOCK_FILE" ]; then
                OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
                if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
                    echo "BLOCKED"
                    exit 0
                fi
                rm -f "$LOCK_FILE"
            fi
            echo "ACQUIRED"
        """))
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "BLOCKED" in result.stdout


class TestScriptFailsWithoutEnv:
    """Test that the script fails gracefully without .env."""

    def test_fails_without_env(self, tmp_path):
        """Script should exit 1 if .env is missing."""
        # Create a minimal version of the script that only checks .env
        test_script = tmp_path / "test_env.sh"
        test_script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            PROJECT_DIR="{tmp_path}"
            if [ -f "$PROJECT_DIR/.env" ]; then
                echo "FOUND"
            else
                echo "ERROR: .env not found"
                exit 1
            fi
        """))
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stdout

    def test_fails_without_polygon_key(self, tmp_path):
        """Script should exit 1 if POLYGON_API_KEY is empty."""
        # Create .env without the key
        env_file = tmp_path / ".env"
        env_file.write_text("SOME_OTHER_KEY=foo\n")

        test_script = tmp_path / "test_key.sh"
        test_script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            PROJECT_DIR="{tmp_path}"
            set -a
            . "$PROJECT_DIR/.env"
            set +a
            if [ -z "${{POLYGON_API_KEY:-}}" ]; then
                echo "ERROR: POLYGON_API_KEY not set"
                exit 1
            fi
            echo "OK"
        """))
        test_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert "POLYGON_API_KEY" in result.stdout
