# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_PORT=8000 \
    AGENT_API_PORT=8765 \
    TZ=Europe/Moscow

# libsndfile1 is required by soundfile; curl is used by HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
        libsndfile1 \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Never bake secrets or runtime data into the image.
# (COPY --exclude keeps this working without a separate .dockerignore.)
COPY --exclude=.git \
     --exclude=.env \
     --exclude=.venv \
     --exclude=__pycache__ \
     --exclude=*.pyc \
     --exclude=*.log \
     --exclude=config.json \
     --exclude=data \
     --exclude=models \
     --exclude=media \
     --exclude=webview \
     --exclude=docker/telegram-bot-api.env \
     --exclude=preview.png \
     --exclude=preview-stt.jpg \
     . .

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/models \
    && chown -R app:app /app

USER app

EXPOSE 8000 8765

# /api/health is the primary check; "/" is the fallback if the route is not
# available. Both are served by the web process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${WEB_PORT:-8000}/api/health" >/dev/null 2>&1 \
        || curl -fsS "http://127.0.0.1:${WEB_PORT:-8000}/" >/dev/null 2>&1 \
        || exit 1

CMD ["python", "web_main.py"]
