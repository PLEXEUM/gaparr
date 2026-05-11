#!/bin/bash

# Set default schedule if not provided
SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"

# Add cron job with user's schedule
echo "$SCHEDULE cd /app && python /app/sync.py >> /app/logs/gaparr.log 2>&1" > /etc/cron.d/gaparr-cron
chmod 0644 /etc/cron.d/gaparr-cron
crontab /etc/cron.d/gaparr-cron

# Start cron in foreground
cron -f