"""Tests for bot.py — Telegram bot handlers, station loading, date parsing.

Uses mocked PTB Update objects to test command handlers and conversation
flows without a real Telegram connection.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# bot.py reads BOT_TOKEN from env at import time; set a dummy token
os.environ["BOT_TOKEN"] = "0000000000:TEST_TOKEN_FOR_UNIT_TESTS"


# ═══════════════════════ Helpers ═══════════════════════════════════════


def make_update(chat_id=12345, text="", callback_data=None, message_id=1):
    """Create a mock PTB Update."""
    from telegram import Update, Message, Chat, User, CallbackQuery

    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 67890

    if callback_data is not None:
        update.callback_query = MagicMock(spec=CallbackQuery)
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_reply_markup = AsyncMock()
        update.callback_query.data = callback_data
        update.callback_query.message = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()
        update.callback_query.message.chat_id = chat_id
        update.callback_query.message.message_id = message_id

    update.message = MagicMock(spec=Message)
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat_id = chat_id
    update.message.from_user = update.effective_user

    return update


def make_context(mock_bot=None):
    """Create a mock CallbackContext with a Bot."""
    from telegram.ext import CallbackContext

    ctx = MagicMock(spec=CallbackContext)
    if mock_bot is None:
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock()
    else:
        ctx.bot = mock_bot
    ctx.user_data = {}
    return ctx


# ═══════════════════════ Station Loading ═══════════════════════════════


class TestStationLoading:

    def test_stations_fallback_on_api_failure(self):
        """When API fails, bot should fall back to hardcoded station list."""
        import bot
        original = list(bot._stations)

        with patch("bot.get_stations", AsyncMock(return_value=None)):
            import asyncio
            asyncio.run(bot.load_stations())

        assert len(bot._stations) == len(bot.FALLBACK_STATIONS)

        # Restore
        bot._stations = original

    @pytest.mark.asyncio
    async def test_stations_index_built_correctly(self):
        import bot
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
            {"code": "57151", "stationName": "Batumi", "isPopular": True},
        ]
        bot._station_index = {}
        for s in bot._stations:
            bot._station_index[str(s.get("code", ""))] = s

        assert bot._station_index["56014"]["stationName"] == "Tbilisi"
        assert "56014" in bot._station_index


# ═══════════════════════ Station Keyboard ══════════════════════════════


class TestStationKeyboard:

    def setup_method(self):
        import bot
        bot._stations = [
            {"code": str(56000 + i), "stationName": f"Station{i}", "isPopular": i < 3}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

    def test_pagination_first_page(self):
        import bot
        markup = bot.build_station_keyboard("from", 0)
        assert markup is not None
        keyboard = markup.inline_keyboard
        assert len(keyboard) >= 8  # stations per page
        # Last row should contain nav buttons and cancel
        last_row = keyboard[-1]
        assert len(last_row) == 1  # cancel
        assert "Cancel" in last_row[0].text

    def test_pagination_middle_page(self):
        import bot
        markup = bot.build_station_keyboard("from", 1)
        keyboard = markup.inline_keyboard
        # Should have prev + page + next in nav row
        nav_row = keyboard[-2]  # second to last is nav
        assert any("Prev" in b.text for b in nav_row)
        assert any("Next" in b.text for b in nav_row)

    def test_pagination_last_page(self):
        import bot
        total_pages = max(1, (len(bot._stations) + bot.STATIONS_PER_PAGE - 1) // bot.STATIONS_PER_PAGE)
        markup = bot.build_station_keyboard("from", total_pages - 1)
        keyboard = markup.inline_keyboard
        nav_row = keyboard[-2]
        assert not any("Next" in b.text for b in nav_row)
        assert any("Prev" in b.text for b in nav_row)

    def test_pagination_action_to(self):
        import bot
        markup = bot.build_station_keyboard("to", 0)
        keyboard = markup.inline_keyboard
        for row in keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("to:"):
                    assert "to:" in btn.callback_data
                    return
        pytest.fail("No 'to:' station found")


# ═══════════════════════ Date Parsing ══════════════════════════════════


class TestDateParsing:

    @pytest.mark.asyncio
    async def test_today(self):
        import bot
        update = make_update(text="today")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved_config = mock_save.call_args[0][1]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            assert saved_config["date"] == today

    @pytest.mark.asyncio
    async def test_tomorrow(self):
        import bot
        update = make_update(text="tomorrow")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved_config = mock_save.call_args[0][1]
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            assert saved_config["date"] == tomorrow

    @pytest.mark.asyncio
    async def test_plus_n_days(self):
        import bot
        update = make_update(text="+5")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved_config = mock_save.call_args[0][1]
            expected = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
            assert saved_config["date"] == expected

    @pytest.mark.asyncio
    async def test_iso_date(self):
        import bot
        update = make_update(text="2026-07-15")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved_config = mock_save.call_args[0][1]
            assert saved_config["date"] == "2026-07-15"

    @pytest.mark.asyncio
    async def test_past_date_rejected(self):
        import bot
        update = make_update(text="2020-01-01")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save:
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.WAITING_DATE  # stay in the conversation
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_date_format(self):
        import bot
        update = make_update(text="not-a-date")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save:
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.WAITING_DATE
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_plus_invalid_number(self):
        import bot
        update = make_update(text="+abc")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save:
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.WAITING_DATE
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_date_values(self):
        import bot
        update = make_update(text="2026-13-01")  # month 13
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save:
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.WAITING_DATE
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_date_today_upper_case(self):
        import bot
        update = make_update(text="TODAY")
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved_config = mock_save.call_args[0][1]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            assert saved_config["date"] == today


# ═══════════════════════ Date Auto-Starts Poller ═══════════════════════


class TestDateAutoStartsPoller:

    @pytest.mark.asyncio
    async def test_complete_config_starts_poller(self):
        import bot
        update = make_update(text="2026-07-15")
        ctx = make_context()

        with patch("bot.load_config", return_value={"some": "data"}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=True), \
             patch("bot.poller.start") as mock_poller_start:
            result = await bot.setdate_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            mock_poller_start.assert_called_once_with(ctx.bot, update.effective_chat.id)


# ═══════════════════════ Route Validation ══════════════════════════════


class TestRouteValidation:

    @pytest.mark.asyncio
    async def test_same_from_and_to_rejected(self):
        """Selecting the same station for from and to should show error."""
        import bot
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
            {"code": "57151", "stationName": "Batumi", "isPopular": True},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="to:56014")  # same as from
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"
        ctx.user_data["from_station"] = "Tbilisi"

        result = await bot.to_station_handler(update, ctx)
        # Should stay on TO_STATION state with error message
        assert result == bot.TO_STATION


# ═══════════════════════ Command Handlers ══════════════════════════════


class TestCommandHandlers:

    @pytest.mark.asyncio
    async def test_start_with_config(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        config = {
            "from_station": "Tbilisi",
            "to_station": "Batumi",
            "date": "2026-07-15",
            "seat_class": "Any",
        }
        with patch("bot.load_config", return_value=config), \
             patch("bot.poller.is_running", return_value=True):
            await bot.cmd_start(update, ctx)
            update.message.reply_text.assert_called_once()
            text = update.message.reply_text.call_args[0][0]
            assert "Tbilisi" in text
            assert "Monitoring active" in text

    @pytest.mark.asyncio
    async def test_start_without_config(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}):
            await bot.cmd_start(update, ctx)
            text = update.message.reply_text.call_args[0][0]
            assert "setroute" in text
            assert "setdate" in text

    @pytest.mark.asyncio
    async def test_status_with_config_complete(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        config = {
            "from_station": "Tbilisi",
            "to_station": "Batumi",
            "date": "2026-07-15",
            "seat_class": "Any",
        }
        with patch("bot.load_config", return_value=config), \
             patch("bot.poller.is_running", return_value=False), \
             patch("bot.is_config_complete", return_value=True):
            await bot.cmd_status(update, ctx)
            text = update.message.reply_text.call_args[0][0]
            assert "Config complete but polling not started" in text

    @pytest.mark.asyncio
    async def test_status_no_config(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}):
            await bot.cmd_status(update, ctx)
            text = update.message.reply_text.call_args[0][0]
            assert "No configuration" in text

    @pytest.mark.asyncio
    async def test_stop_calls_poller_stop(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.poller.stop") as mock_stop:
            await bot.cmd_stop(update, ctx)
            mock_stop.assert_called_once_with(12345)
            update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_calls_poller_resume(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.poller.resume", return_value=(True, "✅ OK")):
            await bot.cmd_resume(update, ctx)
            update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_handler(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        await bot.fallback_handler(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "don't understand" in text.lower()


# ═══════════════════════ Cancel Handler ════════════════════════════════


class TestCancelHandler:

    @pytest.mark.asyncio
    async def test_cancel_with_callback(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.cancel_handler(update, ctx)
        assert result == bot.ConversationHandler.END
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_without_callback(self):
        import bot
        update = make_update()
        update.callback_query = None
        ctx = make_context()

        result = await bot.cancel_handler(update, ctx)
        assert result == bot.ConversationHandler.END
        update.message.reply_text.assert_called_once()


# ═══════════════════════ Conversation: From Station ════════════════════


class TestFromStationHandler:

    @pytest.mark.asyncio
    async def test_cancel_from_station(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.from_station_handler(update, ctx)
        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_pagination_from_station(self):
        import bot
        bot._stations = [
            {"code": str(56000 + i), "stationName": f"Station{i}", "isPopular": True}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="page:from:1")
        ctx = make_context()

        result = await bot.from_station_handler(update, ctx)
        assert result == bot.FROM_STATION
        update.callback_query.edit_message_reply_markup.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_from_station(self):
        import bot
        bot._stations = [{"code": "56014", "stationName": "Tbilisi", "isPopular": True}]
        bot._station_index = {"56014": bot._stations[0]}

        update = make_update(callback_data="from:56014")
        ctx = make_context()

        result = await bot.from_station_handler(update, ctx)
        assert result == bot.TO_STATION
        assert ctx.user_data["from_code"] == "56014"
        assert ctx.user_data["from_station"] == "Tbilisi"

    @pytest.mark.asyncio
    async def test_unknown_station(self):
        import bot
        bot._stations = [{"code": "56014", "stationName": "Tbilisi", "isPopular": True}]
        bot._station_index = {"56014": bot._stations[0]}

        update = make_update(callback_data="from:99999")
        ctx = make_context()

        result = await bot.from_station_handler(update, ctx)
        assert result == bot.ConversationHandler.END


# ═══════════════════════ Conversation: To Station ══════════════════════


class TestToStationHandler:

    @pytest.mark.asyncio
    async def test_cancel_to_station(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.to_station_handler(update, ctx)
        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_pagination_to_station(self):
        import bot
        bot._stations = [
            {"code": str(56000 + i), "stationName": f"Station{i}", "isPopular": True}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="page:to:0")
        ctx = make_context()

        result = await bot.to_station_handler(update, ctx)
        assert result == bot.TO_STATION

    @pytest.mark.asyncio
    async def test_select_to_station_success(self):
        import bot
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
            {"code": "57151", "stationName": "Batumi", "isPopular": True},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="to:57151", chat_id=12345)
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"
        ctx.user_data["from_station"] = "Tbilisi"

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save:
            result = await bot.to_station_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved = mock_save.call_args[0][1]
            assert saved["from_station"] == "Tbilisi"
            assert saved["to_station"] == "Batumi"
            assert saved["from_station_code"] == "56014"
            assert saved["to_station_code"] == "57151"


# ═══════════════════════ Conversation: Set Class ═══════════════════════


class TestSetClass:

    @pytest.mark.asyncio
    async def test_cancel_class(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.setclass_handler(update, ctx)
        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_select_any_class(self):
        import bot
        update = make_update(callback_data="class:Any", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setclass_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved = mock_save.call_args[0][1]
            assert saved["seat_class"] == "Any"

    @pytest.mark.asyncio
    async def test_select_business_starts_poller(self):
        import bot
        update = make_update(callback_data="class:Business", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config"), \
             patch("bot.is_config_complete", return_value=True), \
             patch("bot.poller.start") as mock_poller_start:
            result = await bot.setclass_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            mock_poller_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_class_i(self):
        import bot
        update = make_update(callback_data="class:I", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setclass_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved = mock_save.call_args[0][1]
            assert saved["seat_class"] == "I"

    @pytest.mark.asyncio
    async def test_select_class_ii(self):
        import bot
        update = make_update(callback_data="class:II", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.is_config_complete", return_value=False):
            result = await bot.setclass_handler(update, ctx)
            assert result == bot.ConversationHandler.END
            saved = mock_save.call_args[0][1]
            assert saved["seat_class"] == "II"


# ═══════════════════════ Bot URL Building ══════════════════════════════


class TestBotUrlRegex:

    def test_date_regex_valid(self):
        import bot
        assert bot.DATE_RE.match("2026-07-15")
        assert bot.DATE_RE.match("2026-01-01")
        assert bot.DATE_RE.match("2026-12-31")

    def test_date_regex_invalid(self):
        import bot
        # DATE_RE only checks YYYY-MM-DD format, not valid calendar dates
        assert bot.DATE_RE.match("2026-13-01") is not None  # matches format (month 13 — caught later)
        assert bot.DATE_RE.match("not-a-date") is None
        assert bot.DATE_RE.match("2026-1-1") is None  # no leading zeros
        assert bot.DATE_RE.match("") is None


# ═══════════════════════ /lang Command ══════════════════════════════════


class TestLangCommand:

    @pytest.mark.asyncio
    async def test_lang_shows_current(self):
        """/lang without args shows the current language."""
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()
        ctx.args = []

        with patch("i18n.get_user_language", return_value="en"):
            await bot.cmd_lang(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "Language" in text
        assert "en" in text

    @pytest.mark.asyncio
    async def test_lang_change_to_russian(self):
        """/lang ru changes language to Russian and confirms in Russian."""
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()
        ctx.args = ["ru"]

        with patch("i18n.get_user_language", return_value="en"), \
             patch("config_manager.load_config", return_value={}), \
             patch("config_manager.save_config") as mock_save, \
             patch("i18n.clear_user_lang_cache"):
            await bot.cmd_lang(update, ctx)
        # Verify config was saved with new language
        saved = mock_save.call_args[0][1]
        assert saved["language"] == "ru"
        # Confirmation sent in Russian
        text = update.message.reply_text.call_args[0][0]
        assert "Язык изменён" in text

    @pytest.mark.asyncio
    async def test_lang_change_to_english_from_russian(self):
        """/lang en changes language to English when currently RU."""
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()
        ctx.args = ["en"]

        with patch("i18n.get_user_language", return_value="ru"), \
             patch("config_manager.load_config", return_value={"language": "ru"}), \
             patch("config_manager.save_config") as mock_save, \
             patch("i18n.clear_user_lang_cache"):
            await bot.cmd_lang(update, ctx)
        saved = mock_save.call_args[0][1]
        assert saved["language"] == "en"
        text = update.message.reply_text.call_args[0][0]
        assert "Language changed" in text

    @pytest.mark.asyncio
    async def test_lang_invalid_code(self):
        """/lang de returns an error message."""
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()
        ctx.args = ["de"]

        with patch("i18n.get_user_language", return_value="en"), \
             patch("config_manager.load_config"), \
             patch("config_manager.save_config") as mock_save, \
             patch("i18n.clear_user_lang_cache"):
            await bot.cmd_lang(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "Invalid" in text or "invalid" in text
        assert "de" in text
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_lang_case_insensitive(self):
        """/lang RU works (case-insensitive)."""
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()
        ctx.args = ["RU"]

        with patch("i18n.get_user_language", return_value="en"), \
             patch("config_manager.load_config", return_value={}), \
             patch("config_manager.save_config") as mock_save, \
             patch("i18n.clear_user_lang_cache"):
            await bot.cmd_lang(update, ctx)
        saved = mock_save.call_args[0][1]
        assert saved["language"] == "ru"
