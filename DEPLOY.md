# tkt.ge Telegram Ticket Monitor — Deployment

## Quick start

```bash
# 1. Edit the .env file with your real BOT_TOKEN from @BotFather
nano /root/tg-ticket-monitor/.env

# 2. Enable the service to start on boot
systemctl enable tg-ticket-monitor

# 3. Start the service
systemctl start tg-ticket-monitor

# 4. Check that it's running
systemctl status tg-ticket-monitor

# 5. Tail the logs
journalctl -u tg-ticket-monitor -f
```

## Service details

| Item | Value |
|---|---|
| Service file | `/etc/systemd/system/tg-ticket-monitor.service` |
| User | `tg-ticket-mon` (system, no login) |
| Working directory | `/root/tg-ticket-monitor` |
| Python | `.venv/bin/python3` (virtualenv) |
| Config data | `/root/tg-ticket-monitor/data/` (per-chat JSON) |
| .env file | `/root/tg-ticket-monitor/.env` |
| Python 3.13 compat | `python3 patch_slots.py` after pip install |

## Python 3.13 compatibility

This bot uses `python-telegram-bot==20.8`, which has a known `__slots__` issue on
Python 3.13: the `Updater` class assigns `self.__polling_cleanup_cb` in `__init__`
but doesn't include it in the `__slots__` tuple. The `deploy.sh` script automatically
applies the fix via `patch_slots.py` after installing dependencies.

If you rebuild the virtualenv, re-run the patch:

```bash
.venv/bin/python3 patch_slots.py
```

Or run the full deploy script:

```bash
bash deploy.sh
```

## What the service does

The bot polls tkt.ge every 60 seconds for each configured route. When it finds new tickets or increased seat availability, it sends a Telegram notification to the chat that set up the monitor.

The `bot.py` entry point:
- Loads BOT_TOKEN from `.env`
- Registers 6 commands: `/start`, `/setroute`, `/setdate`, `/setclass`, `/status`, `/stop`
- Uses python-telegram-bot's `run_polling()` — this blocks and runs forever

## Useful commands

```bash
# View recent logs
journalctl -u tg-ticket-monitor -n 50 --no-pager

# Follow logs in real time
journalctl -u tg-ticket-monitor -f

# Restart the service
systemctl restart tg-ticket-monitor

# Stop the service
systemctl stop tg-ticket-monitor

# Disable (prevent start on boot)
systemctl disable tg-ticket-monitor
```

## Permissions

- The service runs as `tg-ticket-mon` (non-root system user)
- Code is at `/root/tg-ticket-monitor` (readable by tg-ticket-mon)
- The `data/` directory is writable by tg-ticket-mon (per-chat JSON configs)
- `.env` is readable only by tg-ticket-mon (mode 600)
- `/root` is mode 755 so tg-ticket-mon can traverse it

## First-time deployment

If you're deploying from scratch, the `deploy.sh` script handles everything:

```bash
# Edit your token first
cd /root/tg-ticket-monitor
nano .env

# Run the full deployment (venv, deps, patch, service)
bash deploy.sh

# Then enable + start
systemctl enable tg-ticket-monitor
systemctl start tg-ticket-monitor
systemctl status tg-ticket-monitor
```

## Re-deploy after code changes

After `git pull` or manual code updates:

```bash
# Re-apply ownership in case files were created as root
chown -R tg-ticket-mon:tg-ticket-mon /root/tg-ticket-monitor

# If dependencies changed, rebuild and re-patch:
# .venv/bin/pip install -r requirements.txt
# .venv/bin/python3 patch_slots.py

# Restart to pick up changes
systemctl restart tg-ticket-monitor
```
