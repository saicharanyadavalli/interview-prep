#!/bin/bash
# ============================================================
# Health Check & Self-Healing Script for Interview Prep Platform
# Recommended crontab: */5 * * * * /home/ubuntu/interview-prep/interview-app/scripts/healthcheck.sh
# ============================================================

LOG_FILE="/var/log/interview-app-health.log"
APP_DIR="/home/ubuntu/interview-prep/interview-app"
HEALTH_URL="http://127.0.0.1:8000/health"
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | sudo tee -a "$LOG_FILE" > /dev/null
}

check_health() {
    # Probe local backend health endpoint directly via GET
    HTTP_CODE=$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 10 "$HEALTH_URL" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        log "✅ Backend health check passed (HTTP $HTTP_CODE)"
        return 0
    else
        log "❌ Backend health check failed (HTTP $HTTP_CODE)"

        # Optional webhook alert
        if [ -n "$ALERT_WEBHOOK" ]; then
            curl -s -X POST "$ALERT_WEBHOOK" \
                -H 'Content-type: application/json' \
                -d "{\"text\":\"🚨 Interview Prep Backend health check failed! HTTP $HTTP_CODE on $(hostname)\"}" > /dev/null 2>&1 || true
        fi

        # Attempt self-healing container restart
        if [ -d "$APP_DIR" ]; then
            log "Attempting to restart backend container..."
            cd "$APP_DIR" || exit 1
            docker compose restart backend
        fi
        return 1
    fi
}

check_health
