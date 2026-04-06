FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

VOLUME ["/app/data"]
VOLUME ["/app/fb_profile"]

ENV DB_PATH=/app/data/yad2bot.db
ENV FB_PROFILE_DIR=/app/fb_profile

CMD ["python", "main.py"]
