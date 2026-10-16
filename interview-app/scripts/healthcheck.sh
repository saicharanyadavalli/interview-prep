#!/bin/bash
# ============================================
# Health Check Script
# Add to cron: */5 * * * * /opt/interview-api/scripts/healthcheck.sh
# ============================================

LOG_FILE="/var/log/interview-api-health.log"
API_URL="https://api.yourdomain.com"
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_health() {
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${API_URL}/health")

    if [ "$response" = "200" ]; then
        log "✅ Health check passed (HTTP $response)"
        return 0
    else
        log "❌ Health check failed (HTTP $response)"

        # Send alert
        if [ -n "$ALERT_WEBHOOK" ]; then
            curl -s -X POST "$ALERT_WEBHOOK" \
                -H 'Content-type: application/json' \
                -d "{\"text\":\"🚨 Interview API health check failed! HTTP $response\"}"
        fi

        # Try to restart
        log "Attempting to restart container..."
        cd /opt/interview-api/interview-app/backend
        docker compose restart app
        return 1
    fi
}

# Main
check_health
