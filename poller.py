"""
Background ticket monitoring.
Launches an asyncio task per chat that checks available rides every 60 s.
"""
import asyncio
import logging
import os
from typing import Dict, Optional

import aiohttp
from telegram import Bot
from telegram.error import TelegramError

from api import get_available_rides
from api_tre import TreGeApi
from config_manager import load_config
from ticket_monitor import CLASS_NAMES
from utils import format_time

logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 60  # seconds between checks

# Global registry of running poller tasks: chat_id -> asyncio.Task
_running_tasks: Dict[int, asyncio.Task] = {}

# Store previous seat counts per chat for stateful diffing.
# Structure: {chat_id: {ride_number_str: {seat_class_id_str: {"seats": N, "price": M}}}}
_state: Dict[int, dict] = {}

# Pause state per chat — when True the loop stays alive but skips checks
_paused: Dict[int, bool] = {}


async def _check_and_notify(bot: Bot, chat_id: int) -> None:
    """Single check → notify if tickets appeared or seat count increased.

    Sends one notification with ALL currently available rides (filtered by
    user preferences).  Notification is sent only when the stateful diff
    detects meaningful changes — no spam for unchanged availability.
    """
    config = load_config(chat_id)
    if not config:
        return

    from_code = config.get("from_station_code")
    to_code = config.get("to_station_code")
    date = config.get("date")
    seat_class = config.get("seat_class", "Any")

    if not all([from_code, to_code, date]):
        return  # incomplete config, skip

    async with aiohttp.ClientSession() as session:
        data = await get_available_rides(session, from_code, to_code, date)

    if data is None:
        return  # API error, try again next interval

    rides = data.get("departureAvailableRides", [])
    if not rides:
        return

    _CLASS_FILTER_MAP = {"I": 1, "II": 2, "Business": 5}

    chat_state = _state.setdefault(chat_id, {})
    has_any_changes = False
    all_rides: dict = {}  # ride_number -> (ride_dict, [(cls_name, seats, price), ...])

    for ride in rides:
        ride_num = ride.get("rideNumber")
        if ride_num is None:
            continue

        all_classes = []
        changed_classes = []
        classes_raw = ride.get("availableSeatsClasses", [])
        ride_state = chat_state.get(str(ride_num), {})

        for cls in classes_raw:
            cls_id = cls.get("seatClassId")
            cls_name = CLASS_NAMES.get(cls_id, "")
            seats = cls.get("availableNumberOfSeats") or 0
            price = cls.get("moneyAmount", "?")

            # Apply class filter
            if seat_class != "Any":
                target_id = _CLASS_FILTER_MAP.get(seat_class)
                if target_id is not None and cls_id != target_id:
                    continue

            # Stateful diff
            prev_entry = ride_state.get(str(cls_id))
            prev_seats = prev_entry["seats"] if prev_entry else 0

            if seats > 0:
                all_classes.append((cls_name, seats, price))
                if prev_entry is None or seats > prev_seats:
                    changed_classes.append((cls_name, seats, price))

            # Always persist current state
            ride_state[str(cls_id)] = {"seats": seats, "price": price}

        chat_state[str(ride_num)] = ride_state

        if all_classes:
            all_rides[ride_num] = (ride, all_classes)
        if changed_classes:
            has_any_changes = True

    if not has_any_changes:
        return

    # ── Build one grouped notification with ALL available rides ──────
    lines = [
        f"🎫 *{config.get('from_station', '?')}* → *{config.get('to_station', '?')}*",
        f"📅 {date}",
        "",
    ]
    for ride_num, (ride, class_list) in all_rides.items():
        dep = format_time(ride.get("rideStartDate") or "")
        arr = format_time(ride.get("rideEndDate") or "")
        dur = ride.get("rideDuration", "?")
        lines.append(f"🚆 *Ride #{ride_num}*  {dep} → {arr} ({dur})")
        # Build purchase link for this ride
        # Use TICKET_SOURCE env variable to pick the right purchase URL
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            purchase_url = TreGeApi.build_purchase_url(
                config.get("from_station_code", ""),
                config.get("to_station_code", ""),
                date,
            )
        else:
            purchase_url = "https://tkt.ge/en/railway"
        lines.append(f"🔗 [Купить]({purchase_url})")
        for cls_name, seats, price in class_list:
            lines.append(f"   {cls_name}: {seats} мест · {price} GEL")
        lines.append("")

    try:
        await bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines).strip(),
            parse_mode="Markdown",
        )
    except TelegramError as e:
        logger.warning("Failed to notify chat %d: %s", chat_id, e)


async def _poller_loop(bot: Bot, chat_id: int) -> None:
    """Infinite loop checking tickets for a single chat.

    Respects the per-chat pause flag: when paused the loop stays alive
    (so resume() can unpause without creating a new task) but skips the
    API check and notification.
    """
    logger.info("Started polling for chat %d", chat_id)
    try:
        while True:
            if not _paused.get(chat_id, False):
                await _check_and_notify(bot, chat_id)
            else:
                logger.debug("Polling paused for chat %d", chat_id)
            await asyncio.sleep(MONITOR_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Polling cancelled for chat %d", chat_id)
        raise
    except Exception:
        logger.exception("Poller loop crashed for chat %d", chat_id)
        raise


def start(bot: Bot, chat_id: int) -> None:
    """Start / restart polling for a chat."""
    stop(chat_id)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    task = loop.create_task(_poller_loop(bot, chat_id))
    _running_tasks[chat_id] = task
    logger.info("Poller started for chat %d", chat_id)


def stop(chat_id: int) -> None:
    """Stop polling for a chat if running."""
    task = _running_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Poller stopped for chat %d", chat_id)
    _state.pop(chat_id, None)
    _paused.pop(chat_id, None)


def is_running(chat_id: int) -> bool:
    """Check if polling is active for this chat."""
    task = _running_tasks.get(chat_id)
    return task is not None and not task.done()


def pause(chat_id: int) -> None:
    """Temporarily pause monitoring for a chat (keeps the task alive)."""
    _paused[chat_id] = True
    logger.info("Poller paused for chat %d", chat_id)


def is_paused(chat_id: int) -> bool:
    """Check if the poller loop is currently paused for a chat."""
    return _paused.get(chat_id, False)


def resume(bot: Bot, chat_id: int) -> tuple[bool, str]:
    """Resume monitoring for a chat.

    Checks route configuration first. If the route is not set, returns
    ``(False, error_message)``. Otherwise clears the pause flag and
    starts the poller if it is not already running.

    Returns ``(True, success_message)`` on success.
    """
    from config_manager import load_config

    config = load_config(chat_id)
    if not config.get("from_station_code") or not config.get("to_station_code"):
        return (
            False,
            "❌ Route not configured. Use /setroute first.",
        )

    # Clear pause flag so the loop resumes checking
    _paused.pop(chat_id, None)

    if not is_running(chat_id):
        start(bot, chat_id)
        return (True, "✅ Monitoring resumed!")
    else:
        return (True, "✅ Monitoring is already active.")


def active_count() -> int:
    """Return number of chats being monitored."""
    return len(_running_tasks)
