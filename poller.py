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
from api_tre import TreGeApi
from config_manager import (
    is_config_complete,
    iter_chat_ids,
    load_config,
    load_state,
    save_state,
)
from i18n import get_user_language, get_user_translation, translate_station_name
from ticket_monitor import CLASS_FILTER_IDS, CLASS_NAMES
from utils import format_time

logger = logging.getLogger(__name__)

MONITOR_INTERVAL = 60  # seconds between checks

# Global registry of running poller tasks: chat_id -> asyncio.Task
_running_tasks: Dict[int, asyncio.Task] = {}

# Store previous seat counts per chat for stateful diffing.
# Structure: {chat_id: {"key": "from>to@date",
#                       "rides": {ride_number_str: {class_id_str: {"seats", "price"}}}}}
# Mirrored to data/{chat_id}.state.json so a restart does not re-announce
# every ticket that was already known.
_state: Dict[int, dict] = {}

# Pause state per chat — when True the loop stays alive but skips checks
_paused: Dict[int, bool] = {}

# Shared HTTP session, created lazily on the running loop.  One session for
# the whole process keeps connections alive between checks instead of paying
# for a fresh TLS handshake every 60 s per chat.
_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    """Return the shared aiohttp session, creating it on first use."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """Close the shared session — call once during application shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


def _route_key(config: dict) -> str:
    """Identity of the thing being monitored: route + date.

    When any of these change the previous snapshot describes a different
    search and must be discarded rather than diffed against.
    """
    return (
        f"{config.get('from_station_code', '')}>"
        f"{config.get('to_station_code', '')}@{config.get('date', '')}"
    )


def _get_rides_state(chat_id: int, config: dict) -> dict:
    """Return the stored per-ride snapshot for the chat's current route.

    Loads from disk on first access after a restart.  A snapshot taken for
    a different route or date is dropped, which also keeps the state file
    from growing without bound as users change their plans.
    """
    entry = _state.get(chat_id)
    if entry is None:
        entry = load_state(chat_id)
        _state[chat_id] = entry

    if entry.get("key") != _route_key(config):
        entry = {"key": _route_key(config), "rides": {}}
        _state[chat_id] = entry

    return entry.setdefault("rides", {})


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

    session = await get_session()
    data = await get_available_rides(session, from_code, to_code, date)

    if data is None:
        return  # API error, try again next interval

    rides = data.get("departureAvailableRides", [])
    if not rides:
        return

    chat_state = _get_rides_state(chat_id, config)
    has_any_changes = False
    state_dirty = False
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
            price = cls.get("moneyAmount", 0)

            # Apply class filter
            if seat_class != "Any":
                target_id = CLASS_FILTER_IDS.get(seat_class)
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
            if prev_entry is None or prev_entry.get("seats") != seats:
                state_dirty = True
            ride_state[str(cls_id)] = {"seats": seats, "price": price}

        chat_state[str(ride_num)] = ride_state

        if all_classes:
            all_rides[ride_num] = (ride, all_classes)
        if changed_classes:
            has_any_changes = True

    if state_dirty:
        save_state(chat_id, _state[chat_id])

    if not has_any_changes:
        return

    # ── Build one grouped notification with ALL available rides ──────
    t = get_user_translation(chat_id)
    from_code_str = config.get("from_station_code", "0")
    to_code_str = config.get("to_station_code", "0")
    from_name_display = translate_station_name(int(from_code_str), t.lang,
                                                fallback=config.get("from_station", ""))
    to_name_display = translate_station_name(int(to_code_str), t.lang,
                                              fallback=config.get("to_station", ""))
    lines = [
        t("poller.route_header",
          from_name=from_name_display,
          to_name=to_name_display),
        t("poller.date", date=date),
        "",
    ]
    for ride_num, (ride, class_list) in all_rides.items():
        dep = format_time(ride.get("rideStartDate") or "")
        arr = format_time(ride.get("rideEndDate") or "")
        dur = ride.get("rideDuration", "?")
        lines.append(t("poller.ride",
                       ride_num=ride_num, departure=dep, arrival=arr, duration=dur))
        # Build purchase link via TreGeApi
        purchase_url = TreGeApi.build_purchase_url(
            config.get("from_station_code", ""),
            config.get("to_station_code", ""),
            date,
        )
        lines.append(t("poller.purchase_link", url=purchase_url))
        for cls_name, seats, price in class_list:
            lines.append(t("poller.class_info",
                           class_name=cls_name, seats=seats, price=price))
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

    A failing check must never end monitoring: anything short of
    cancellation is logged and retried on the next interval.
    """
    logger.info("Started polling for chat %d", chat_id)
    try:
        while True:
            if not _paused.get(chat_id, False):
                try:
                    await _check_and_notify(bot, chat_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Check failed for chat %d; retrying in %ds",
                        chat_id,
                        MONITOR_INTERVAL,
                    )
            else:
                logger.debug("Polling paused for chat %d", chat_id)
            await asyncio.sleep(MONITOR_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Polling cancelled for chat %d", chat_id)
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
    """Stop polling for a chat if running.

    The on-disk snapshot is deliberately kept: restarting monitoring
    should not replay every ticket that was already reported.
    """
    task = _running_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Poller stopped for chat %d", chat_id)
    _state.pop(chat_id, None)
    _paused.pop(chat_id, None)


def restore_all(bot: Bot) -> int:
    """Restart monitoring for every chat that has a complete config.

    Called once at startup.  Without this the in-memory task registry is
    empty after a restart, so monitoring stays silently dead even though
    the configs are still on disk.

    Returns the number of pollers restored.
    """
    restored = 0
    for chat_id in iter_chat_ids():
        try:
            config = load_config(chat_id)
        except RuntimeError as e:
            logger.warning("Skipping chat %d: %s", chat_id, e)
            continue
        if not is_config_complete(config):
            continue
        start(bot, chat_id)
        restored += 1
    if restored:
        logger.info("Restored %d poller(s) after restart", restored)
    return restored


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
        t = get_user_translation(chat_id)
        return (
            False,
            t("poller.not_configured"),
        )

    # Clear pause flag so the loop resumes checking
    _paused.pop(chat_id, None)

    t = get_user_translation(chat_id)
    if not is_running(chat_id):
        start(bot, chat_id)
        return (True, t("poller.resumed"))
    else:
        return (True, t("poller.already_active"))


def active_count() -> int:
    """Return number of chats being monitored."""
    return len(_running_tasks)
