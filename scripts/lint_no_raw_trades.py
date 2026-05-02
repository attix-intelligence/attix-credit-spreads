#!/usr/bin/env python3
"""CI guardrail: forbid raw `FROM trades` SELECTs in metric/gate code paths.

Background
----------
Twice now (EXP-1220 backfill, the 2026-05-02 systemic ``closed_pre_reset`` audit)
non-real rows have leaked into Gate metric calculations because each call site
implemented its own ad-hoc filter on the ``trades`` table. The fix
(``metrics/eligible_trades.py``) provides ``metrics_eligible_cte`` and
``open_eligible_cte`` as the single source of truth.

This script enforces the rule. It scans Python sources under ``CHECKED_DIRS`` and
fails with non-zero exit if any line matches ``FROM\\s+trades`` (case-insensitive)
without an explicit allow-list entry.

Allow mechanism
---------------
Three ways a line is accepted:

1. The file path is in ``ALLOWED_FILES`` (the helper module itself, this lint
   script, the migration script, and tests).
2. The line — or any of the 5 lines immediately preceding it — carries the
   marker ``# noqa: raw-trades`` (or ``# noqa: raw-trades — <reason>``). The
   look-back window lets the marker live as a Python comment above multi-line
   SQL strings. Use only for intentionally-raw operational/lifecycle queries
   (e.g. orphan detection that needs to see ``unmanaged`` rows). Always
   document the reason inline.
3. The match is ``UPDATE trades`` / ``INSERT INTO trades`` / ``DELETE FROM trades``
   — those are write paths, not metric reads. (We only flag ``FROM trades``.)

Run:
    python scripts/lint_no_raw_trades.py            # check whole tree
    python scripts/lint_no_raw_trades.py path/file  # check specific file(s)

Wire into CI / Makefile so violations fail the build.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directories whose .py files must go through the helper.
CHECKED_DIRS = (
    "sentinel",
    "metrics",
    "engine",
    "reporting",
    "alerts",
    "gates",  # placeholder if/when split out
)

# Files exempt from the rule (raw access is intentional and safe).
ALLOWED_FILES = {
    # The helper itself defines the CTE that wraps `FROM trades`.
    PROJECT_ROOT / "metrics" / "eligible_trades.py",
    # This script greps source for the pattern; mentions it in strings.
    PROJECT_ROOT / "scripts" / "lint_no_raw_trades.py",
    # Migration script must touch the table directly.
    PROJECT_ROOT / "scripts" / "migrate_excluded_from_metrics.py",
}

# Tests are allowed because they assert behaviour against fixture DBs.
ALLOWED_DIR_PREFIXES = (
    PROJECT_ROOT / "tests",
)

# The forbidden pattern. Case-sensitive uppercase `FROM` — every SQL query in
# the codebase uses uppercase keywords; lowercase `from trades table` shows up
# in prose comments and is not a SQL access. Word-boundary on `trades` avoids
# hitting `trade_legs`, `trades_external`, etc.
PATTERN = re.compile(r"\bFROM\s+trades\b")

# Inline allow marker. Anything after the marker is ignored (treat as comment).
NOQA_MARKER = re.compile(r"#\s*noqa:\s*raw-trades\b", re.IGNORECASE)

# How many preceding lines are scanned for a noqa marker.
# Lets the marker live as a Python comment above a multi-line SQL string.
# 8 lines covers a typical "comment block + SELECT-list" stretch above FROM.
NOQA_LOOKBACK = 8


def is_allowed(path: Path) -> bool:
    if path in ALLOWED_FILES:
        return True
    for prefix in ALLOWED_DIR_PREFIXES:
        try:
            path.relative_to(prefix)
            return True
        except ValueError:
            continue
    return False


def iter_targets(roots: list[Path]) -> list[Path]:
    """Yield .py files under each root."""
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            out.append(root)
        else:
            out.extend(sorted(root.rglob("*.py")))
    return out


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, line) violations for a single file."""
    violations: list[tuple[int, str]] = []
    if is_allowed(path):
        return violations
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return violations

    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if not PATTERN.search(line):
            continue
        # Same-line marker, or any of the previous NOQA_LOOKBACK lines.
        window_start = max(0, idx - NOQA_LOOKBACK)
        window = lines[window_start : idx + 1]
        if any(NOQA_MARKER.search(w) for w in window):
            continue
        violations.append((idx + 1, line.rstrip()))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="*",
        help="Specific files/dirs to check. If empty, checks all CHECKED_DIRS under project root.",
    )
    args = parser.parse_args(argv)

    if args.paths:
        roots = [Path(p).resolve() for p in args.paths]
    else:
        roots = [PROJECT_ROOT / d for d in CHECKED_DIRS]

    targets = iter_targets(roots)
    n_violations = 0
    for path in targets:
        violations = check_file(path)
        for lineno, line in violations:
            rel = path.relative_to(PROJECT_ROOT) if path.is_absolute() else path
            print(f"{rel}:{lineno}: raw `FROM trades` not allowed: {line.strip()}")
            n_violations += 1

    if n_violations == 0:
        print(f"OK — no raw `FROM trades` violations across {len(targets)} files.")
        return 0

    print(
        f"\nFAIL — {n_violations} violation(s).\n"
        "Fix by switching to metrics_eligible_cte() / open_eligible_cte(), or, for\n"
        "intentionally-raw operational queries, add an inline `# noqa: raw-trades`\n"
        "comment with a one-line reason. See docs/metrics_data_pipeline.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
