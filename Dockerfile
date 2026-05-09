FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Expose port
EXPOSE 7117

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=7117
ENV HOST=0.0.0.0

# Run the application
CMD ["python", "main.py"]