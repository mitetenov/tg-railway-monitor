# ─── tkt.ge Telegram Ticket Monitor — Docker image ───────────────────────
#
# Build with version (recommended):
#   VERSION=$(cat version.txt)
#   docker build --build-arg VERSION=$VERSION \
#     -t tg-ticket-monitor:$VERSION \
#     -t tg-ticket-monitor:latest .
#
# Quick build (no version arg — uses 0.0.0 as fallback):
#   docker build -t tg-ticket-monitor .
#
# Run:
#   docker run -d --restart unless-stopped \
#     --name tg-ticket-monitor \
#     -e BOT_TOKEN=your_token_here \
#     tg-ticket-monitor
#
# Environment variables:
#   BOT_TOKEN   (required) — Telegram bot token from @BotFather
#
FROM python:3.11-alpine

# ── Build-time version (injected via --build-arg VERSION=x.y.z) ──────
ARG VERSION=0.0.0
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.title="tg-ticket-monitor"
LABEL org.opencontainers.image.description="Telegram bot for monitoring tkt.ge ticket availability"

# ── OS-level dependencies ───────────────────────────────────────────────
# tzdata for timezone support (used by datetime logic); clean apk caches
RUN apk add --no-cache tzdata

# ── Non-root user ───────────────────────────────────────────────────────
RUN adduser -D -h /app monitor

WORKDIR /app

# ── Python dependencies (copied first for Docker layer caching) ─────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ────────────────────────────────────────────────────
COPY . .

# ── Runtime directories and permissions ─────────────────────────────────
RUN mkdir -p data /app/.env-data \
    && chown -R monitor:monitor /app

# ── Entrypoint ──────────────────────────────────────────────────────────
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod 755 /app/docker-entrypoint.sh && chown monitor:monitor /app/docker-entrypoint.sh

USER monitor

ENTRYPOINT ["/app/docker-entrypoint.sh"]
