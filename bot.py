"""
Telegram bot for monitoring tre.ge train tickets.
Uses a multi-step /start wizard and /stop. All previous commands removed.
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
from config_manager import delete_config, load_config, is_config_complete, save_config
from i18n import (
    SUPPORTED_LANGUAGES,
    get_user_language,
    get_user_translation,
    set_user_language,
    translate_station_name,
)
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

# Quick-pick station codes
TBILISI_CODE = "56014"
BATUMI_CODE = "57151"


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


def station_name_for_code(code: str, lang: str = "en", station_name: Optional[str] = None) -> str:
    """Return the translated display name for a station code, or the code itself.

    When *station_name* (the API's ``stationName``) is provided, it is used
    as a fallback when no hardcoded translation exists for the code.
    """
    return translate_station_name(int(code), lang, fallback=station_name)


# ── Paginated keyboard (all stations, excluding quick-picks) ─────────

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
    """Build a paginated inline keyboard for station selection (wizard).

    action: "wiz_from" or "wiz_to" — embedded in callback_data for state tracking.
    Excludes Tbilisi and Batumi (they are shown as quick-picks in the initial view).
    """
    # Filter out quick-pick stations from paginated list
    filtered = [s for s in _stations
                if str(s.get("code", "")) not in (TBILISI_CODE, BATUMI_CODE)]

    total = len(filtered)
    total_pages = max(1, (total + STATIONS_PER_PAGE - 1) // STATIONS_PER_PAGE)
    start = page * STATIONS_PER_PAGE
    end = min(start + STATIONS_PER_PAGE, total)

    lang = t.lang if t else "en"
    cancel_label = t("button.cancel") if t else "🚫 Cancel"

    keyboard = []
    for s in filtered[start:end]:
        code = str(s.get("code", ""))
        name = translate_station_name(int(code), lang, fallback=s.get("stationName")) if code else s.get("stationName", "?")
        keyboard.append([InlineKeyboardButton(name, callback_data=f"{action}:{code}")])

    nav = pagination_buttons(page, total_pages, action, t)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(cancel_label, callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


# ── Wizard step keyboards ────────────────────────────────────────────

def build_date_keyboard(t) -> InlineKeyboardMarkup:
    """Inline keyboard for date selection step."""
    keyboard = [
        [
            InlineKeyboardButton(t("wizard.date_today_btn"), callback_data="wiz_date:today"),
            InlineKeyboardButton(t("wizard.date_tomorrow_btn"), callback_data="wiz_date:tomorrow"),
        ],
        [InlineKeyboardButton(t("wizard.date_custom_btn"), callback_data="wiz_date:custom")],
        [InlineKeyboardButton(t("button.cancel"), callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_quick_station_keyboard(action: str, t) -> InlineKeyboardMarkup:
    """Inline keyboard with Tbilisi / Batumi quick-picks + 'All stations'."""
    lang = t.lang
    tbilisi_fallback = _station_index.get(TBILISI_CODE, {}).get("stationName")
    batumi_fallback = _station_index.get(BATUMI_CODE, {}).get("stationName")
    tbilisi_name = translate_station_name(int(TBILISI_CODE), lang, fallback=tbilisi_fallback)
    batumi_name = translate_station_name(int(BATUMI_CODE), lang, fallback=batumi_fallback)
    keyboard = [
        [
            InlineKeyboardButton(tbilisi_name, callback_data=f"{action}:{TBILISI_CODE}"),
            InlineKeyboardButton(batumi_name, callback_data=f"{action}:{BATUMI_CODE}"),
        ],
        [InlineKeyboardButton(t("wizard.station_all_btn"), callback_data=f"{action}:all")],
        [InlineKeyboardButton(t("button.cancel"), callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_class_keyboard(t) -> InlineKeyboardMarkup:
    """Inline keyboard for seat class selection."""
    keyboard = [
        [
            InlineKeyboardButton(t("wizard.class_any_btn"), callback_data="wiz_class:Any"),
            InlineKeyboardButton(t("wizard.class_business_btn"), callback_data="wiz_class:Business"),
        ],
        [
            InlineKeyboardButton(t("wizard.class_i_btn"), callback_data="wiz_class:I"),
            InlineKeyboardButton(t("wizard.class_ii_btn"), callback_data="wiz_class:II"),
        ],
        [InlineKeyboardButton(t("button.cancel"), callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ── Conversation states ──────────────────────────────────────────────
(DATE_SELECT, WAITING_CUSTOM_DATE, DEPARTURE_SELECT, ARRIVAL_SELECT, CLASS_SELECT) = range(5)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ═══════════════════════ /start WIZARD ════════════════════════════════

async def cmd_start(update: Update, context) -> int:
    """Entry point: begin the setup wizard."""
    # Clear any previous wizard state
    context.user_data.clear()

    # Initialise station cache if needed
    if not _stations:
        await load_stations()

    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    text = t("wizard.date_select")
    reply_markup = build_date_keyboard(t)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    return DATE_SELECT


async def wizard_date_handler(update: Update, context) -> int:
    """Handle date selection: Today, Tomorrow, or Custom."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        return await _wizard_cancel(update)

    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    if data == "wiz_date:today":
        date_str = now.strftime("%Y-%m-%d")
        context.user_data["date"] = date_str
        await query.edit_message_text(
            t("wizard.date_today_set", date=date_str),
            parse_mode="Markdown",
        )
        return await _show_departure(update, context)

    if data == "wiz_date:tomorrow":
        date_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        context.user_data["date"] = date_str
        await query.edit_message_text(
            t("wizard.date_tomorrow_set", date=date_str),
            parse_mode="Markdown",
        )
        return await _show_departure(update, context)

    if data == "wiz_date:custom":
        # Ask user to type a date
        await query.edit_message_text(
            t("wizard.date_custom_prompt"),
            parse_mode="Markdown",
        )
        return WAITING_CUSTOM_DATE

    return DATE_SELECT


async def wizard_custom_date_handler(update: Update, context) -> int:
    """Parse custom date text input."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    if DATE_RE.match(text):
        try:
            date = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date < now:
                await update.message.reply_text(t("wizard.date_past"), parse_mode="Markdown")
                return WAITING_CUSTOM_DATE
        except ValueError:
            await update.message.reply_text(t("wizard.date_invalid"), parse_mode="Markdown")
            return WAITING_CUSTOM_DATE
    else:
        await update.message.reply_text(t("wizard.date_invalid"), parse_mode="Markdown")
        return WAITING_CUSTOM_DATE

    date_str = date.strftime("%Y-%m-%d")
    context.user_data["date"] = date_str
    await update.message.reply_text(
        t("wizard.date_set", date=date_str),
        parse_mode="Markdown",
    )
    return await _show_departure(update, context)


async def _show_departure(update: Update, context) -> int:
    """Show departure station selection (called after date is set)."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    text = t("wizard.select_departure")
    reply_markup = build_quick_station_keyboard("wiz_from", t)

    # If triggered from a callback query, edit the existing message
    query = update.callback_query
    if query:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    return DEPARTURE_SELECT


async def wizard_departure_handler(update: Update, context) -> int:
    """Handle departure station selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        return await _wizard_cancel(update)

    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)

    # "All stations" → show paginated list
    if data == "wiz_from:all":
        await query.edit_message_text(
            t("wizard.select_departure"),
            parse_mode="Markdown",
            reply_markup=build_station_keyboard("wiz_from", 0, t),
        )
        return DEPARTURE_SELECT

    # Pagination
    if data.startswith("page:wiz_from:"):
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("wiz_from", page, t),
        )
        return DEPARTURE_SELECT

    # Station selected
    if data.startswith("wiz_from:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            await query.edit_message_text(t("wizard.station_not_found"))
            return DEPARTURE_SELECT
        context.user_data["from_code"] = code
        # Keep the English name for storage (canonical key)
        context.user_data["from_station"] = station.get("stationName", "?")
        return await _show_arrival(update, context, code, station.get("stationName", "?"))

    return DEPARTURE_SELECT


async def _show_arrival(update: Update, context,
                        from_code: str = "", from_name: str = "") -> int:
    """Show arrival station selection."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    # Translate the station name for display, falling back to the API name
    code_int = int(from_code) if from_code else 0
    name = translate_station_name(
        code_int,
        t.lang,
        fallback=from_name or None,
    )
    text = t("wizard.from_selected", station_name=name)
    reply_markup = build_quick_station_keyboard("wiz_to", t)

    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=reply_markup,
    )
    return ARRIVAL_SELECT


async def wizard_arrival_handler(update: Update, context) -> int:
    """Handle arrival station selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        return await _wizard_cancel(update)

    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)

    # "All stations" → show paginated list
    if data == "wiz_to:all":
        await query.edit_message_text(
            t("wizard.select_arrival"),
            parse_mode="Markdown",
            reply_markup=build_station_keyboard("wiz_to", 0, t),
        )
        return ARRIVAL_SELECT

    # Pagination
    if data.startswith("page:wiz_to:"):
        page = int(data.split(":")[2])
        await query.edit_message_reply_markup(
            reply_markup=build_station_keyboard("wiz_to", page, t),
        )
        return ARRIVAL_SELECT

    # Station selected
    if data.startswith("wiz_to:"):
        code = data.split(":", 1)[1]
        station = _station_index.get(code)
        if not station:
            await query.edit_message_text(t("wizard.station_not_found"))
            return ARRIVAL_SELECT

        # Same-station validation
        from_code = context.user_data.get("from_code", "")
        if from_code == code:
            await query.edit_message_text(
                t("wizard.station_same"),
                reply_markup=build_quick_station_keyboard("wiz_to", t),
            )
            return ARRIVAL_SELECT

        context.user_data["to_code"] = code
        # Keep the English name for storage (canonical key)
        context.user_data["to_station"] = station.get("stationName", "?")

        # Save route to config — store English canonical names
        config = load_config(chat_id)
        config["from_station"] = context.user_data["from_station"]
        config["from_station_code"] = context.user_data["from_code"]
        config["to_station"] = context.user_data["to_station"]
        config["to_station_code"] = code
        config["date"] = context.user_data.get("date", "")
        save_config(chat_id, config)

        # Confirm route and proceed to class selection — translate for display
        from_name = translate_station_name(
            int(context.user_data.get("from_code", 0)),
            t.lang,
            fallback=context.user_data.get("from_station"),
        )
        to_name = translate_station_name(
            int(code),
            t.lang,
            fallback=station.get("stationName"),
        )
        await query.edit_message_text(
            t("wizard.route_saved", from_name=from_name, to_name=to_name),
            parse_mode="Markdown",
        )
        return await _show_class(update, context)

    return ARRIVAL_SELECT


async def _show_class(update: Update, context) -> int:
    """Show class selection step."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    text = t("wizard.select_class")
    reply_markup = build_class_keyboard(t)

    await update.callback_query.message.reply_text(
        text, parse_mode="Markdown", reply_markup=reply_markup,
    )
    return CLASS_SELECT


async def wizard_class_handler(update: Update, context) -> int:
    """Handle class selection — final step. Save config and start monitoring."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel":
        return await _wizard_cancel(update)

    if data.startswith("wiz_class:"):
        cls = data.split(":", 1)[1]
        chat_id = update.effective_chat.id
        config = load_config(chat_id)
        config["seat_class"] = cls
        save_config(chat_id, config)

        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(
            t("wizard.class_set", class_name=cls),
            parse_mode="Markdown",
        )

        # Start monitoring
        poller.start(context.bot, chat_id)
        await query.message.reply_text(
            t("wizard.monitoring_started"),
            parse_mode="Markdown",
        )

        context.user_data.clear()
        return ConversationHandler.END

    return CLASS_SELECT


async def _wizard_cancel(update: Update) -> int:
    """Cancel the wizard and clean up."""
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = update.effective_chat.id
        t = get_user_translation(chat_id, update.effective_user)
        await query.edit_message_text(t("wizard.cancelled"))
    return ConversationHandler.END


# ═══════════════════════ /lang Command ════════════════════════════════

async def cmd_lang(update: Update, context) -> None:
    """Set the user's interface language: /lang en or /lang ru."""
    chat_id = update.effective_chat.id

    # Parse the language code from the command text
    try:
        args = (update.message.text or "").strip().split()
        if len(args) != 2:
            raise ValueError
        requested = args[1]
    except (ValueError, IndexError):
        supported_list = ", ".join(sorted(SUPPORTED_LANGUAGES))
        await update.message.reply_text(
            f"⚠️ Usage: /lang <code>\n"
            f"Supported: {supported_list}\n"
            f"Examples: /lang en, /lang ru"
        )
        return

    try:
        new_lang = set_user_language(chat_id, requested)
    except ValueError:
        supported_list = ", ".join(sorted(SUPPORTED_LANGUAGES))
        await update.message.reply_text(
            f"❌ Unsupported language '{requested}'.\n"
            f"Supported: {supported_list}"
        )
        return

    # Switch to the new language for the response
    t = get_user_translation(chat_id, update.effective_user)
    language_name = "English" if new_lang == "en" else "Русский"
    await update.message.reply_text(
        t("lang.set_success", language=language_name)
    )


# ═══════════════════════ /stop Command ════════════════════════════════

async def cmd_stop(update: Update, _context) -> None:
    """Stop monitoring and clear all configuration."""
    chat_id = update.effective_chat.id
    poller.stop(chat_id)
    delete_config(chat_id)
    t = get_user_translation(chat_id, update.effective_user)
    await update.message.reply_text(t("stop.stopped"))


# ═══════════════════════ Fallback ═════════════════════════════════════

async def fallback_handler(update: Update, _context) -> None:
    """Handle unrecognised commands / text."""
    chat_id = update.effective_chat.id
    t = get_user_translation(chat_id, update.effective_user)
    await update.message.reply_text(t("fallback.unrecognised"))


# ═══════════════════════ Main ════════════════════════════════════════

async def post_init(application: Application) -> None:
    """Run after Application initialisation — load station cache and register bot commands."""
    await load_stations()

    # Pre-cache both EN and RU translations
    from i18n import get_translation  # noqa: PLC0415
    t_en = get_translation("en")
    t_ru = get_translation("ru")
    logger.info("i18n loaded: en (%d keys), ru (%d keys)", t_en.key_count, t_ru.key_count)

    await application.bot.set_my_commands(
        [
            BotCommand("start", "Start ticket monitoring setup wizard"),
            BotCommand("stop", "Stop monitoring and clear configuration"),
            BotCommand("lang", "Set interface language (en / ru)"),
        ]
    )
    logger.info("Bot commands registered with Telegram API")


def main() -> None:
    """Build and run the bot."""
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── /start wizard Conversation ──
    wizard_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            DATE_SELECT: [CallbackQueryHandler(wizard_date_handler)],
            WAITING_CUSTOM_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_custom_date_handler),
            ],
            DEPARTURE_SELECT: [CallbackQueryHandler(wizard_departure_handler)],
            ARRIVAL_SELECT: [CallbackQueryHandler(wizard_arrival_handler)],
            CLASS_SELECT: [CallbackQueryHandler(wizard_class_handler)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )
    app.add_handler(wizard_conv)

    # ── /stop ──
    app.add_handler(CommandHandler("stop", cmd_stop))

    # ── /lang ──
    app.add_handler(CommandHandler("lang", cmd_lang))

    # ── Fallback ──
    app.add_handler(MessageHandler(filters.COMMAND, fallback_handler))

    # ── Start ──
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
