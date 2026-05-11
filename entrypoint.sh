#!/bin/bash

# Log rotation - keep last 1000 lines if file exceeds 10MB
LOG_FILE="/app/logs/gaparr.log"
if [ -f "$LOG_FILE" ] && [ $(stat -c%s "$LOG_FILE") -gt 10485760 ]; then
    tail -n 1000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# Set default schedule if not provided
SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"

# Add cron job that logs to both file and stdout
echo "$SCHEDULE cd /app && python /app/sync.py 2>&1 | tee -a /app/logs/gaparr.log" > /etc/cron.d/gaparr-cron
chmod 0644 /etc/cron.d/gaparr-cron
crontab /etc/cron.d/gaparr-cron

# Start cron in background
cron

# Tail the log file to stdout so docker logs shows it
tail -f /app/logs/gaparr.log