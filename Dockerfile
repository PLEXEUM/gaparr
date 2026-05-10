FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
# This copies main.py AND the entire app/ directory into /app/
COPY . .

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Create logs directory for log files
RUN mkdir -p /app/logs

# Expose port
EXPOSE 7117

# Run main.py
CMD ["python", "main.py"]