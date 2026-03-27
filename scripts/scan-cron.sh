#!/bin/bash
# Credit Spread Scanner — Cron Runner
# Called by crontab at scheduled market hours (ET, weekdays only).
#
# IMPORTANT: scan-cron.sh handles ONLY EXP-700 (ML-filtered, one-shot scanner).
#
# EXP-400, EXP-401, EXP-503, EXP-600 are managed exclusively by their
# LaunchAgent persistent schedulers (~/Library/LaunchAgents/com.pilotai.exp*.plist).
# Running scan-cron for those experiments while LaunchAgents are active causes
# double-execution: orphan positions, split-brain DBs, and risk-gate lockout.
# See: research/double-execution-investigation.md (2026-03-27)

set -euo pipefail

PROJECT_DIR="/Users/charlesbot/projects/pilotai-credit-spreads"
LOG_DIR="${PROJECT_DIR}/logs"
MAX_LOG_SIZE=$((5 * 1024 * 1024))  # 5 MB

mkdir -p "$LOG_DIR"

# Skip weekends (extra safety — cron schedule is Mon-Fri but TZ edge cases exist)
DOW=$(TZ=America/New_York date +%u)  # 1=Mon, 7=Sun
if [ "$DOW" -gt 5 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Skipping scan — weekend (day=$DOW)"
  exit 0
fi

cd "$PROJECT_DIR"

# EXP-700: ML-filtered champion (custom scanner)
_run_ml_scan() {
  local LOG_FILE="${LOG_DIR}/scan-cron-exp700.log"
  if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.1"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting exp700 ML scan (ET: $(TZ=America/New_York date '+%H:%M %Z'))" >> "$LOG_FILE"
  /usr/bin/python3 scripts/exp700_ml_scanner.py --config configs/paper_exp700.yaml --env-file .env.exp700 >> "$LOG_FILE" 2>&1
  local RC=$?
  [ $RC -eq 0 ] && echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] exp700 ML scan completed successfully" >> "$LOG_FILE" || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] exp700 ML scan failed with exit code $RC" >> "$LOG_FILE"
  echo "---" >> "$LOG_FILE"
}
_run_ml_scan
