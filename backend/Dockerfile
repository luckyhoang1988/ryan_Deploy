FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies hệ thống cho psycopg + impacket
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# ASGI (uvicorn, không phải gunicorn+wsgi) — cần cho WebSocket real-time (Channels).
# Không dùng daphne: daphne ghim twisted[tls]->pyopenssl>=25.2.0, xung đột impacket
# ghim pyOpenSSL==24.0.0 (xem requirements.txt).
CMD ["uvicorn", "ryandeploy.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
