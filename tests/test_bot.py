"""
Tests for bot.py — Telegram bot handlers, wizard flow, station loading, and stop.

Uses mocked PTB Update objects to test command handlers and conversation
flows without a real Telegram connection.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# bot.py reads BOT_TOKEN from env at import time; set a dummy token
os.environ["BOT_TOKEN"] = "0000000:TEST_TOKEN_FOR_UNIT_TESTS"


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
        # Use stations that do NOT include Tbilisi/Batumi so they're not filtered out
        bot._stations = [
            {"code": str(57000 + i), "stationName": f"Station{i}", "isPopular": i < 3}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

    def test_pagination_first_page(self):
        import bot
        markup = bot.build_station_keyboard("wiz_from", 0)
        assert markup is not None
        keyboard = markup.inline_keyboard
        assert len(keyboard) >= 8  # stations per page
        # Last row should contain cancel
        last_row = keyboard[-1]
        assert len(last_row) == 1
        assert "Cancel" in last_row[0].text

    def test_pagination_middle_page(self):
        import bot
        markup = bot.build_station_keyboard("wiz_from", 1)
        keyboard = markup.inline_keyboard
        # Should have prev + page + next in nav row
        nav_row = keyboard[-2]  # second to last is nav
        assert any("Prev" in b.text for b in nav_row)
        assert any("Next" in b.text for b in nav_row)

    def test_pagination_last_page(self):
        import bot
        total_pages = max(1, (len(bot._stations) + bot.STATIONS_PER_PAGE - 1) // bot.STATIONS_PER_PAGE)
        markup = bot.build_station_keyboard("wiz_from", total_pages - 1)
        keyboard = markup.inline_keyboard
        nav_row = keyboard[-2]
        assert not any("Next" in b.text for b in nav_row)
        assert any("Prev" in b.text for b in nav_row)

    def test_pagination_action_to(self):
        import bot
        markup = bot.build_station_keyboard("wiz_to", 0)
        keyboard = markup.inline_keyboard
        for row in keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("wiz_to:"):
                    assert "wiz_to:" in btn.callback_data
                    return
        pytest.fail("No 'wiz_to:' station found")

    def test_quick_pick_stations_filtered_from_paginated(self):
        """Tbilisi and Batumi should not appear in the paginated keyboard."""
        import bot
        # Include Tbilisi and Batumi in stations list
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
            {"code": "57151", "stationName": "Batumi", "isPopular": True},
            {"code": "99999", "stationName": "TestStation", "isPopular": True},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        markup = bot.build_station_keyboard("wiz_from", 0)
        keyboard = markup.inline_keyboard
        texts = [btn.text for row in keyboard for btn in row]
        assert "Tbilisi" not in texts
        assert "Batumi" not in texts
        assert "TestStation" in texts  # API stationName used as fallback for unknown code

    def test_no_numeric_codes_in_keyboard(self):
        """Station keyboard buttons should never display raw numeric codes."""
        import bot
        # Mix of known and unknown codes
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi", "isPopular": True},
            {"code": "99999", "stationName": "Custom Station", "isPopular": False},
            {"code": "88888", "stationName": "Another Place", "isPopular": False},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        markup = bot.build_station_keyboard("wiz_from", 0)
        keyboard = markup.inline_keyboard
        for row in keyboard:
            for btn in row:
                # Skip nav/cancel buttons
                if btn.callback_data in ("noop", "cancel") or btn.callback_data and btn.callback_data.startswith("page:"):
                    continue
                # Station buttons should show names, not numeric codes
                assert not btn.text.isdigit(), (
                    f"Button '{btn.text}' appears to be a numeric code — "
                    f"should be a station name"
                )


# ═══════════════════════ Date Keyboard ═════════════════════════════════


class TestDateKeyboard:

    def test_date_keyboard_structure(self):
        import bot
        t = MagicMock()
        t.side_effect = lambda key: {
            "wizard.date_today_btn": "📅 Today",
            "wizard.date_tomorrow_btn": "📅 Tomorrow",
            "wizard.date_custom_btn": "✏️ Custom date...",
            "button.cancel": "🚫 Cancel",
        }.get(key, key)

        markup = bot.build_date_keyboard(t)
        keyboard = markup.inline_keyboard
        assert len(keyboard) == 3  # 2 date rows + cancel
        assert keyboard[0][0].callback_data == "wiz_date:today"
        assert keyboard[0][1].callback_data == "wiz_date:tomorrow"
        assert keyboard[1][0].callback_data == "wiz_date:custom"
        assert keyboard[2][0].callback_data == "cancel"


# ═══════════════════════ Quick Station Keyboard ════════════════════════


class TestQuickStationKeyboard:

    def test_quick_station_keyboard_structure(self):
        import bot
        t = MagicMock()
        t.lang = "en"
        t.side_effect = lambda key: {
            "wizard.station_tbilisi_btn": "🏛 Tbilisi",
            "wizard.station_batumi_btn": "🏖 Batumi",
            "wizard.station_all_btn": "📋 All stations...",
            "button.cancel": "🚫 Cancel",
        }.get(key, key)

        markup = bot.build_quick_station_keyboard("wiz_from", t)
        keyboard = markup.inline_keyboard
        assert len(keyboard) == 3
        assert keyboard[0][0].callback_data == "wiz_from:56014"
        assert keyboard[0][1].callback_data == "wiz_from:57151"
        assert keyboard[1][0].callback_data == "wiz_from:all"
        assert keyboard[2][0].callback_data == "cancel"

    def test_quick_station_keyboard_uses_api_fallback(self):
        """build_quick_station_keyboard passes API stationName as fallback."""
        import bot
        # Set up station_index with API names
        bot._stations = [
            {"code": "56014", "stationName": "Tbilisi Central", "isPopular": True},
            {"code": "57151", "stationName": "Batumi Seaside", "isPopular": True},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        # Quick-pick codes ARE in STATION_NAMES, so fallback is ignored
        # But the call still demonstrates fallback passthrough
        t = MagicMock()
        t.lang = "en"
        t.side_effect = lambda key: {
            "wizard.station_tbilisi_btn": "🏛 Tbilisi",
            "wizard.station_batumi_btn": "🏖 Batumi",
            "wizard.station_all_btn": "📋 All stations...",
            "button.cancel": "🚫 Cancel",
        }.get(key, key)

        with patch("bot.translate_station_name", wraps=bot.translate_station_name) as mock_tsn:
            bot.build_quick_station_keyboard("wiz_from", t)
            # Verify called twice, each with fallback from _station_index
            calls = mock_tsn.call_args_list
            assert len(calls) >= 2
            # First call: Tbilisi with fallback
            assert calls[0][0] == (56014, "en")
            assert calls[0][1]["fallback"] == "Tbilisi Central"
            # Second call: Batumi with fallback
            assert calls[1][0] == (57151, "en")
            assert calls[1][1]["fallback"] == "Batumi Seaside"


# ═══════════════════════ Class Keyboard ════════════════════════════════


class TestClassKeyboard:

    def test_class_keyboard_structure(self):
        import bot
        t = MagicMock()
        t.side_effect = lambda key: {
            "wizard.class_any_btn": "✨ Any",
            "wizard.class_business_btn": "💼 Business",
            "wizard.class_i_btn": "🥇 I класс",
            "wizard.class_ii_btn": "🥈 II класс",
            "button.cancel": "🚫 Cancel",
        }.get(key, key)

        markup = bot.build_class_keyboard(t)
        keyboard = markup.inline_keyboard
        assert len(keyboard) == 3  # 2 class rows + cancel
        assert keyboard[0][0].callback_data == "wiz_class:Any"
        assert keyboard[0][1].callback_data == "wiz_class:Business"
        assert keyboard[1][0].callback_data == "wiz_class:I"
        assert keyboard[1][1].callback_data == "wiz_class:II"
        assert keyboard[2][0].callback_data == "cancel"


# ═══════════════════════ /start Wizard Flow ════════════════════════════


class TestWizardStart:

    @pytest.mark.asyncio
    async def test_cmd_start_shows_date_keyboard(self):
        import bot
        bot._stations = [{"code": "56014", "stationName": "Tbilisi", "isPopular": True}]
        bot._station_index = {"56014": bot._stations[0]}

        update = make_update(chat_id=12345)
        ctx = make_context()

        result = await bot.cmd_start(update, ctx)
        assert result == bot.DATE_SELECT
        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args
        assert "reply_markup" in args[1]
        keyboard = args[1]["reply_markup"].inline_keyboard
        assert keyboard[0][0].callback_data == "wiz_date:today"


class TestWizardDateSelection:

    @pytest.mark.asyncio
    async def test_date_today(self):
        import bot
        update = make_update(callback_data="wiz_date:today")
        ctx = make_context()

        with patch.object(bot, "_show_departure", AsyncMock(return_value=bot.DEPARTURE_SELECT)):
            result = await bot.wizard_date_handler(update, ctx)

        assert result == bot.DEPARTURE_SELECT
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert ctx.user_data["date"] == today

    @pytest.mark.asyncio
    async def test_date_tomorrow(self):
        import bot
        update = make_update(callback_data="wiz_date:tomorrow")
        ctx = make_context()

        with patch.object(bot, "_show_departure", AsyncMock(return_value=bot.DEPARTURE_SELECT)):
            result = await bot.wizard_date_handler(update, ctx)

        assert result == bot.DEPARTURE_SELECT
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        assert ctx.user_data["date"] == tomorrow

    @pytest.mark.asyncio
    async def test_date_custom_transitions(self):
        import bot
        update = make_update(callback_data="wiz_date:custom")
        ctx = make_context()

        result = await bot.wizard_date_handler(update, ctx)

        assert result == bot.WAITING_CUSTOM_DATE
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_date_cancel(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.wizard_date_handler(update, ctx)

        assert result == bot.ConversationHandler.END


class TestWizardCustomDate:

    @pytest.mark.asyncio
    async def test_valid_iso_date(self):
        import bot
        update = make_update(text="2026-07-15")
        ctx = make_context()

        with patch.object(bot, "_show_departure", AsyncMock(return_value=bot.DEPARTURE_SELECT)):
            result = await bot.wizard_custom_date_handler(update, ctx)

        assert result == bot.DEPARTURE_SELECT
        assert ctx.user_data["date"] == "2026-07-15"

    @pytest.mark.asyncio
    async def test_past_date_rejected(self):
        import bot
        update = make_update(text="2020-01-01")
        ctx = make_context()

        result = await bot.wizard_custom_date_handler(update, ctx)

        assert result == bot.WAITING_CUSTOM_DATE
        assert "date" not in ctx.user_data

    @pytest.mark.asyncio
    async def test_invalid_format(self):
        import bot
        update = make_update(text="not-a-date")
        ctx = make_context()

        result = await bot.wizard_custom_date_handler(update, ctx)

        assert result == bot.WAITING_CUSTOM_DATE

    @pytest.mark.asyncio
    async def test_invalid_month(self):
        import bot
        update = make_update(text="2026-13-01")  # month 13
        ctx = make_context()

        result = await bot.wizard_custom_date_handler(update, ctx)

        assert result == bot.WAITING_CUSTOM_DATE


class TestWizardDeparture:

    @pytest.mark.asyncio
    async def test_cancel(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_quick_pick_tbilisi(self):
        import bot
        bot._stations = [{"code": "56014", "stationName": "Tbilisi", "isPopular": True}]
        bot._station_index = {"56014": bot._stations[0]}

        update = make_update(callback_data="wiz_from:56014")
        ctx = make_context()

        with patch.object(bot, "_show_arrival", AsyncMock(return_value=bot.ARRIVAL_SELECT)):
            result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT
        assert ctx.user_data["from_code"] == "56014"
        assert ctx.user_data["from_station"] == "Tbilisi"

    @pytest.mark.asyncio
    async def test_quick_pick_batumi(self):
        import bot
        bot._stations = [{"code": "57151", "stationName": "Batumi", "isPopular": True}]
        bot._station_index = {"57151": bot._stations[0]}

        update = make_update(callback_data="wiz_from:57151")
        ctx = make_context()

        with patch.object(bot, "_show_arrival", AsyncMock(return_value=bot.ARRIVAL_SELECT)):
            result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT
        assert ctx.user_data["from_code"] == "57151"
        assert ctx.user_data["from_station"] == "Batumi"

    @pytest.mark.asyncio
    async def test_all_stations_shows_paginated(self):
        import bot
        bot._stations = [
            {"code": "57000", "stationName": "Kutaisi", "isPopular": True},
            {"code": "57290", "stationName": "Zugdidi", "isPopular": True},
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="wiz_from:all")
        ctx = make_context()

        result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.DEPARTURE_SELECT
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_pagination(self):
        import bot
        bot._stations = [
            {"code": str(57000 + i), "stationName": f"Station{i}", "isPopular": True}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="page:wiz_from:1")
        ctx = make_context()

        result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.DEPARTURE_SELECT
        update.callback_query.edit_message_reply_markup.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_from_paginated(self):
        import bot
        bot._stations = [{"code": "57000", "stationName": "Kutaisi", "isPopular": True}]
        bot._station_index = {"57000": bot._stations[0]}

        update = make_update(callback_data="wiz_from:57000")
        ctx = make_context()

        with patch.object(bot, "_show_arrival", AsyncMock(return_value=bot.ARRIVAL_SELECT)):
            result = await bot.wizard_departure_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT
        assert ctx.user_data["from_code"] == "57000"
        assert ctx.user_data["from_station"] == "Kutaisi"


class TestWizardArrival:

    @pytest.mark.asyncio
    async def test_cancel(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.wizard_arrival_handler(update, ctx)

        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_quick_pick(self):
        import bot
        bot._stations = [{"code": "57151", "stationName": "Batumi", "isPopular": True}]
        bot._station_index = {"57151": bot._stations[0]}

        update = make_update(callback_data="wiz_to:57151", chat_id=12345)
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"
        ctx.user_data["from_station"] = "Tbilisi"
        ctx.user_data["date"] = "2026-07-15"

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch.object(bot, "_show_class", AsyncMock(return_value=bot.CLASS_SELECT)):
            result = await bot.wizard_arrival_handler(update, ctx)

        assert result == bot.CLASS_SELECT
        saved = mock_save.call_args[0][1]
        assert saved["from_station"] == "Tbilisi"
        assert saved["to_station"] == "Batumi"
        assert saved["from_station_code"] == "56014"
        assert saved["to_station_code"] == "57151"
        assert saved["date"] == "2026-07-15"

    @pytest.mark.asyncio
    async def test_same_station_rejected(self):
        import bot
        bot._stations = [{"code": "56014", "stationName": "Tbilisi", "isPopular": True}]
        bot._station_index = {"56014": bot._stations[0]}

        update = make_update(callback_data="wiz_to:56014")
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"

        result = await bot.wizard_arrival_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_stations_shows_paginated(self):
        import bot
        bot._stations = [
            {"code": "57000", "stationName": "Kutaisi", "isPopular": True},
        ]
        bot._station_index = {"57000": bot._stations[0]}

        update = make_update(callback_data="wiz_to:all")
        ctx = make_context()

        result = await bot.wizard_arrival_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_pagination(self):
        import bot
        bot._stations = [
            {"code": str(57000 + i), "stationName": f"Station{i}", "isPopular": True}
            for i in range(20)
        ]
        bot._station_index = {s["code"]: s for s in bot._stations}

        update = make_update(callback_data="page:wiz_to:0")
        ctx = make_context()

        result = await bot.wizard_arrival_handler(update, ctx)

        assert result == bot.ARRIVAL_SELECT


class TestWizardClassSelection:

    @pytest.mark.asyncio
    async def test_cancel(self):
        import bot
        update = make_update(callback_data="cancel")
        ctx = make_context()

        result = await bot.wizard_class_handler(update, ctx)

        assert result == bot.ConversationHandler.END

    @pytest.mark.asyncio
    async def test_select_any_class(self):
        import bot
        update = make_update(callback_data="wiz_class:Any", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.poller.start"):
            result = await bot.wizard_class_handler(update, ctx)

        assert result == bot.ConversationHandler.END
        saved = mock_save.call_args[0][1]
        assert saved["seat_class"] == "Any"

    @pytest.mark.asyncio
    async def test_select_business_starts_poller(self):
        import bot
        update = make_update(callback_data="wiz_class:Business", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config"), \
             patch("bot.poller.start") as mock_poller_start:
            result = await bot.wizard_class_handler(update, ctx)

        assert result == bot.ConversationHandler.END
        mock_poller_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_class_i(self):
        import bot
        update = make_update(callback_data="wiz_class:I", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.poller.start"):
            result = await bot.wizard_class_handler(update, ctx)

        assert result == bot.ConversationHandler.END
        saved = mock_save.call_args[0][1]
        assert saved["seat_class"] == "I"

    @pytest.mark.asyncio
    async def test_select_class_ii(self):
        import bot
        update = make_update(callback_data="wiz_class:II", chat_id=12345)
        ctx = make_context()

        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config") as mock_save, \
             patch("bot.poller.start"):
            result = await bot.wizard_class_handler(update, ctx)

        assert result == bot.ConversationHandler.END
        saved = mock_save.call_args[0][1]
        assert saved["seat_class"] == "II"


# ═══════════════════════ /stop Command ═════════════════════════════════


class TestStopCommand:

    @pytest.mark.asyncio
    async def test_stop_calls_poller_stop_and_delete_config(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.poller.stop") as mock_poller_stop, \
             patch("bot.delete_config") as mock_delete_config:
            await bot.cmd_stop(update, ctx)

            mock_poller_stop.assert_called_once_with(12345)
            mock_delete_config.assert_called_once_with(12345)
            update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_shows_stopped_message(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        with patch("bot.poller.stop"), \
             patch("bot.delete_config"):
            await bot.cmd_stop(update, ctx)

            text = update.message.reply_text.call_args[0][0]
            # Should contain the stop message from i18n
            assert "stopped" in text.lower() or "остановлен" in text.lower()


# ═══════════════════════ /lang Command ═════════════════════════════════


class TestLangCommand:

    @pytest.mark.asyncio
    async def test_lang_en_sets_english(self):
        """'/lang en' calls set_user_language and sends confirmation in English."""
        import bot
        update = make_update(chat_id=12345, text="/lang en")
        ctx = make_context()

        with patch("bot.set_user_language", return_value="en") as mock_set, \
             patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.set_success": "🌐 Interface language set to *English*",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.cmd_lang(update, ctx)

            mock_set.assert_called_once_with(12345, "en")
            mock_get_t.assert_called_once_with(12345, update.effective_user)
            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            assert "English" in msg

    @pytest.mark.asyncio
    async def test_lang_ru_sets_russian(self):
        """'/lang ru' calls set_user_language and sends confirmation in Russian."""
        import bot
        update = make_update(chat_id=12345, text="/lang ru")
        ctx = make_context()

        with patch("bot.set_user_language", return_value="ru") as mock_set, \
             patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.set_success": "🌐 Язык интерфейса установлен: *Русский*",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.cmd_lang(update, ctx)

            mock_set.assert_called_once_with(12345, "ru")
            msg = update.message.reply_text.call_args[0][0]
            assert "Русский" in msg

    @pytest.mark.asyncio
    async def test_lang_no_argument_shows_keyboard(self):
        """'/lang' with no argument shows inline keyboard with language buttons."""
        import bot
        update = make_update(chat_id=12345, text="/lang")
        ctx = make_context()

        with patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.select": "🌐 *Select interface language:*",
                "lang.en_btn": "🇬🇧 English",
                "lang.ru_btn": "🇷🇺 Русский",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.cmd_lang(update, ctx)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args[1]
        assert "reply_markup" in call_kwargs
        keyboard = call_kwargs["reply_markup"]
        # Two buttons in one row
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
        btn_en, btn_ru = keyboard.inline_keyboard[0]
        assert "English" in btn_en.text
        assert "Русский" in btn_ru.text
        assert btn_en.callback_data == "lang_set:en"
        assert btn_ru.callback_data == "lang_set:ru"

    @pytest.mark.asyncio
    async def test_lang_too_many_arguments_shows_keyboard(self):
        """'/lang en ru' with too many arguments shows the language keyboard."""
        import bot
        update = make_update(chat_id=12345, text="/lang en ru")
        ctx = make_context()

        with patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.select": "🌐 *Select interface language:*",
                "lang.en_btn": "🇬🇧 English",
                "lang.ru_btn": "🇷🇺 Русский",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.cmd_lang(update, ctx)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args[1]
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_lang_invalid_language_shows_error(self):
        """'/lang fr' with unsupported language shows error."""
        import bot
        update = make_update(chat_id=12345, text="/lang fr")
        ctx = make_context()

        with patch("bot.set_user_language", side_effect=ValueError(
            "Unsupported language 'fr'. Supported: en, ru"
        )):
            await bot.cmd_lang(update, ctx)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Unsupported" in msg or "fr" in msg

    @pytest.mark.asyncio
    async def test_lang_empty_message_shows_keyboard(self):
        """Empty message text falls through to showing the language keyboard."""
        import bot
        update = make_update(chat_id=12345, text="")
        ctx = make_context()

        with patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.select": "🌐 *Select interface language:*",
                "lang.en_btn": "🇬🇧 English",
                "lang.ru_btn": "🇷🇺 Русский",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.cmd_lang(update, ctx)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args[1]
        assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_lang_persists_and_get_user_translation_returns_new_lang(self):
        """After /lang ru, get_user_translation reflects the change."""
        import bot
        from i18n import clear_user_lang_cache

        # Use a temp config dir for real persistence
        import config_manager
        data_dir = tempfile.mkdtemp()
        config_manager.DATA_DIR = data_dir
        clear_user_lang_cache()

        update = make_update(chat_id=12346, text="/lang ru")
        ctx = make_context()

        await bot.cmd_lang(update, ctx)

        msg = update.message.reply_text.call_args[0][0]
        assert "Русский" in msg

        # Verify config file was written
        path = os.path.join(data_dir, "12346.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        assert config.get("language") == "ru"

        # Verify get_user_translation picks it up
        t = bot.get_user_translation(12346)
        assert t.lang == "ru"

    @pytest.mark.asyncio
    async def test_lang_callback_sets_language_en(self):
        """Callback with 'lang_set:en' sets language and edits the message."""
        import bot
        update = make_update(callback_data="lang_set:en", chat_id=12347)
        ctx = make_context()

        with patch("bot.set_user_language", return_value="en") as mock_set, \
             patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.set_success": "🌐 Interface language set to *English*",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.lang_callback(update, ctx)

        mock_set.assert_called_once_with(12347, "en")
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "English" in msg

    @pytest.mark.asyncio
    async def test_lang_callback_sets_language_ru(self):
        """Callback with 'lang_set:ru' sets language and edits the message."""
        import bot
        update = make_update(callback_data="lang_set:ru", chat_id=12348)
        ctx = make_context()

        with patch("bot.set_user_language", return_value="ru") as mock_set, \
             patch("bot.get_user_translation") as mock_get_t:
            t = MagicMock()
            t.side_effect = lambda key, **kw: {
                "lang.set_success": "🌐 Язык интерфейса установлен: *Русский*",
            }.get(key, key)
            mock_get_t.return_value = t

            await bot.lang_callback(update, ctx)

        mock_set.assert_called_once_with(12348, "ru")
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Русский" in msg

    @pytest.mark.asyncio
    async def test_lang_callback_invalid_code_silently_returns(self):
        """Callback with invalid language code does not crash."""
        import bot
        update = make_update(callback_data="lang_set:fr", chat_id=12349)
        ctx = make_context()

        with patch("bot.set_user_language", side_effect=ValueError(
            "Unsupported language 'fr'. Supported: en, ru"
        )) as mock_set:
            await bot.lang_callback(update, ctx)

        mock_set.assert_called_once_with(12349, "fr")
        # edit_message_text should NOT be called on error
        update.callback_query.edit_message_text.assert_not_called()

    def test_build_lang_keyboard_structure(self):
        """build_lang_keyboard returns a one-row InlineKeyboardMarkup with two buttons."""
        import bot
        t = MagicMock()
        t.side_effect = lambda key, **kw: {
            "lang.en_btn": "🇬🇧 English",
            "lang.ru_btn": "🇷🇺 Русский",
        }.get(key, key)

        keyboard = bot.build_lang_keyboard(t)

        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
        btn_en, btn_ru = keyboard.inline_keyboard[0]
        assert btn_en.text == "🇬🇧 English"
        assert btn_en.callback_data == "lang_set:en"
        assert btn_ru.text == "🇷🇺 Русский"
        assert btn_ru.callback_data == "lang_set:ru"


# ═══════════════════════ Fallback ═════════════════════════════════════


class TestFallback:

    @pytest.mark.asyncio
    async def test_fallback_handler(self):
        import bot
        update = make_update(chat_id=12345)
        ctx = make_context()

        await bot.fallback_handler(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "don't understand" in text.lower() or "не понимаю" in text


# ═══════════════════════ Date Regex ════════════════════════════════════


class TestDateRegex:

    def test_date_regex_valid(self):
        import bot
        assert bot.DATE_RE.match("2026-07-15")
        assert bot.DATE_RE.match("2026-01-01")
        assert bot.DATE_RE.match("2026-12-31")

    def test_date_regex_invalid(self):
        import bot
        assert bot.DATE_RE.match("2026-13-01") is not None  # format match, caught later
        assert bot.DATE_RE.match("not-a-date") is None
        assert bot.DATE_RE.match("2026-1-1") is None
        assert bot.DATE_RE.match("") is None


# ═══════════════════════ Station Name Helper ═══════════════════════════


class TestStationNameForCode:

    def test_known_station(self):
        import bot
        bot._station_index = {"56014": {"code": "56014", "stationName": "Tbilisi"}}

        name = bot.station_name_for_code("56014")
        assert name == "Tbilisi"

    def test_unknown_station_returns_code(self):
        import bot
        bot._station_index = {"56014": {"code": "56014", "stationName": "Tbilisi"}}

        name = bot.station_name_for_code("99999")
        assert name == "99999"

    def test_unknown_station_with_fallback(self):
        """When API stationName is provided, it is used as fallback."""
        import bot
        bot._station_index = {"56014": {"code": "56014", "stationName": "Tbilisi"}}

        name = bot.station_name_for_code("99999", station_name="Custom Station")
        assert name == "Custom Station"

    def test_known_station_ignores_fallback(self):
        """Hardcoded translation takes priority over API name."""
        import bot
        bot._station_index = {"56014": {"code": "56014", "stationName": "Tbilisi"}}

        name = bot.station_name_for_code("56014", station_name="Should Not Use")
        assert name == "Tbilisi"

    def test_all_fallback_stations_return_names(self):
        """Every station from FALLBACK_STATIONS returns a name, never a numeric code."""
        import bot
        from stations import FALLBACK_STATIONS

        bot._stations = FALLBACK_STATIONS
        bot._station_index = {}
        for s in bot._stations:
            code = str(s.get("code", ""))
            if code:
                bot._station_index[code] = s

        for s in FALLBACK_STATIONS:
            code = s.get("code", "")
            station_name = s.get("stationName", "")
            if code:
                result = bot.station_name_for_code(str(code), station_name=station_name)
                assert not result.isdigit(), (
                    f"Code {code} returned numeric '{result}' instead of a name"
                )
                assert result, f"Code {code} returned empty string"


# ═══════════════════════ Full 36-Station Integration ═══════════════════

# A realistic 36-station dataset mimicking what the API may return.
# Mix of known codes (with hardcoded translations) and unknown codes
# (relying on API stationName as fallback).
_THIRTY_SIX_STATIONS = [
    {"code": "56014", "stationName": "Tbilisi",             "isPopular": True},
    {"code": "57151", "stationName": "Batumi",              "isPopular": True},
    {"code": "57450", "stationName": "Kutaisi Airport",     "isPopular": True},
    {"code": "57530", "stationName": "Kutaisi",             "isPopular": True},
    {"code": "57290", "stationName": "Zugdidi",             "isPopular": True},
    {"code": "57120", "stationName": "Kobuleti",            "isPopular": True},
    {"code": "57100", "stationName": "Ozurgeti",            "isPopular": True},
    {"code": "57190", "stationName": "Senaki",              "isPopular": True},
    {"code": "57000", "stationName": "Samtredia",           "isPopular": True},
    {"code": "57070", "stationName": "Ureki",               "isPopular": False},
    {"code": "57210", "stationName": "Poti",                "isPopular": True},
    {"code": "57900", "stationName": "Gori",                "isPopular": False},
    {"code": "57720", "stationName": "Khashuri",            "isPopular": False},
    {"code": "57600", "stationName": "Zestafoni",           "isPopular": False},
    {"code": "57510", "stationName": "Rioni",               "isPopular": False},
    {"code": "57030", "stationName": "Nigoiti",             "isPopular": False},
    {"code": "56040", "stationName": "Mtskheta",            "isPopular": False},
    {"code": "56080", "stationName": "Kaspi",               "isPopular": False},
    {"code": "10001", "stationName": "Station Alpha",       "isPopular": False},
    {"code": "10002", "stationName": "Station Beta",        "isPopular": False},
    {"code": "10003", "stationName": "Station Gamma",       "isPopular": False},
    {"code": "10004", "stationName": "Station Delta",       "isPopular": False},
    {"code": "10005", "stationName": "Station Epsilon",     "isPopular": False},
    {"code": "10006", "stationName": "Station Zeta",        "isPopular": False},
    {"code": "10007", "stationName": "Station Eta",         "isPopular": False},
    {"code": "10008", "stationName": "Station Theta",       "isPopular": False},
    {"code": "10009", "stationName": "Station Iota",        "isPopular": False},
    {"code": "10010", "stationName": "Station Kappa",       "isPopular": False},
    {"code": "10011", "stationName": "Station Lambda",      "isPopular": False},
    {"code": "10012", "stationName": "Station Mu",          "isPopular": False},
    {"code": "10013", "stationName": "Station Nu",          "isPopular": False},
    {"code": "10014", "stationName": "Station Xi",          "isPopular": False},
    {"code": "10015", "stationName": "Station Omicron",     "isPopular": False},
    {"code": "10016", "stationName": "Station Pi",          "isPopular": False},
    {"code": "10017", "stationName": "Station Rho",         "isPopular": False},
    {"code": "10018", "stationName": "Station Sigma",       "isPopular": False},
]


class TestAll36StationsNoNumericCodes:
    """Integration tests: all 36 stations produce names, never numeric codes."""

    def setup_method(self):
        import bot
        bot._stations = list(_THIRTY_SIX_STATIONS)
        bot._station_index = {s["code"]: s for s in bot._stations}

    def test_build_station_keyboard_all_pages_no_numeric(self):
        """Every button on every page of the paginated keyboard is a name."""
        import bot
        total = len(bot._stations) - 2
        total_pages = max(1, (total + bot.STATIONS_PER_PAGE - 1) // bot.STATIONS_PER_PAGE)
        for page in range(total_pages):
            markup = bot.build_station_keyboard("wiz_from", page)
            for row in markup.inline_keyboard:
                for btn in row:
                    if btn.callback_data in ("noop", "cancel") or (
                        btn.callback_data and btn.callback_data.startswith("page:")
                    ):
                        continue
                    assert not btn.text.isdigit(), (
                        f"Page {page}: button '{btn.text}' is a numeric code"
                    )
                    if btn.callback_data and btn.callback_data.startswith("wiz_from:"):
                        code_from_cb = btn.callback_data.split(":", 1)[1]
                        assert btn.text != code_from_cb, (
                            f"Page {page}: button text matches code '{code_from_cb}'"
                        )

    def test_build_quick_station_keyboard_no_numeric(self):
        """Quick-pick keyboard always shows names."""
        import bot
        t = MagicMock()
        t.lang = "en"
        t.side_effect = lambda key: key
        markup = bot.build_quick_station_keyboard("wiz_from", t)
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data == "cancel":
                    continue
                assert not btn.text.isdigit(), f"Quick-pick '{btn.text}' is numeric"

    def test_build_station_keyboard_all_pages_all_actions(self):
        """Both wiz_from and wiz_to keyboards are numeric-free on all pages."""
        import bot
        total = len(bot._stations) - 2
        total_pages = max(1, (total + bot.STATIONS_PER_PAGE - 1) // bot.STATIONS_PER_PAGE)
        for action in ("wiz_from", "wiz_to"):
            for page in range(total_pages):
                markup = bot.build_station_keyboard(action, page)
                for row in markup.inline_keyboard:
                    for btn in row:
                        if btn.callback_data in ("noop", "cancel") or (
                            btn.callback_data and btn.callback_data.startswith("page:")
                        ):
                            continue
                        assert not btn.text.isdigit(), (
                            f"Action '{action}' page {page}: '{btn.text}' is numeric"
                        )

    def test_all_36_stations_return_names_not_numbers(self):
        """station_name_for_code never returns a bare number."""
        import bot
        for s in bot._stations:
            code = s.get("code", "")
            station_name = s.get("stationName", "")
            if not code:
                continue
            result = bot.station_name_for_code(code, station_name=station_name)
            assert not result.isdigit(), (
                f"Code {code} returned numeric '{result}'"
            )
            assert result, f"Code {code} returned empty"

    def test_all_36_stations_all_languages(self):
        """Every station returns a non-digit name in EN, RU, and KA."""
        from i18n import translate_station_name
        for s in _THIRTY_SIX_STATIONS:
            code = s.get("code", "")
            station_name = s.get("stationName", "")
            if not code:
                continue
            code_int = int(code)
            for lang in ("en", "ru", "ka"):
                result = translate_station_name(code_int, lang, fallback=station_name)
                assert not result.isdigit(), (
                    f"Code {code} lang '{lang}' returned numeric '{result}'"
                )
                assert result, f"Code {code} lang '{lang}' returned empty"

    def test_build_station_keyboard_with_translation(self):
        """Paginated keyboard with real translation uses real names."""
        import bot
        from i18n import get_translation
        t = get_translation("en")
        markup = bot.build_station_keyboard("wiz_from", 0, t)
        texts = []
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data not in ("noop", "cancel") and not (
                    btn.callback_data and btn.callback_data.startswith("page:")
                ):
                    texts.append(btn.text)
        known_names = {"Kutaisi Airport", "Kutaisi", "Zugdidi", "Kobuleti",
                       "Ozurgeti", "Senaki", "Samtredia", "Ureki", "Poti",
                       "Gori", "Khashuri", "Zestafoni", "Rioni", "Nigoiti",
                       "Mtskheta", "Kaspi"}
        found_known = known_names & set(texts)
        assert len(found_known) > 0, "Should find at least some known station names"

    def test_quick_station_keyboard_with_translation(self):
        """Quick-picks use translated names."""
        import bot
        from i18n import get_translation
        t = get_translation("en")
        markup = bot.build_quick_station_keyboard("wiz_from", t)
        texts = [btn.text for row in markup.inline_keyboard
                 for btn in row if btn.callback_data != "cancel"]
        assert "Tbilisi" in texts or any("Tbilisi" in t for t in texts), (
            f"Quick-pick buttons: {texts}"
        )
        assert "Batumi" in texts or any("Batumi" in t for t in texts), (
            f"Quick-pick buttons: {texts}"
        )

    @pytest.mark.asyncio
    async def test_departure_select_shows_name_not_code(self):
        """Selecting a station stores and displays a name."""
        import bot
        update = make_update(callback_data="wiz_from:57000")
        ctx = make_context()
        with patch.object(bot, "_show_arrival", AsyncMock(return_value=bot.ARRIVAL_SELECT)):
            await bot.wizard_departure_handler(update, ctx)
        assert ctx.user_data["from_code"] == "57000"
        assert ctx.user_data["from_station"] == "Samtredia"

    @pytest.mark.asyncio
    async def test_arrival_select_shows_name_not_code(self):
        """Selecting arrival displays translated name in confirmation."""
        import bot
        update = make_update(callback_data="wiz_to:57151", chat_id=12345)
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"
        ctx.user_data["from_station"] = "Tbilisi"
        ctx.user_data["date"] = "2026-07-15"
        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config"), \
             patch.object(bot, "_show_class", AsyncMock(return_value=bot.CLASS_SELECT)):
            await bot.wizard_arrival_handler(update, ctx)
        edit_call = update.callback_query.edit_message_text.call_args
        message_text = edit_call[0][0]
        assert "Tbilisi" in message_text, f"Missing Tbilisi in: {message_text}"
        assert "Batumi" in message_text, f"Missing Batumi in: {message_text}"
        assert "56014" not in message_text, (
            f"Numeric code in message: {message_text}"
        )
        assert "57151" not in message_text, (
            f"Numeric code in message: {message_text}"
        )

    @pytest.mark.asyncio
    async def test_unknown_code_still_shows_api_name(self):
        """Even unknown codes produce a name via API fallback."""
        import bot
        update = make_update(callback_data="wiz_from:10001", chat_id=12345)
        ctx = make_context()
        with patch.object(bot, "_show_arrival", AsyncMock(return_value=bot.ARRIVAL_SELECT)):
            await bot.wizard_departure_handler(update, ctx)
        stored_name = ctx.user_data.get("from_station", "")
        assert stored_name == "Station Alpha", f"Got '{stored_name}'"

    @pytest.mark.asyncio
    async def test_arrival_unknown_code_shows_api_name_in_confirmation(self):
        """Arrival with unknown code uses API name in route_saved message."""
        import bot
        update = make_update(callback_data="wiz_to:10018", chat_id=12345)
        ctx = make_context()
        ctx.user_data["from_code"] = "56014"
        ctx.user_data["from_station"] = "Tbilisi"
        ctx.user_data["date"] = "2026-07-15"
        with patch("bot.load_config", return_value={}), \
             patch("bot.save_config"), \
             patch.object(bot, "_show_class", AsyncMock(return_value=bot.CLASS_SELECT)):
            await bot.wizard_arrival_handler(update, ctx)
        edit_call = update.callback_query.edit_message_text.call_args
        message_text = edit_call[0][0]
        assert "Station Sigma" in message_text, (
            f"Expected 'Station Sigma' in: {message_text}"
        )
        assert "10018" not in message_text, (
            f"Numeric code in message: {message_text}"
        )