#!/usr/bin/env bash
# ============================================================================
# daily_data_update.sh — Daily SPY Options Data Update
# ============================================================================
#
# Fetches new SPY options data from Polygon and validates the cache DB.
# Designed to be idempotent and safe to run via cron.
#
# Steps:
#   1. Source .env for POLYGON_API_KEY
#   2. Acquire lock to prevent concurrent runs
#   3. Run backfill_polygon_cache.py to fetch new data
#   4. Run iron_vault_setup.py to validate the DB
#   5. Log all output with timestamps to data/daily_update.log
#
# Crontab entry (9 PM UTC daily, after US market close):
#   0 21 * * * /path/to/pilotai-credit-spreads/scripts/daily_data_update.sh
#
# Usage:
#   ./scripts/daily_data_update.sh
#   ./scripts/daily_data_update.sh --dry-run
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCK_FILE="$PROJECT_DIR/data/.daily_update.lock"
LOG_FILE="$PROJECT_DIR/data/daily_update.log"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# ── Logging ────────────────────────────────────────────────────────────────

log() {
    local msg="[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

# ── Lock (idempotency) ────────────────────────────────────────────────────

cleanup() {
    rm -f "$LOCK_FILE"
}

if [ -f "$LOCK_FILE" ]; then
    # Check if the PID in the lock file is still running
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Another daily_data_update is already running (PID $OLD_PID). Exiting."
        exit 0
    fi
    # Stale lock — remove it
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap cleanup EXIT

# ── Setup ──────────────────────────────────────────────────────────────────

cd "$PROJECT_DIR"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log "=========================================="
log "Daily Data Update — START"
log "=========================================="

# ── Source environment ─────────────────────────────────────────────────────

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.env"
    set +a
    log "Sourced .env"
else
    log "ERROR: .env file not found at $PROJECT_DIR/.env"
    exit 1
fi

if [ -z "${POLYGON_API_KEY:-}" ]; then
    log "ERROR: POLYGON_API_KEY is not set in .env"
    exit 1
fi

log "POLYGON_API_KEY is set (${POLYGON_API_KEY:0:4}...)"

# ── Step 1: Backfill Polygon Cache ─────────────────────────────────────────

BACKFILL_ARGS="--workers 4"
if [ "$DRY_RUN" = true ]; then
    BACKFILL_ARGS="$BACKFILL_ARGS --dry-run"
fi

log "Step 1: Fetching new SPY options data (backfill_polygon_cache.py $BACKFILL_ARGS)"

if python3 "$PROJECT_DIR/scripts/backfill_polygon_cache.py" $BACKFILL_ARGS >> "$LOG_FILE" 2>&1; then
    log "Step 1: PASSED — backfill completed successfully"
else
    BACKFILL_EXIT=$?
    log "Step 1: FAILED — backfill exited with code $BACKFILL_EXIT"
    exit 1
fi

# ── Step 2: Validate Iron Vault DB ─────────────────────────────────────────

log "Step 2: Validating options_cache.db (iron_vault_setup.py)"

if python3 "$PROJECT_DIR/scripts/iron_vault_setup.py" >> "$LOG_FILE" 2>&1; then
    log "Step 2: PASSED — Iron Vault validation successful"
else
    VAULT_EXIT=$?
    log "Step 2: FAILED — Iron Vault validation exited with code $VAULT_EXIT"
    exit 1
fi

# ── Done ───────────────────────────────────────────────────────────────────

log "=========================================="
log "Daily Data Update — COMPLETE"
log "=========================================="
