#!/usr/bin/env bash
# deploy.sh — one-shot setup for the tg-ticket-monitor systemd service
# Run as root:  bash deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="tg-ticket-monitor"

echo "=== tg-ticket-monitor deployment ==="

# ── 1. Create non-privileged system user ────────────────────────────
if ! id -u tg-ticket-mon &>/dev/null; then
    echo "Creating system user 'tg-ticket-mon'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin tg-ticket-mon
else
    echo "User 'tg-ticket-mon' already exists."
fi

# ── 2. Make /root traversable by the service user ──────────────────
# The project lives under /root/; the service needs read+traverse.
chmod 755 /root

# ── 3. Set ownership of the project tree ───────────────────────────
# tg-ticket-mon needs read+execute on code and write on data/
chown -R tg-ticket-mon:tg-ticket-mon "$SCRIPT_DIR"
chmod 755 "$SCRIPT_DIR"
chmod 644 "$SCRIPT_DIR"/*.py
chmod 755 "$SCRIPT_DIR"/.venv/bin/python3 2>/dev/null || true

# Ensure data/ directory is writable
mkdir -p "$SCRIPT_DIR/data"
chown tg-ticket-mon:tg-ticket-mon "$SCRIPT_DIR/data"
chmod 755 "$SCRIPT_DIR/data"

# ── 4. Ensure .env exists with placeholder if missing ──────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Creating .env from .env.example — EDIT THIS FILE with your real BOT_TOKEN"
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    chown tg-ticket-mon:tg-ticket-mon "$SCRIPT_DIR/.env"
    chmod 600 "$SCRIPT_DIR/.env"
fi

# ── 5. Set up virtualenv and install dependencies ──────────────────
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
echo "Installing Python dependencies..."
"$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ── 6. Patch python-telegram-bot for Python 3.13 __slots__ compat ──
echo "Patching python-telegram-bot for Python 3.13 compatibility..."
"$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/patch_slots.py"

# ── 7. Install systemd service ─────────────────────────────────────
echo "Installing systemd service..."
install -m 644 -o root -g root "$SCRIPT_DIR/tg-ticket-monitor.service" /etc/systemd/system/
systemctl daemon-reload

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $SCRIPT_DIR/.env with your real BOT_TOKEN from @BotFather"
echo "  2. Enable on boot:   systemctl enable $SERVICE_NAME"
echo "  3. Start:            systemctl start $SERVICE_NAME"
echo "  4. Check status:     systemctl status $SERVICE_NAME"
echo "  5. View logs:        journalctl -u $SERVICE_NAME -f"
