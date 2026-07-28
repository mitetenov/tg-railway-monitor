# syntax=docker/dockerfile:1
# ─── Telegram Ticket Monitor — Docker image ──────────────────────────────
#
# Build with version (recommended):
#   VERSION=$(cat version.txt)
#   docker build --build-arg VERSION=$VERSION \
#     -t mitetenov/tg-ticket-monitor:$VERSION \
#     -t mitetenov/tg-ticket-monitor:latest .
#
# Push:
#   docker push mitetenov/tg-ticket-monitor:$VERSION
#   docker push mitetenov/tg-ticket-monitor:latest
#
# Environment variables:
#   BOT_TOKEN  (required) — Telegram bot token from @BotFather
#   TZ         (optional) — container timezone, e.g. Asia/Tbilisi
#
# Layer order is deliberate: everything that changes rarely (base image,
# OS packages, user, Python deps) comes first; the application code and
# the VERSION label — which change on every commit — come last, so a
# version bump never invalidates the dependency layers.
#
ARG PYTHON_VERSION=3.11

# ═══════════════════════════════════════════════════════════════════════
# Stage 1 — build dependencies into an isolated prefix
# ═══════════════════════════════════════════════════════════════════════
FROM python:${PYTHON_VERSION}-alpine AS deps

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /tmp/build
COPY requirements.txt .

# The BuildKit cache mount keeps pip's wheel/HTTP cache between local
# rebuilds without ever landing in an image layer.  Installing into
# /install (rather than the system prefix) means the runtime stage copies
# exactly the dependencies — no pip bytecode, no build leftovers.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --prefix=/install -r requirements.txt

# ═══════════════════════════════════════════════════════════════════════
# Stage 2 — runtime
# ═══════════════════════════════════════════════════════════════════════
FROM python:${PYTHON_VERSION}-alpine AS runtime

# ── OS packages + non-root user (one layer, changes almost never) ──────
# tzdata lets the operator pin the container clock with -e TZ=Asia/Tbilisi.
RUN apk add --no-cache tzdata \
    && adduser -D -H -u 10001 monitor

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Python dependencies (invalidated only by requirements.txt) ─────────
COPY --from=deps /install /usr/local

WORKDIR /app

# ── Runtime data directory (per-chat JSON configs, normally a volume) ──
RUN mkdir -p /app/data && chown monitor:monitor /app/data

# ── Application code (changes every commit — copied last) ──────────────
# --chown avoids a `chown -R` layer that would duplicate the whole tree.
# locales/ is not optional: without it i18n silently renders every message
# as a "?key?" placeholder instead of failing loudly.
COPY --chown=monitor:monitor *.py ./
COPY --chown=monitor:monitor locales/ ./locales/

USER monitor

# ── Build-time version metadata (last: invalidates nothing above) ──────
ARG VERSION=0.0.0
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="tg-ticket-monitor" \
      org.opencontainers.image.description="Telegram bot for monitoring train ticket availability" \
      org.opencontainers.image.source="https://github.com/mitetenov/tg-railway-monitor"

# bot.py reads BOT_TOKEN straight from the environment (python-dotenv
# never overrides real env vars), so no entrypoint shim is needed.
ENTRYPOINT ["python3", "bot.py"]
