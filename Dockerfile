FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (separate layer for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Data directory — mount a named volume here to persist SQLite DB
RUN mkdir -p /app/data

CMD ["python", "bot.py"]
