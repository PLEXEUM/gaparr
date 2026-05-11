#!/bin/bash

# Set default schedule if not provided
SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"

# Add cron job that logs to both file and stdout
echo "$SCHEDULE cd /app && python /app/sync.py 2>&1 | tee -a /app/logs/gaparr.log" > /etc/cron.d/gaparr-cron
chmod 0644 /etc/cron.d/gaparr-cron
crontab /etc/cron.d/gaparr-cron

# Start cron in foreground and also show output
cron -f 2>&1