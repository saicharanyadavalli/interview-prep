#!/bin/bash
# ==============================================================================
# Health Check & Self-Healing Watchdog for Interview Practice Platform
# Recommended crontab: */5 * * * * /home/ubuntu/interview-prep/interview-app/scripts/healthcheck.sh
# ==============================================================================

set -euo pipefail

# Configuration
LOG_FILE="/var/log/interview-app-health.log"
APP_DIR="/home/ubuntu/interview-prep/interview-app"
HEALTH_URL="http://127.0.0.1:8000/health/live"
LOCK_FILE="$APP_DIR/.healthcheck.lock"
STATE_FILE="$APP_DIR/.healthcheck_state"
MAX_CONSECUTIVE_FAILURES=3
COOLDOWN_SECONDS=600         # 10 minutes between restart attempts
MAX_CONSECUTIVE_RESTARTS=3   # Cap to prevent infinite restart loops
PROBE_TIMEOUT=10
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL:-}"

# Ensure lock descriptor to prevent overlapping concurrent executions
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Another healthcheck execution is already in progress. Exiting." >> "$LOG_FILE"
    exit 0
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" >> "$LOG_FILE"
}

# Load state
FAIL_COUNT=0
LAST_RESTART=0
RESTART_COUNT=0

if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE" 2>/dev/null || true
fi

# Ensure integer defaults
FAIL_COUNT=${FAIL_COUNT:-0}
LAST_RESTART=${LAST_RESTART:-0}
RESTART_COUNT=${RESTART_COUNT:-0}

save_state() {
    cat <<EOF > "$STATE_FILE"
FAIL_COUNT=$FAIL_COUNT
LAST_RESTART=$LAST_RESTART
RESTART_COUNT=$RESTART_COUNT
EOF
}

CURRENT_TIME=$(date +%s)

# Probe local liveness endpoint directly via GET
HTTP_CODE=$(curl -fsS -o /dev/null -w "%{http_code}" --max-time "$PROBE_TIMEOUT" "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    if [ "$FAIL_COUNT" -gt 0 ] || [ "$RESTART_COUNT" -gt 0 ]; then
        log "✅ Backend service recovered to healthy state (HTTP $HTTP_CODE). Clearing failure counters."
    else
        log "✅ Backend health check passed (HTTP $HTTP_CODE)"
    fi
    FAIL_COUNT=0
    RESTART_COUNT=0
    save_state
    exit 0
fi

# Failure Handling
FAIL_COUNT=$((FAIL_COUNT + 1))
log "❌ Backend health check probe failed (HTTP $HTTP_CODE) - consecutive failure count: $FAIL_COUNT / $MAX_CONSECUTIVE_FAILURES"

# Optional webhook notification
if [ -n "$ALERT_WEBHOOK" ]; then
    curl -s -X POST "$ALERT_WEBHOOK" \
        -H 'Content-type: application/json' \
        -d "{\"text\":\"🚨 Interview Prep Backend health check failed! HTTP $HTTP_CODE (attempt $FAIL_COUNT) on $(hostname)\"}" > /dev/null 2>&1 || true
fi

# Check if failure threshold reached
if [ "$FAIL_COUNT" -lt "$MAX_CONSECUTIVE_FAILURES" ]; then
    log "⚠️ Failure count ($FAIL_COUNT) is below retry threshold ($MAX_CONSECUTIVE_FAILURES). Awaiting next probe cycle."
    save_state
    exit 1
fi

# Failure threshold reached: evaluate cooldown and restart limits
TIME_SINCE_RESTART=$((CURRENT_TIME - LAST_RESTART))

if [ "$RESTART_COUNT" -ge "$MAX_CONSECUTIVE_RESTARTS" ]; then
    log "🛑 Maximum consecutive restart limit ($MAX_CONSECUTIVE_RESTARTS) reached. Suppressing automatic restarts to prevent infinite restart loop. Manual inspection required."
    save_state
    exit 1
fi

if [ "$TIME_SINCE_RESTART" -lt "$COOLDOWN_SECONDS" ]; then
    REMAINING=$((COOLDOWN_SECONDS - TIME_SINCE_RESTART))
    log "⏳ Restart cooldown active (${TIME_SINCE_RESTART}s elapsed, ${REMAINING}s remaining of ${COOLDOWN_SECONDS}s). Suppressing restart."
    save_state
    exit 1
fi

# Execute targeted self-healing restart
if [ -d "$APP_DIR" ]; then
    log "🔄 Threshold of $MAX_CONSECUTIVE_FAILURES consecutive failures reached. Executing targeted restart of 'backend' service..."
    cd "$APP_DIR"
    if docker compose restart backend >> "$LOG_FILE" 2>&1; then
        RESTART_COUNT=$((RESTART_COUNT + 1))
        LAST_RESTART=$CURRENT_TIME
        FAIL_COUNT=0
        log "✅ Backend container restart initiated successfully (restart #$RESTART_COUNT/$MAX_CONSECUTIVE_RESTARTS)."
    else
        log "❌ Failed to restart backend container via docker compose."
    fi
else
    log "❌ Application directory $APP_DIR does not exist. Cannot restart backend container."
fi

save_state
exit 1
