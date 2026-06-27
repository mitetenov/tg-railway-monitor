"""
Background ticket monitoring.
Launches an asyncio task per chat that checks available rides every 60 s.
"""
import asyncio
import logging
from typing import Dict, Optional

import aiohttp
from telegram import Bot
from telegram.error import TelegramError

from api import get_available_rides
from config_manager import load_config

logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 60  # seconds between checks

# Global registry of running poller tasks: chat_id -> asyncio.Task
_running_tasks: Dict[int, asyncio.Task] = {}

# Track already-notified ride+class combos so we don't spam
_notified: Dict[int, set] = {}


def _notified_key(ride_number: int, class_name: str) -> str:
    return f"{ride_number}:{class_name}"


def _format_time(iso_str: str) -> str:
    """Extract HH:MM from ISO datetime string, handling timezone offsets."""
    if not iso_str:
        return "??:??"
    try:
        if "T" in iso_str:
            time_part = iso_str.split("T")[1]
            # Strip timezone offset: +04:00, Z, etc
            for sep in ("+", "-", "Z"):
                if sep in time_part[2:]:  # skip the HH part
                    time_part = time_part.split(sep)[0]
            return time_part[:5]
        return iso_str
    except (IndexError, ValueError):
        return iso_str


async def _check_and_notify(bot: Bot, chat_id: int) -> None:
    """Single check → notify if new tickets found.

    Groups all newly-found seat classes for the same ride into one message.
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

    # ── Collect newly-found classes per ride ────────────────────────
    # ride_number -> (ride_dict, [(cls_name, seats, price), ...])
    rides_with_new: dict = {}

    for ride in rides:
        ride_num = ride.get("rideNumber")
        if ride_num is None:
            continue

        new_classes = []
        classes_raw = ride.get("availableSeatsClasses", [])
        for cls in classes_raw:
            cls_name = cls.get("seatClassName", "")
            seats = cls.get("availableNumberOfSeats", 0)
            price = cls.get("moneyAmount", "?")

            # Apply class filter
            if seat_class != "Any":
                # Normalise: "Business" → "business", "I" → "i", "II" → "ii"
                target = seat_class.lower().strip()
                current = cls_name.lower().strip()
                if target not in current and current not in target:
                    continue

            if seats is not None and seats > 0:
                key = _notified_key(ride_num, cls_name)
                if key not in _notified.setdefault(chat_id, set()):
                    new_classes.append((cls_name, seats, price))
                    _notified[chat_id].add(key)

        if new_classes:
            rides_with_new[ride_num] = (ride, new_classes)

    if not rides_with_new:
        return

    # ── Build one grouped notification per ride ─────────────────────
    lines = [
        f"🎫 *{config.get('from_station', '?')}* → *{config.get('to_station', '?')}*",
        f"📅 {date}",
        "",
    ]
    for ride_num, (ride, class_list) in list(rides_with_new.items())[:5]:
        dep = _format_time(ride.get("rideStartDate") or "")
        arr = _format_time(ride.get("rideEndDate") or "")
        dur = ride.get("rideDuration", "?")
        lines.append(f"🚆 *Ride #{ride_num}*  {dep} → {arr} ({dur})")
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
    """Infinite loop checking tickets for a single chat."""
    logger.info("Started polling for chat %d", chat_id)
    try:
        while True:
            await _check_and_notify(bot, chat_id)
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
    _notified.pop(chat_id, None)


def is_running(chat_id: int) -> bool:
    """Check if polling is active for this chat."""
    task = _running_tasks.get(chat_id)
    return task is not None and not task.done()


def active_count() -> int:
    """Return number of chats being monitored."""
    return len(_running_tasks)
