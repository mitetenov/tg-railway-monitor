"""
Telegram bot for monitoring tre.ge train tickets.
Commands: /start, /setroute, /setdate, /setclass, /status, /stop
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import poller
from api import get_stations
from config_manager import load_config, save_config, is_config_complete
from i18n import get_user_translation
from stations import FALLBACK_STATIONS, STATION_SLUGS
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN not set in environment or .env file")

# ── Station cache ────────────────────────────────────────────────────
_stations: list[dict] = []        # raw from API
_station_index: dict[str, dict] = {}  # code -> station
STATIONS_PER_PAGE = 8


async def load_stations() -> None:
    """Populate the station cache from API, with fallback."""
    global _stations, _station_index
    try:
        async with aiohttp.ClientSession() as session:
            data = await get_stations(session)
        if data and isinstance(data, list):
            _stations = data
        else:
            _stations = FALLBACK_STATIONS
    except Exception:
        logger.warning("API station fetch failed, using fallback list")
        _stations = FALLBACK_STATIONS

    # Build index
    for s in _stations:
        code = str(s.get("code", ""))
        _station_index[code] = s

    logger.info("Loaded %d stations", len(_stations))


def station_button(station: dict, action: str) -> InlineKeyboardButton:
    """Create an inline button for a station."""
    name = station.get("stationName", "?")
    code = str(station.get("code", ""))
    return InlineKeyboardButton(name, callback_data=f"{action}:{code}")


def pagination_buttons(page: int, total_pages: int, action: str, t=None) -> list[InlineKeyboardButton]:
    """Create Prev / Next / Page buttons for pagination."""
    buttons = []
    if page > 0:
        prev_label = t("button.prev") if t else "◀️ Prev"
        buttons.append(InlineKeyboardButton(prev_label, callback_data=f"page:{action}:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        next_label = t("button.next") if t else "Next ▶️"
        buttons.append(InlineKeyboardButton(next_label, callback_data=f"page:{action}:{page + 1}"))
    return buttons


def build_station_keyboard(action: str, page: int = 0, t=None) -> InlineKeyboardMarkup:
    """Build a paginated inline keyboard for station selection.

    action: "from" or "to"  — embedded in callback_data for state tracking.
    """
    total = len(_stations)
    total_pages = max(1, (total + STATIONS_PER_PAGE - 1) // STATIONS_PER_PAGE)
    start = page * STATIONS_PER_PAGE
    end = min(start + STATIONS_PER_PAGE, total)

    cancel_label = t("button.cancel") if t else "🚫 Cancel"

    keyboard = []
    for s in _stations[start:end]:
        name = s.get("stationName", "?")
        code = str(s.get("code", ""))
        keyboard.append([InlineKeyboardButton(name, callback_data=f"{action}:{code}")])

    nav = pagination_buttons(page, total_pages, action, t)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(cancel_label, callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


# ── Conversation states ──────────────────────────────────────────────
(FROM_STATION, TO_STATION, WAITING_DATE, WAITING_CLASS) = range(4)


# ═══════════════════════ COMMAND HANDLERS ════════════════════════════

async def cmd_start(update: Update, _context) -> None:
    """Welcome message with current config summary."""
    chat_id = update.effective_chat.id
    config = load_config(chat_id)
    t = get_user_translation(chat_id, update.effective_user)

    lines = [
        t("start.welcome"),
        "",
        t("start.description"),
        "",
    ]

    if config:
        lines.append(t("start.current_config"))
        lines.append(t("start.route_line", from_name=config.get("from_station", "?"),
                       to_name=config.get("to_station", "?")))
        lines.append(t("start.date_line", date=config.get("date", "?")))
        lines.append(t("start.class_line", class_name=config.get("seat_class", "Any")))
        if poller.is_running(chat_id):
            lines.append(f"\n{t('start.monitoring_active')}")
        else:
            lines.append(f"\n{t('start.monitoring_paused')}")
    else:
        lines.append(t("start.no_config"))
        lines.append("")

    lines.append("")
    lines.append(t("start.cmd_setroute"))
    lines.append(t("start.cmd_setdate"))
    lines.append(t("start.cmd_setclass"))
    lines.append(t("start.cmd_status"))
    lines.append(t("start.cmd_stop"))
    lines.append(t("start.cmd_resume"))
    lines.append(t("start.cmd_lang"))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, _context) -> None:
    """Show current config and monitoring state."""
    chat_id = update.effective_chat.id
    config = load_config(chat_id)
    t = get_user_translation(chat_id, update.effective_user)

    lines = [t("status.title"), ""]

    if config:
        lines.append(t("status.route", from_name=config.get("from_station", "?"),
                       to_name=config.get("to_station", "?")))
        lines.append(t("status.date", date=config.get("date", "?")))
        lines.append(t("status.class", class_name=config.get("seat_class", "Any")))
        lines.append("")

        if poller.is_running(chat_id):
            lines.append(t("status.monitoring_active"))
        elif is_config_complete(config):
            lines.append(t("status.config_complete_not_started"))
            lines.append(t("status.config_complete_hint"))
        else:
            lines.append(t("status.config_incomplete"))
    else:
        lines.append(t("status.no_config"))
        lines.append(t("status.start_with_setroute"))

    lines.append("")
    lines.append(t("status.active_monitors", count=poller.active_count()))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stop(update: Update, _context) -> None:
    """Stop monitoring for this chat."""
    chat_id = update.effective_chat.id
    poller.stop(chat_id)
    t = get_user_translation(chat_id, update.effective_user)
    await update.message.reply_text(t("stop.stopped"))


async def cmd_resume(update: Update, _context) -> None:
    """Resume monitoring for this chat (route must be configured)."""
    chat_id = update.effective_chat.id
    success, msg = poller.resume(_context.bot, chat_id)
    await update.message.reply_text(msg, parse_mode="Markdown")


# ═══════════════════ /setroute Conversation ══════════════════════════

async def setroute_entry(update: Update, context) -> int:
    """Start route selection — show 'from' station keyboard."""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    # Initialise station cache if needed
    if not _stations:
        await load_stations()

    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    text = t("route.select_from")
    reply_markup = build_station_keyboard("from", 0, t)

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    return FROM_STATION


async def from_station_handler(update: Update, context) -> Optional[int]:
    """Handle 'from' station selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("route.cancelled"))
        return ConversationHandler.END

    if data.startswith("page:from:"):
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("from", page, t)
        )
        return FROM_STATION

    if data.startswith("from:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            chat_id = update.effective_chat.id
            t = get_user_translation(chat_id, update.effective_user)
            await query.edit_message_text(t("route.station_not_found"))
            return ConversationHandler.END
        context.user_data["from_code"] = code
        context.user_data["from_station"] = station.get("stationName", "?")

        # Show 'to' station keyboard
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        text = t("route.from_selected", station_name=station.get("stationName"))
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=build_station_keyboard("to", 0, t))
        return TO_STATION

    return FROM_STATION


async def to_station_handler(update: Update, context) -> Optional[int]:
    """Handle 'to' station selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("route.cancelled"))
        return ConversationHandler.END

    if data.startswith("page:to:"):
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("to", page, t)
        )
        return TO_STATION

    if data.startswith("to:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            chat_id = update.effective_chat.id
            t = get_user_translation(chat_id, update.effective_user)
            await query.edit_message_text(t("route.station_not_found"))
            return ConversationHandler.END

        from_name = context.user_data.get("from_station", "?")
        from_code = context.user_data.get("from_code", "")

        if from_code == code:
            chat_id = update.effective_chat.id
            t = get_user_translation(chat_id, update.effective_user)
            await query.edit_message_text(
                t("route.same_station"),
                reply_markup=build_station_keyboard("to", 0, t),
            )
            return TO_STATION

        to_name = station.get("stationName", "?")
        to_code = str(station.get("code", ""))

        # Save route
        chat_id = update.effective_chat.id
        config = load_config(chat_id)
        config["from_station"] = from_name
        config["from_station_code"] = from_code
        config["to_station"] = to_name
        config["to_station_code"] = to_code
        save_config(chat_id, config)

        context.user_data.clear()

        t = get_user_translation(chat_id, update.effective_user)
        msg = t("route.saved", from_name=from_name, to_name=to_name)
        await query.edit_message_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    return TO_STATION


# ═══════════════════ /setdate Conversation ═══════════════════════════

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def setdate_entry(update: Update, _context) -> int:
    """Ask user for a date."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    await update.message.reply_text(
        t("date.prompt"),
        parse_mode="Markdown",
    )
    return WAITING_DATE


async def setdate_handler(update: Update, context) -> Optional[int]:
    """Parse and save the date."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)

    # Parse relative dates
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if text.lower() == "today":
        date = now
    elif text.lower() == "tomorrow":
        date = now + timedelta(days=1)
    elif text.startswith("+"):
        try:
            days = int(text[1:])
            date = now + timedelta(days=days)
        except ValueError:
            await update.message.reply_text(t("date.invalid_format"), parse_mode="Markdown")
            return WAITING_DATE
    elif DATE_RE.match(text):
        try:
            date = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date < now:
                await update.message.reply_text(t("date.past_date"))
                return WAITING_DATE
        except ValueError:
            await update.message.reply_text(t("date.invalid_date"), parse_mode="Markdown")
            return WAITING_DATE
    else:
        await update.message.reply_text(t("date.unrecognised"), parse_mode="Markdown")
        return WAITING_DATE

    date_str = date.strftime("%Y-%m-%d")
    config = load_config(chat_id)
    config["date"] = date_str
    save_config(chat_id, config)

    await update.message.reply_text(t("date.set", date=date_str), parse_mode="Markdown")

    # If config is now complete, start polling automatically
    if is_config_complete(config):
        poller.start(context.bot, chat_id)
        await update.message.reply_text(t("date.monitoring_started"))
    else:
        await update.message.reply_text(t("date.incomplete_hint"))

    return ConversationHandler.END


# ═══════════════════ /setclass Conversation ══════════════════════════

CLASS_OPTIONS = [("Any class", "Any"), ("Business", "Business"), ("Class I", "I"), ("Class II", "II")]


async def setclass_entry(update: Update, _context) -> int:
    """Show class selection keyboard."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"class:{val}") for name, val in CLASS_OPTIONS[:2]],
        [InlineKeyboardButton(name, callback_data=f"class:{val}") for name, val in CLASS_OPTIONS[2:]],
        [InlineKeyboardButton(t("button.cancel"), callback_data="cancel")],
    ]
    await update.message.reply_text(
        t("class.select"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_CLASS


async def setclass_handler(update: Update, context) -> Optional[int]:
    """Save the selected class."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("class.cancelled"))
        return ConversationHandler.END

    if data.startswith("class:"):
        cls = data.split(":", 1)[1]
        chat_id = update.effective_chat.id
        config = load_config(chat_id)
        config["seat_class"] = cls
        save_config(chat_id, config)

        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("class.set", class_name=cls), parse_mode="Markdown")

        # If config is now complete, start polling
        if is_config_complete(config):
            poller.start(context.bot, chat_id)
            await query.message.reply_text(t("class.monitoring_started"))
        else:
            await query.message.reply_text(t("class.incomplete_hint"))
        return ConversationHandler.END

    return WAITING_CLASS


async def cancel_handler(update: Update, _context) -> int:
    """Generic cancel fallback for all conversation handlers."""
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("route.cancelled"))
    else:
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await update.message.reply_text(t("route.cancelled"))
    return ConversationHandler.END


# ═══════════════════════ /lang Command ═══════════════════════════════════


async def cmd_lang(update: Update, context) -> None:
    """Show or change the user's language preference."""
    chat_id = update.effective_chat.id
    from config_manager import load_config, save_config  # noqa: PLC0415
    from i18n import SUPPORTED_LANGUAGES, get_translation, get_user_language

    current_lang = get_user_language(chat_id, update.effective_user)
    args = context.args

    if not args:
        # Show current language
        t = get_translation(current_lang)
        lang_display = {"en": "English", "ru": "Русский"}.get(current_lang, current_lang)
        await update.message.reply_text(
            t("lang.current", lang=current_lang, lang_name=lang_display),
            parse_mode="Markdown",
        )
        return

    code = args[0].lower().strip()

    if code not in SUPPORTED_LANGUAGES:
        # Invalid language code
        t = get_translation(current_lang)
        await update.message.reply_text(
            t("lang.invalid", code=code),
            parse_mode="Markdown",
        )
        return

    # Valid language code — update and confirm in the new language
    config = load_config(chat_id)
    config["language"] = code
    save_config(chat_id, config)

    # Bust the in-memory cache so subsequent lookups use the new language
    from i18n import clear_user_lang_cache
    clear_user_lang_cache()

    t = get_translation(code)
    lang_display = {"en": "English", "ru": "Русский"}.get(code, code)
    await update.message.reply_text(
        t("lang.changed", lang=code, lang_name=lang_display),
        parse_mode="Markdown",
    )


# ═══════════════════ Fallback text handler ═══════════════════════════

async def fallback_handler(update: Update, _context) -> None:
    """Handle unrecognised commands / text."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    await update.message.reply_text(t("fallback.unrecognised"))


# ═══════════════════ Main ════════════════════════════════════════════

async def post_init(application: Application) -> None:
    """Run after Application initialisation — load station cache, init i18n, and register bot commands."""
    await load_stations()

    # Pre-cache both EN and RU translations
    from i18n import get_translation
    t_en = get_translation("en")
    t_ru = get_translation("ru")
    logger.info("i18n loaded: en (%d keys), ru (%d keys)", t_en.key_count, t_ru.key_count)

    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot and show help"),
            BotCommand("lang", "Change language / Сменить язык"),
            BotCommand("setroute", "Set departure and arrival stations"),
            BotCommand("setdate", "Set travel date"),
            BotCommand("setclass", "Select seat class"),
            BotCommand("resume", "Resume paused monitoring"),
            BotCommand("status", "Show current configuration and status"),
        ]
    )
    logger.info("Bot commands registered with Telegram API")


def main() -> None:
    """Build and run the bot."""
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── Simple commands ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))

    # ── /setroute Conversation ──
    setroute_conv = ConversationHandler(
        entry_points=[CommandHandler("setroute", setroute_entry)],
        states={
            FROM_STATION: [CallbackQueryHandler(from_station_handler)],
            TO_STATION: [CallbackQueryHandler(to_station_handler)],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel$"),
                   CommandHandler("setroute", setroute_entry)],
        map_to_parent={ConversationHandler.END: ConversationHandler.END},
    )
    app.add_handler(setroute_conv)

    # ── /setdate Conversation ──
    setdate_conv = ConversationHandler(
        entry_points=[CommandHandler("setdate", setdate_entry)],
        states={
            WAITING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setdate_handler),
                CallbackQueryHandler(cancel_handler, pattern="^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("setdate", setdate_entry)],
    )
    app.add_handler(setdate_conv)

    # ── /setclass Conversation ──
    setclass_conv = ConversationHandler(
        entry_points=[CommandHandler("setclass", setclass_entry)],
        states={
            WAITING_CLASS: [CallbackQueryHandler(setclass_handler)],
        },
        fallbacks=[CallbackQueryHandler(cancel_handler, pattern="^cancel$"),
                   CommandHandler("setclass", setclass_entry)],
    )
    app.add_handler(setclass_conv)

    # ── Fallback ──
    app.add_handler(MessageHandler(filters.COMMAND, fallback_handler))

    # ── Start ──
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
