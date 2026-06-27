"""
Telegram bot for monitoring tkt.ge train tickets.
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
from api import get_stations, init_ticket_api
from config_manager import load_config, save_config, is_config_complete

# ── logging ──────────────────────────────────────────────────────────
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

# Fallback station list if API fails
FALLBACK_STATIONS: list[dict] = [
    {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
    {"code": "57151", "stationName": "Batumi", "isPopular": True},
    {"code": "57450", "stationName": "Kutaisi Airport", "isPopular": True},
    {"code": "57290", "stationName": "Zugdidi", "isPopular": True},
    {"code": "57120", "stationName": "Kobuleti", "isPopular": True},
    {"code": "57100", "stationName": "Ozurgeti", "isPopular": True},
    {"code": "57190", "stationName": "Senaki", "isPopular": True},
    {"code": "57000", "stationName": "Samtredia", "isPopular": True},
    {"code": "57070", "stationName": "Ureki", "isPopular": False},
    {"code": "57210", "stationName": "Poti", "isPopular": True},
    {"code": "57900", "stationName": "Gori", "isPopular": False},
    {"code": "57720", "stationName": "Khashuri", "isPopular": False},
    {"code": "57600", "stationName": "Zestafoni", "isPopular": False},
    {"code": "57510", "stationName": "Rioni", "isPopular": False},
    {"code": "57030", "stationName": "Nigoiti", "isPopular": False},
    {"code": "56040", "stationName": "Mtskheta", "isPopular": False},
    {"code": "56080", "stationName": "Kaspi", "isPopular": False},
]


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


def pagination_buttons(page: int, total_pages: int, action: str) -> list[InlineKeyboardButton]:
    """Create Prev / Next / Page buttons for pagination."""
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page:{action}:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"page:{action}:{page + 1}"))
    return buttons


def build_station_keyboard(action: str, page: int = 0) -> InlineKeyboardMarkup:
    """Build a paginated inline keyboard for station selection.

    action: "from" or "to"  — embedded in callback_data for state tracking.
    """
    total = len(_stations)
    total_pages = max(1, (total + STATIONS_PER_PAGE - 1) // STATIONS_PER_PAGE)
    start = page * STATIONS_PER_PAGE
    end = min(start + STATIONS_PER_PAGE, total)

    keyboard = []
    for s in _stations[start:end]:
        name = s.get("stationName", "?")
        code = str(s.get("code", ""))
        keyboard.append([InlineKeyboardButton(name, callback_data=f"{action}:{code}")])

    nav = pagination_buttons(page, total_pages, action)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🚫 Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


# ── Conversation states ──────────────────────────────────────────────
(FROM_STATION, TO_STATION, WAITING_DATE, WAITING_CLASS) = range(4)


# ═══════════════════════ COMMAND HANDLERS ════════════════════════════

async def cmd_start(update: Update, _context) -> None:
    """Welcome message with current config summary."""
    chat_id = update.effective_chat.id
    config = load_config(chat_id)

    lines = [
        "👋 *tkt.ge Ticket Monitor*",
        "",
        "I check train ticket availability on Georgian Railway and notify you.",
        "",
    ]

    if config:
        lines.append("*Current config:*")
        lines.append(f"🚉 {config.get('from_station', '?')} → {config.get('to_station', '?')}")
        lines.append(f"📅 {config.get('date', '?')}")
        lines.append(f"💺 Class: {config.get('seat_class', 'Any')}")
        if poller.is_running(chat_id):
            lines.append("\n✅ *Monitoring active* — checking every 60 s")
        else:
            lines.append("\n⏸ *Monitoring paused*")
    else:
        lines.append("Use the commands below to set up monitoring:")
        lines.append("")

    lines.append("")
    lines.append("/setroute — pick departure & arrival stations")
    lines.append("/setdate — set travel date")
    lines.append("/setclass — pick seat class")
    lines.append("/status — show current config & polling")
    lines.append("/stop — stop monitoring")
    lines.append("/resume — resume monitoring (if route is configured)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, _context) -> None:
    """Show current config and monitoring state."""
    chat_id = update.effective_chat.id
    config = load_config(chat_id)

    lines = ["*📊 Status*", ""]

    if config:
        lines.append(f"*Route:* {config.get('from_station', '?')} → {config.get('to_station', '?')}")
        lines.append(f"*Date:* {config.get('date', '?')}")
        lines.append(f"*Class:* {config.get('seat_class', 'Any')}")
        lines.append("")

        if poller.is_running(chat_id):
            lines.append("✅ *Monitoring active* — checking every 60 s")
        elif is_config_complete(config):
            lines.append("⏸ *Config complete but polling not started*")
            lines.append("   Start with /setdate or re-send /setroute")
        else:
            lines.append("⚠️ *Config incomplete* — use /setroute, /setdate, /setclass")
    else:
        lines.append("No configuration yet.")
        lines.append("Start with /setroute")

    lines.append("")
    lines.append(f"👥 Active monitors: {poller.active_count()}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stop(update: Update, _context) -> None:
    """Stop monitoring for this chat."""
    chat_id = update.effective_chat.id
    poller.stop(chat_id)
    await update.message.reply_text(
        "🛑 Monitoring stopped. Your configuration is preserved.\n"
        "Use /setroute to restart."
    )


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

    text = "🚉 *Select departure station:*"
    reply_markup = build_station_keyboard("from", 0)

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
        await query.edit_message_text("🚫 Cancelled.")
        return ConversationHandler.END

    if data.startswith("page:from:"):
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("from", page)
        )
        return FROM_STATION

    if data.startswith("from:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            await query.edit_message_text("❌ Station not found. Try again.")
            return ConversationHandler.END
        context.user_data["from_code"] = code
        context.user_data["from_station"] = station.get("stationName", "?")

        # Show 'to' station keyboard
        text = f"🚉 *From:* {station.get('stationName')}\n\nNow select *arrival station:*"
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=build_station_keyboard("to", 0))
        return TO_STATION

    return FROM_STATION


async def to_station_handler(update: Update, context) -> Optional[int]:
    """Handle 'to' station selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        await query.edit_message_text("🚫 Cancelled.")
        return ConversationHandler.END

    if data.startswith("page:to:"):
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("to", page)
        )
        return TO_STATION

    if data.startswith("to:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            await query.edit_message_text("❌ Station not found. Try again.")
            return ConversationHandler.END

        from_name = context.user_data.get("from_station", "?")
        from_code = context.user_data.get("from_code", "")

        if from_code == code:
            await query.edit_message_text(
                "⚠️ Departure and arrival must be different. Try again.",
                reply_markup=build_station_keyboard("to", 0),
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

        msg = (
            f"✅ *Route saved:* {from_name} → {to_name}\n\n"
            "Next steps:\n"
            "  /setdate — set travel date\n"
            "  /setclass — choose seat class"
        )
        await query.edit_message_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    return TO_STATION


# ═══════════════════ /setdate Conversation ═══════════════════════════

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def setdate_entry(update: Update, _context) -> int:
    """Ask user for a date."""
    await update.message.reply_text(
        "📅 *Enter travel date*\n\n"
        "Format: `YYYY-MM-DD`\n"
        "Examples: `2026-07-15`, `today`, `tomorrow`, `+3` (days from now)",
        parse_mode="Markdown",
    )
    return WAITING_DATE


async def setdate_handler(update: Update, context) -> Optional[int]:
    """Parse and save the date."""
    text = update.message.text.strip()

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
            await update.message.reply_text("❌ Invalid format. Use `+3` or `YYYY-MM-DD`.", parse_mode="Markdown")
            return WAITING_DATE
    elif DATE_RE.match(text):
        try:
            date = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date < now:
                await update.message.reply_text("❌ Date is in the past. Try again.")
                return WAITING_DATE
        except ValueError:
            await update.message.reply_text("❌ Invalid date. Use format `YYYY-MM-DD`.", parse_mode="Markdown")
            return WAITING_DATE
    else:
        await update.message.reply_text(
            "❌ I don't understand. Use `YYYY-MM-DD`, `today`, or `tomorrow`.",
            parse_mode="Markdown",
        )
        return WAITING_DATE

    date_str = date.strftime("%Y-%m-%d")
    chat_id = update.effective_chat.id
    config = load_config(chat_id)
    config["date"] = date_str
    save_config(chat_id, config)

    await update.message.reply_text(f"✅ Date set to *{date_str}*", parse_mode="Markdown")

    # If config is now complete, start polling automatically
    if is_config_complete(config):
        poller.start(context.bot, chat_id)
        await update.message.reply_text("✅ Monitoring started — checking every 60 s!")
    else:
        await update.message.reply_text(
            "Make sure to also set:\n"
            "  /setroute — route\n"
            "  /setclass — seat class\n"
        )

    return ConversationHandler.END


# ═══════════════════ /setclass Conversation ══════════════════════════

CLASS_OPTIONS = [("Any class", "Any"), ("Business", "Business"), ("Class I", "I"), ("Class II", "II")]


async def setclass_entry(update: Update, _context) -> int:
    """Show class selection keyboard."""
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"class:{val}") for name, val in CLASS_OPTIONS[:2]],
        [InlineKeyboardButton(name, callback_data=f"class:{val}") for name, val in CLASS_OPTIONS[2:]],
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel")],
    ]
    await update.message.reply_text(
        "💺 *Select seat class:*",
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
        await query.edit_message_text("🚫 Cancelled.")
        return ConversationHandler.END

    if data.startswith("class:"):
        cls = data.split(":", 1)[1]
        chat_id = update.effective_chat.id
        config = load_config(chat_id)
        config["seat_class"] = cls
        save_config(chat_id, config)

        await query.edit_message_text(f"✅ Seat class set to *{cls}*", parse_mode="Markdown")

        # If config is now complete, start polling
        if is_config_complete(config):
            poller.start(context.bot, chat_id)
            await query.message.reply_text("✅ Monitoring started — checking every 60 s!")
        else:
            await query.message.reply_text(
                "Make sure to also set:\n"
                "  /setroute — route\n"
                "  /setdate — travel date\n"
            )
        return ConversationHandler.END

    return WAITING_CLASS


async def cancel_handler(update: Update, _context) -> int:
    """Generic cancel fallback for all conversation handlers."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("🚫 Cancelled.")
    else:
        await update.message.reply_text("🚫 Cancelled.")
    return ConversationHandler.END


# ═══════════════════ Fallback text handler ═══════════════════════════

async def fallback_handler(update: Update, _context) -> None:
    """Handle unrecognised commands / text."""
    await update.message.reply_text(
        "I don't understand that command.\n"
        "Try /start to see available commands."
    )


# ═══════════════════ Main ════════════════════════════════════════════

async def post_init(application: Application) -> None:
    """Run after Application initialisation — load station cache and register bot commands."""
    init_ticket_api()  # initialise TICKET_SOURCE factory before any API calls
    await load_stations()
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start the bot and show help"),
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
