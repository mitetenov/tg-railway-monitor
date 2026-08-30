"""Delivery guarantees for the polling change detector."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_manager
import poller


def _response(seats: int | None) -> dict:
    classes = [] if seats is None else [{
        "seatClassId": 1,
        "availableNumberOfSeats": seats,
        "moneyAmount": 76,
    }]
    return {
        "departureAvailableRides": [{
            "rideNumber": 812,
            "rideStartDate": "2099-07-15T08:00:00Z",
            "rideEndDate": "2099-07-15T13:00:00Z",
            "rideDuration": "05:00:00",
            "availableSeatsClasses": classes,
        }] if seats is not None else [],
    }


@pytest.fixture(autouse=True)
def isolated_poller_state(tmp_path):
    previous_data_dir = config_manager.DATA_DIR
    config_manager.DATA_DIR = str(tmp_path)
    poller._state.clear()
    yield
    poller._state.clear()
    config_manager.DATA_DIR = previous_data_dir


def _configure(chat_id: int) -> None:
    config_manager.save_config(chat_id, {
        "from_station_code": "56014",
        "to_station_code": "57151",
        "from_station": "Tbilisi",
        "to_station": "Batumi",
        "date": "2099-07-15",
        "seat_class": "Any",
    })


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_before_snapshot_is_advanced():
    chat_id = 40_001
    _configure(chat_id)
    bot = MagicMock(send_message=AsyncMock(side_effect=[TelegramError("blocked"), None]))

    with patch("poller.get_session", AsyncMock(return_value=MagicMock())), \
         patch("poller.get_available_rides", AsyncMock(return_value=_response(5))):
        await poller._check_and_notify(bot, chat_id)
        assert poller._state[chat_id]["rides"] == {}
        await poller._check_and_notify(bot, chat_id)

    assert bot.send_message.await_count == 2
    assert poller._state[chat_id]["rides"]["812"]["1"]["seats"] == 5


@pytest.mark.asyncio
async def test_reappearing_same_count_is_not_suppressed_after_absence():
    chat_id = 40_002
    _configure(chat_id)
    bot = MagicMock(send_message=AsyncMock())

    with patch("poller.get_session", AsyncMock(return_value=MagicMock())), \
         patch("poller.get_available_rides", AsyncMock(side_effect=[
             _response(5), _response(None), _response(5),
         ])):
        await poller._check_and_notify(bot, chat_id)
        await poller._check_and_notify(bot, chat_id)
        await poller._check_and_notify(bot, chat_id)

    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_identical_snapshot_is_suppressed_after_successful_delivery():
    chat_id = 40_003
    _configure(chat_id)
    bot = MagicMock(send_message=AsyncMock())

    with patch("poller.get_session", AsyncMock(return_value=MagicMock())), \
         patch("poller.get_available_rides", AsyncMock(return_value=_response(5))):
        await poller._check_and_notify(bot, chat_id)
        await poller._check_and_notify(bot, chat_id)

    assert bot.send_message.await_count == 1


def test_expired_monitor_is_cleared_but_language_is_retained():
    chat_id = 40_004
    config_manager.save_config(chat_id, {
        "from_station_code": "56014",
        "to_station_code": "57151",
        "date": "2000-01-01",
        "seat_class": "Any",
        "language": "ru",
    })
    config_manager.save_state(chat_id, {"key": "old", "rides": {}})

    assert poller._expire_if_needed(chat_id)
    assert config_manager.load_config(chat_id) == {"language": "ru"}
    assert config_manager.load_state(chat_id) == {}
