FROM python:3.11-slim

RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync.py /app/sync.py

RUN mkdir -p /app/logs

# Add cron job
RUN echo "0 11 * * * cd /app && python /app/sync.py >> /app/logs/gaparr.log 2>&1" > /etc/cron.d/gaparr-cron && \
    chmod 0644 /etc/cron.d/gaparr-cron && \
    crontab /etc/cron.d/gaparr-cron

# Create log file
RUN touch /app/logs/gaparr.log

CMD ["cron", "-f"]