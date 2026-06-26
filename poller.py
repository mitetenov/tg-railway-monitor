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


async def _check_and_notify(bot: Bot, chat_id: int) -> None:
    """Single check → notify if new tickets found."""
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

    # Find rides matching the user's class filter
    new_finds = []
    for ride in rides:
        classes = ride.get("availableSeatsClasses", [])
        for cls in classes:
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
                key = _notified_key(ride.get("rideNumber"), cls_name)
                if key not in _notified.setdefault(chat_id, set()):
                    new_finds.append((ride, cls_name, seats, price))
                    _notified[chat_id].add(key)

    if not new_finds:
        return

    # Build notification message
    lines = [
        f"🎫 *{config.get('from_station', '?')}* → *{config.get('to_station', '?')}*",
        f"📅 {date}",
        "",
    ]
    for ride, cls_name, seats, price in new_finds[:5]:
        dep = (ride.get("rideStartDate") or "")[:5]
        arr = (ride.get("rideEndDate") or "")[:5]
        dur = ride.get("rideDuration", "?")
        ride_n = ride.get("rideNumber", "?")
        lines.append(f"🚆 *Ride #{ride_n}*  {dep} → {arr} ({dur})")
        lines.append(f"   {cls_name}: {seats} seat(s) · {price} GEL")
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
