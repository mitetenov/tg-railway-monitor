"""Tests for restart survival: poller restore + persisted diff state.

These cover the two failure modes that made monitoring silently die or
spam after a container restart:
  * the task registry is in memory only, so nothing polled after a restart
  * the diff snapshot was in memory only, so the first check after a
    restart treated every known ticket as new
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_manager
import poller
from poller import _check_and_notify, _state, restore_all, stop

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

COMPLETE_CONFIG = {
    "from_station_code": "56014",
    "to_station_code": "57151",
    "from_station": "Tbilisi",
    "to_station": "Batumi",
    "date": "2099-06-27",
    "seat_class": "Any",
}

SAMPLE_RIDES = {
    "isAnyDepartureTripAvailable": True,
    "departureAvailableRides": [
        {
            "rideNumber": 812,
            "rideStartDate": "2099-06-27T00:30:00Z",
            "rideEndDate": "2099-06-27T05:42:00Z",
            "rideDuration": "05:12:00",
            "availableSeatsClasses": [
                {"seatClassId": 1, "availableNumberOfSeats": 5, "moneyAmount": 76},
            ],
        },
    ],
    "returningAvailableRides": [],
}


def _write_config(chat_id, overrides=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = dict(COMPLETE_CONFIG)
    if overrides:
        cfg.update(overrides)
    with open(os.path.join(DATA_DIR, f"{chat_id}.json"), "w") as f:
        json.dump(cfg, f)


def _cleanup(chat_id):
    stop(chat_id)
    for name in (f"{chat_id}.json", f"{chat_id}.state.json"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            os.remove(p)


# ═══════════════════════ iter_chat_ids ═══════════════════════════════


class TestIterChatIds:

    def test_finds_config_files(self):
        _write_config(91001)
        try:
            assert 91001 in config_manager.iter_chat_ids()
        finally:
            _cleanup(91001)

    def test_ignores_state_files(self):
        """A {chat_id}.state.json must not be mistaken for a config."""
        _write_config(91002)
        config_manager.save_state(91002, {"key": "x", "rides": {}})
        try:
            ids = config_manager.iter_chat_ids()
            assert ids.count(91002) == 1
        finally:
            _cleanup(91002)

    def test_ignores_non_numeric_names(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        before = config_manager.iter_chat_ids()
        junk = os.path.join(DATA_DIR, "notachat.json")
        with open(junk, "w") as f:
            json.dump({}, f)
        try:
            assert config_manager.iter_chat_ids() == before
        finally:
            os.remove(junk)


# ═══════════════════════ restore_all ═════════════════════════════════


class TestRestoreAll:

    def test_restores_complete_configs(self):
        _write_config(91010)
        try:
            with patch("poller.start") as mock_start:
                restored = restore_all(MagicMock())
            assert restored >= 1
            assert any(call.args[1] == 91010 for call in mock_start.call_args_list)
        finally:
            _cleanup(91010)

    def test_skips_incomplete_configs(self):
        _write_config(91011, {"date": None})
        os.remove(os.path.join(DATA_DIR, "91011.json"))
        with open(os.path.join(DATA_DIR, "91011.json"), "w") as f:
            json.dump({"from_station_code": "56014"}, f)  # no date / class
        try:
            with patch("poller.start") as mock_start:
                restore_all(MagicMock())
            assert not any(
                call.args[1] == 91011 for call in mock_start.call_args_list
            )
        finally:
            _cleanup(91011)

    def test_corrupt_config_does_not_abort_restore(self):
        """One unreadable config must not stop the other chats coming back."""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "91012.json"), "w") as f:
            f.write("{not json")
        _write_config(91013)
        try:
            with patch("poller.start") as mock_start:
                restore_all(MagicMock())
            assert any(call.args[1] == 91013 for call in mock_start.call_args_list)
        finally:
            _cleanup(91012)
            _cleanup(91013)

    def test_non_object_config_does_not_abort_restore(self):
        """A valid JSON value with the wrong shape must not block other chats."""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "91014.json"), "w") as f:
            json.dump([], f)
        _write_config(91015)
        try:
            with patch("poller.start") as mock_start:
                restored = restore_all(MagicMock())
            assert restored >= 1
            assert any(call.args[1] == 91015 for call in mock_start.call_args_list)
        finally:
            _cleanup(91014)
            _cleanup(91015)


# ═══════════════════════ State persistence ═══════════════════════════


class TestStatePersistence:

    @pytest.mark.asyncio
    async def test_state_written_to_disk(self):
        chat_id = 91020
        _write_config(chat_id)
        _state.pop(chat_id, None)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        try:
            with patch("poller.get_available_rides", AsyncMock(return_value=SAMPLE_RIDES)):
                await _check_and_notify(bot, chat_id)

            on_disk = config_manager.load_state(chat_id)
            assert on_disk["rides"]["812"]["1"]["seats"] == 5
        finally:
            _cleanup(chat_id)

    @pytest.mark.asyncio
    async def test_restart_does_not_renotify(self):
        """After a restart the persisted snapshot suppresses the replay."""
        chat_id = 91021
        _write_config(chat_id)
        _state.pop(chat_id, None)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        try:
            with patch("poller.get_available_rides", AsyncMock(return_value=SAMPLE_RIDES)):
                await _check_and_notify(bot, chat_id)
            assert bot.send_message.call_count == 1

            # Simulate a process restart: memory is gone, disk survives.
            _state.pop(chat_id, None)
            bot.send_message.reset_mock()

            with patch("poller.get_available_rides", AsyncMock(return_value=SAMPLE_RIDES)):
                await _check_and_notify(bot, chat_id)
            bot.send_message.assert_not_called()
        finally:
            _cleanup(chat_id)

    @pytest.mark.asyncio
    async def test_date_change_discards_stale_snapshot(self):
        """A snapshot for another date must not suppress the new search."""
        chat_id = 91022
        _write_config(chat_id)
        _state.pop(chat_id, None)
        bot = MagicMock()
        bot.send_message = AsyncMock()

        try:
            with patch("poller.get_available_rides", AsyncMock(return_value=SAMPLE_RIDES)):
                await _check_and_notify(bot, chat_id)
            assert bot.send_message.call_count == 1

            # User picks a different date — same ride numbers, new search.
            _write_config(chat_id, {"date": "2099-07-04"})
            _state.pop(chat_id, None)
            bot.send_message.reset_mock()

            with patch("poller.get_available_rides", AsyncMock(return_value=SAMPLE_RIDES)):
                await _check_and_notify(bot, chat_id)
            bot.send_message.assert_called_once()
        finally:
            _cleanup(chat_id)

    def test_corrupt_state_file_degrades_quietly(self):
        chat_id = 91023
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, f"{chat_id}.state.json"), "w") as f:
            f.write("{truncated")
        try:
            assert config_manager.load_state(chat_id) == {}
        finally:
            _cleanup(chat_id)


# ═══════════════════════ Loop resilience ═════════════════════════════


class TestLoopResilience:

    @pytest.mark.asyncio
    async def test_failing_check_does_not_end_the_loop(self):
        """A raising check is logged and retried, not fatal."""
        calls = []

        async def boom(_bot, _chat_id):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("corrupt config")

        sleeps = []

        async def fake_sleep(_seconds):
            sleeps.append(1)
            if len(sleeps) >= 2:
                raise _StopLoop

        with patch("poller._check_and_notify", boom), \
             patch("poller.asyncio.sleep", fake_sleep):
            with pytest.raises(_StopLoop):
                await poller._poller_loop(MagicMock(), 91030)

        # Survived the first failure and ran a second check.
        assert len(calls) == 2


class _StopLoop(Exception):
    """Sentinel used to break out of the infinite poller loop in tests."""


# ═══════════════════════ Shared session ══════════════════════════════


class TestSharedSession:

    @pytest.mark.asyncio
    async def test_session_is_reused(self):
        first = await poller.get_session()
        second = await poller.get_session()
        try:
            assert first is second
        finally:
            await poller.close_session()

    @pytest.mark.asyncio
    async def test_closed_session_is_replaced(self):
        first = await poller.get_session()
        await poller.close_session()
        second = await poller.get_session()
        try:
            assert first is not second
            assert not second.closed
        finally:
            await poller.close_session()
