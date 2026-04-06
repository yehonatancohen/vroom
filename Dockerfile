FROM python:3.12-slim

# Chromium headless runtime dependencies.
# Installed manually to avoid playwright install-deps pulling unavailable font packages
# (ttf-unifont / ttf-ubuntu-font-family) in newer Debian releases.
# libasound2 was renamed to libasound2t64 in Debian Bookworm — try both.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libexpat1 \
    && (apt-get install -y --no-install-recommends libasound2 \
        || apt-get install -y --no-install-recommends libasound2t64) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

VOLUME ["/app/data"]

ENV DB_PATH=/app/data/yad2bot.db

CMD ["python", "main.py"]
