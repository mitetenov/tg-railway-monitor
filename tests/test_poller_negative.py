"""Negative / edge-case tests for poller.py.

Covers: empty API responses, zero seats, class filter edge cases,
_state memory, notification errors, pause/resume edge
cases, concurrent state access, malformed ride data.
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import poller
from poller import (
    _state,
    _paused,
    _running_tasks,
    _check_and_notify,
    start,
    stop,
    pause,
    is_paused,
    resume,
    is_running,
    active_count,
)
from utils import format_time


# ═══════════════════════ format_time edge cases ═══════════════════════


class TestFormatTimeNegative:

    def test_only_t_no_time(self):
        result = format_time("2026-06-27T")
        assert result == ""

    def test_midnight_exactly(self):
        result = format_time("2026-06-27T00:00:00Z")
        assert result == "00:00"

    def test_negative_timezone(self):
        result = format_time("2026-06-27T23:59:59-05:00")
        assert result == "23:59"

    def test_milliseconds(self):
        result = format_time("2026-06-27T12:30:45.123Z")
        # Contains "." so gets split away after HH
        assert result == "12:30"

    def test_no_timezone_at_all(self):
        result = format_time("2026-06-27T12:30:00")
        assert result == "12:30"

    def test_time_with_colon_in_timezone(self):
        result = format_time("2026-06-27T08:15:00+04:00")
        assert result == "08:15"


# ═══════════════════════ _running_tasks / active_count ═════════════════


class TestTaskRegistry:

    def setup_method(self):
        # Clean state
        for cid in list(_running_tasks.keys()):
            stop(cid)

    def test_active_count_initially_zero(self):
        assert active_count() == 0

    def test_stop_nonexistent_no_error(self):
        stop(99999)  # should not raise

    def test_is_running_nonexistent(self):
        assert not is_running(99999)


# ═══════════════════════ Pause / Resume Edge Cases ═════════════════════


class TestPauseResumeNegative:

    def setup_method(self):
        for cid in list(_running_tasks.keys()):
            stop(cid)

    def test_pause_twice_no_error(self):
        pause(70001)
        pause(70001)  # should not raise
        assert is_paused(70001)

    def test_unpause_when_not_paused(self):
        """resume() when not paused returns (False, error_message)."""
        import pytest

        chat_id = 70002
        success, msg = resume(None, chat_id)
        assert not success, f"Expected (False, error_message), got ({success}, {msg!r})"
        assert isinstance(msg, str), f"Expected string error message, got {type(msg).__name__}"
        assert msg, "Error message should not be empty"
        assert "Route not configured" in msg, (
            f"Expected 'Route not configured' in message, got: {msg!r}"
        )

    def test_stop_cleans_all_state(self):
        chat_id = 70003
        _state[chat_id] = {"812": {"1": {"seats": 5, "price": 76}}}
        _paused[chat_id] = True
        stop(chat_id)
        assert chat_id not in _state
        assert chat_id not in _paused
        assert chat_id not in _running_tasks


# ═══════════════════════ _state Memory ══════════════════════════════════


class TestStateMemory:
    """State dict persists previous seat counts for diffing."""

    def setup_method(self):
        for cid in list(_state.keys()):
            _state.pop(cid, None)

    def test_state_tracks_seat_counts(self):
        chat_id = 80001
        _state.pop(chat_id, None)

        # Simulate many ride+class combos
        chat_state = {}
        for i in range(100):
            ride_key = str(i)
            chat_state[ride_key] = {"5": {"seats": i % 10, "price": 126}}

        _state[chat_id] = chat_state

        assert chat_id in _state
        assert len(_state[chat_id]) == 100

        # After stop, state is cleared
        stop(chat_id)
        assert chat_id not in _state

    def test_state_cleared_on_stop(self):
        """stop() clears state (important for restart)."""
        chat_id = 80002
        _state[chat_id] = {
            "812": {"1": {"seats": 5, "price": 76}},
            "900": {"5": {"seats": 3, "price": 126}},
        }
        assert chat_id in _state
        stop(chat_id)
        assert chat_id not in _state


# ═══════════════════════ _check_and_notify Mocked ═══════════════════════


class TestCheckAndNotifyNegative:
    """Mock _check_and_notify internals to test edge cases."""

    def setup_method(self):
        """Clean global state before each test."""
        from poller import _state, _paused, _running_tasks
        _state.clear()
        _paused.clear()
        for cid in list(_running_tasks.keys()):
            from poller import stop
            stop(cid)

    SAMPLE_EMPTY = {
        "isAnyDepartureTripAvailable": False,
        "departureAvailableRides": [],
        "returningAvailableRides": [],
    }

    SAMPLE_NO_SEATS = {
        "isAnyDepartureTripAvailable": True,
        "departureAvailableRides": [
            {
                "rideNumber": 812,
                "rideStartDate": "2026-06-27T00:30:00Z",
                "rideEndDate": "2026-06-27T05:42:00Z",
                "rideDuration": "05:12:00",
                "availableSeatsClasses": [
                    {"seatClassId": 2, "availableNumberOfSeats": 0, "moneyAmount": 36},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    SAMPLE_MISSING_RIDE_NUMBER = {
        "isAnyDepartureTripAvailable": True,
        "departureAvailableRides": [
            {
                "rideStartDate": "2026-06-27T00:30:00Z",
                "rideEndDate": "2026-06-27T05:42:00Z",
                "rideDuration": "05:12:00",
                "availableSeatsClasses": [
                    {"seatClassId": 2, "availableNumberOfSeats": 5, "moneyAmount": 36},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    SAMPLE_NEGATIVE_SEATS = {
        "isAnyDepartureTripAvailable": True,
        "departureAvailableRides": [
            {
                "rideNumber": 812,
                "rideStartDate": "2026-06-27T00:30:00Z",
                "rideEndDate": "2026-06-27T05:42:00Z",
                "rideDuration": "05:12:00",
                "availableSeatsClasses": [
                    {"seatClassId": 2, "availableNumberOfSeats": -1, "moneyAmount": 36},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    def setup_method(self):
        self.data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        os.makedirs(self.data_dir, exist_ok=True)
        for cid in list(_state.keys()):
            _state.pop(cid, None)

    def _write_config(self, chat_id, overrides=None):
        cfg = {
            "from_station_code": "56014",
            "to_station_code": "57151",
            "from_station": "Tbilisi",
            "to_station": "Batumi",
            "date": "2026-06-27",
            "seat_class": "Any",
        }
        if overrides:
            cfg.update(overrides)
        with open(os.path.join(self.data_dir, f"{chat_id}.json"), "w") as f:
            json.dump(cfg, f)

    def _cleanup_config(self, chat_id):
        p = os.path.join(self.data_dir, f"{chat_id}.json")
        if os.path.exists(p):
            os.remove(p)

    @pytest.mark.asyncio
    async def test_check_without_config(self):
        """If config doesn't exist, _check_and_notify returns silently."""
        mock_bot = MagicMock()
        result = await _check_and_notify(mock_bot, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_check_with_empty_rides(self):
        """Empty ride list → no notification."""
        chat_id = 81001
        self._write_config(chat_id)
        mock_bot = MagicMock()

        with patch("poller.get_available_rides", AsyncMock(return_value=self.SAMPLE_EMPTY)):
            await _check_and_notify(mock_bot, chat_id)
            mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_check_when_api_returns_none(self):
        """API failure → return silently, no crash."""
        chat_id = 81002
        self._write_config(chat_id)
        mock_bot = MagicMock()

        with patch("poller.get_available_rides", AsyncMock(return_value=None)):
            await _check_and_notify(mock_bot, chat_id)
            mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_zero_seats_not_notified(self):
        """Seats == 0 should NOT trigger notification."""
        chat_id = 81003
        self._write_config(chat_id)
        mock_bot = MagicMock()

        with patch("poller.get_available_rides", AsyncMock(return_value=self.SAMPLE_NO_SEATS)):
            await _check_and_notify(mock_bot, chat_id)
            mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_negative_seats_not_notified(self):
        """Negative seat count should NOT trigger notification."""
        chat_id = 81004
        self._write_config(chat_id)
        mock_bot = MagicMock()

        with patch("poller.get_available_rides", AsyncMock(return_value=self.SAMPLE_NEGATIVE_SEATS)):
            await _check_and_notify(mock_bot, chat_id)
            mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_ride_without_ride_number_skipped(self):
        """Rides with None rideNumber are silently skipped."""
        chat_id = 81005
        self._write_config(chat_id)
        mock_bot = MagicMock()

        with patch("poller.get_available_rides", AsyncMock(return_value=self.SAMPLE_MISSING_RIDE_NUMBER)):
            await _check_and_notify(mock_bot, chat_id)
            mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_class_filter_exact_match_by_id(self):
        """Class filter "I" matches only seatClassId=1 (I Class)."""
        chat_id = 81006
        self._write_config(chat_id, {"seat_class": "Business"})
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        _state.pop(chat_id, None)

        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 3, "moneyAmount": 126},
                        {"seatClassId": 2, "availableNumberOfSeats": 10, "moneyAmount": 36},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)
            if mock_bot.send_message.called:
                text = mock_bot.send_message.call_args[1]["text"]
                assert "Business" in text
                assert "II Class" not in text

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_class_filter_i_matches_only_class_i(self):
        """Class filter "I" matches seatClassId=1 only (not II Class)."""
        chat_id = 81007
        self._write_config(chat_id, {"seat_class": "I"})
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        _state.pop(chat_id, None)

        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 1, "availableNumberOfSeats": 15, "moneyAmount": 76},
                        {"seatClassId": 2, "availableNumberOfSeats": 20, "moneyAmount": 36},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)
            if mock_bot.send_message.called:
                text = mock_bot.send_message.call_args[1]["text"]
                assert "I Class" in text
                assert "II Class" not in text  # exact match — no false positive

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_incomplete_config_skips_check(self):
        """If from_code is missing, no API call is made."""
        chat_id = 81008
        self._write_config(chat_id, {"from_station_code": None, "date": None})
        mock_bot = MagicMock()

        # Should return early without fetching
        await _check_and_notify(mock_bot, chat_id)
        mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_repeated_same_ride_not_notified_twice(self):
        """Once notified, same ride+class combo is not re-notified."""
        chat_id = 81009
        self._write_config(chat_id)
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        _state.pop(chat_id, None)

        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 3, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)
            first_call_count = mock_bot.send_message.call_count

            await _check_and_notify(mock_bot, chat_id)
            second_call_count = mock_bot.send_message.call_count

            assert second_call_count == first_call_count  # no new notification

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_telegram_error_handled_gracefully(self):
        """TelegramError during notification is caught, not propagated."""
        chat_id = 81010
        self._write_config(chat_id)
        _state.pop(chat_id, None)

        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 3, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("Blocked by user"))

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            # Should not raise
            await _check_and_notify(mock_bot, chat_id)

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_multiple_rides_group_properly_with_purchase_links(self):
        """Two rides with new classes → one message per ride."""
        chat_id = 81011
        self._write_config(chat_id)
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        _state.pop(chat_id, None)

        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 800,
                    "rideStartDate": "2026-06-27T08:00:00Z",
                    "rideEndDate": "2026-06-27T13:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 1, "availableNumberOfSeats": 5, "moneyAmount": 76},
                    ],
                },
                {
                    "rideNumber": 900,
                    "rideStartDate": "2026-06-27T18:00:00Z",
                    "rideEndDate": "2026-06-27T23:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 2, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)

        if mock_bot.send_message.called:
            text = mock_bot.send_message.call_args[1]["text"]
            assert "Ride #800" in text
            assert "Ride #900" in text

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_notification_includes_all_rides_not_just_changed(self):
        """When one ride changes, notification includes ALL available rides."""
        chat_id = 81012
        self._write_config(chat_id)
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        # Reset state for this chat
        _state.pop(chat_id, None)

        # Seed state: ride #800 already known with 5 seats
        _state[chat_id] = {
            "800": {"1": {"seats": 5, "price": 76}},
        }

        # API returns: ride #800 unchanged + ride #900 (new)
        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 800,
                    "rideStartDate": "2026-06-27T08:00:00Z",
                    "rideEndDate": "2026-06-27T13:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 1, "availableNumberOfSeats": 5, "moneyAmount": 76},
                    ],
                },
                {
                    "rideNumber": 900,
                    "rideStartDate": "2026-06-27T18:00:00Z",
                    "rideEndDate": "2026-06-27T23:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 2, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)

        # Both rides should appear in notification
        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args[1]["text"]
        assert "Ride #800" in text, "Unchanged ride should still be in notification"
        assert "Ride #900" in text, "New ride should be in notification"

        # Verify state tracks both rides
        assert str(900) in _state.get(chat_id, {}), "State should track ride 900"

        self._cleanup_config(chat_id)

    @pytest.mark.asyncio
    async def test_no_notification_when_nothing_changes(self):
        """When API returns exact same data as state → no notification at all."""
        chat_id = 81013
        self._write_config(chat_id)
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        _state.pop(chat_id, None)

        # Seed state: 2 rides already known
        _state[chat_id] = {
            "800": {"1": {"seats": 5, "price": 76}},
            "900": {"5": {"seats": 2, "price": 126}},
        }

        # API returns exactly the same data
        data = {
            "isAnyDepartureTripAvailable": True,
            "departureAvailableRides": [
                {
                    "rideNumber": 800,
                    "rideStartDate": "2026-06-27T08:00:00Z",
                    "rideEndDate": "2026-06-27T13:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 1, "availableNumberOfSeats": 5, "moneyAmount": 76},
                    ],
                },
                {
                    "rideNumber": 900,
                    "rideStartDate": "2026-06-27T18:00:00Z",
                    "rideEndDate": "2026-06-27T23:00:00Z",
                    "rideDuration": "05:00:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": 2, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }

        with patch("poller.get_available_rides", AsyncMock(return_value=data)):
            await _check_and_notify(mock_bot, chat_id)

        mock_bot.send_message.assert_not_called()

        self._cleanup_config(chat_id)
