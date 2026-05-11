FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY sync.py .

# Create logs directory
RUN mkdir -p /app/logs

# Run script (will be overridden by docker-compose if needed)
CMD ["python", "sync.py"]