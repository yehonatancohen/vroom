FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the SQLite DB outside the container
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/yad2bot.db

CMD ["python", "main.py"]
