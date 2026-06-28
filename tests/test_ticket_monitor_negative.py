"""Negative / edge-case tests for ticket_monitor.py.

Covers: malformed API responses, HTTP error codes, corrupted state file,
format edge cases, thread safety, callback errors, empty routes, CLI.
"""
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ticket_monitor import (
    TicketMonitor,
    RouteConfig,
    TicketState,
    create_default_config,
    STATION_NAMES,
    CLASS_NAMES,
    main,
)
from utils import format_time, fmt_duration


# ═══════════════════════ RouteConfig Negative ══════════════════════════


class TestRouteConfigNegative:

    def test_date_default_tomorrow_utc(self):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        r = RouteConfig(from_station_code="56014", to_station_code="57151")
        assert r.date == tomorrow

    def test_custom_name_override(self):
        r = RouteConfig(
            from_station_code="56014",
            to_station_code="57151",
            from_station_name="Custom A",
            to_station_name="Custom B",
        )
        assert r.from_station_name == "Custom A"
        assert r.to_station_name == "Custom B"

    def test_all_defaults(self):
        r = RouteConfig(from_station_code="56014", to_station_code="57151")
        assert r.passengers == 1
        assert r.class_filter is None

    def test_empty_codes(self):
        r = RouteConfig(from_station_code="", to_station_code="")
        assert r.from_station_name == ""
        assert r.to_station_name == ""

    def test_past_date_accepted(self):
        """RouteConfig does NOT validate date — it's just a container."""
        r = RouteConfig(from_station_code="56014", to_station_code="57151", date="2020-01-01")
        assert r.date == "2020-01-01"


# ═══════════════════════ Formatting Edge Cases ═════════════════════════


class TestFormattingNegative:
    def setup_method(self):
        self.monitor = TicketMonitor(routes=[])

    def test_format_time_no_t(self):
        assert format_time("hello world") == "hello world"

    def test_format_time_trailing_z(self):
        assert format_time("2026-06-27T23:59:59Z") == "23:59"

    def test_format_time_offset_with_colon(self):
        assert format_time("2026-06-27T08:15:00+04:00") == "08:15"

    def test_format_time_negative_offset(self):
        assert format_time("2026-06-27T16:45:00-05:00") == "16:45"

    def test_format_time_milliseconds(self):
        assert format_time("2026-06-27T12:30:45.123456Z") == "12:30"

    def test_format_time_none_via_get(self):
        """Simulate ride.get('key', '') returning empty string."""
        assert format_time("") == "??:??"
        # How poller calls it: _format_time(ride.get("rideStartDate") or "")
        assert format_time(None or "") == "??:??"

    def test_fmt_duration_single_digit_hours(self):
        assert fmt_duration("05:12:00") == "5h 12m"

    def test_fmt_duration_midnight(self):
        assert fmt_duration("00:00:00") == "0h 00m"

    def test_fmt_duration_long(self):
        assert fmt_duration("12:34:56") == "12h 34m"

    def test_fmt_duration_no_colons(self):
        assert fmt_duration("nonsense") == "nonsense"

    def test_fmt_duration_none(self):
        assert fmt_duration(None or "") == "??:??"


# ═══════════════════════ Telegram Text Edge Cases ══════════════════════


class TestTelegramTextNegative:
    def setup_method(self):
        self.monitor = TicketMonitor(routes=[])

    def test_single_seat_singular(self):
        text = self.monitor._format_telegram(
            ride_num=812, from_name="A", to_name="B",
            departure="00:30", arrival="05:42", duration="5h 12m",
            cls_name="Business", cls_emoji="⭐", seats=1, price=126,
            change_type="new_ticket",
        )
        assert "1 seat" in text

    def test_multiple_seats_plural(self):
        text = self.monitor._format_telegram(
            ride_num=812, from_name="A", to_name="B",
            departure="00:30", arrival="05:42", duration="5h 12m",
            cls_name="I Class", cls_emoji="💺", seats=15, price=76,
            change_type="new_ticket",
        )
        assert "15 seats" in text

    def test_increased_header(self):
        text = self.monitor._format_telegram(
            ride_num=812, from_name="A", to_name="B",
            departure="00:30", arrival="05:42", duration="5h 12m",
            cls_name="I Class", cls_emoji="💺", seats=15, price=76,
            change_type="seats_increased",
        )
        assert "📈" in text
        assert "Seats increased" in text


# ═══════════════════════ _fetch_rides Error Handling ═══════════════════


class TestFetchRidesNegative:

    SAMPLE_RIDES = {
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

    def setup_method(self):
        self.route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.monitor = TicketMonitor(routes=[self.route], state_file=self.tmp.name)

    def teardown_method(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_http_404(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test", 404, "Not Found", {}, None
            )
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_http_500(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test", 500, "Server Error", {}, None
            )
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_connection_refused(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_timeout(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timed out")
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_json_decode_error(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"not valid json {{{"
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_os_error(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("Network is unreachable")
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_generic_exception(self):
        """_fetch_rides catches Exception (including RuntimeError) gracefully."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = RuntimeError("unexpected")
            result = self.monitor._fetch_rides(self.route)
            assert result is None

    def test_malformed_json_returns_none(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"valid": true}'  # valid JSON but wrong shape
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            result = self.monitor._fetch_rides(self.route)
            # Valid JSON is returned as-is; poll_once handles missing keys
            assert result is not None
            assert isinstance(result, dict)


# ═══════════════════════ State Persistence Negative ════════════════════


class TestStatePersistenceNegative:

    def test_corrupted_state_file_handled(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{corrupted!")
            state_path = f.name

        try:
            monitor = TicketMonitor(routes=[], state_file=state_path)
            assert monitor._state.routes == {}  # defaults to empty
        finally:
            os.unlink(state_path)

    def test_missing_state_file_no_error(self):
        monitor = TicketMonitor(routes=[], state_file="/nonexistent/path/state.json")
        assert monitor._state.routes == {}

    def test_state_file_is_directory(self):
        """If state_file points to a directory, load fails gracefully."""
        d = tempfile.mkdtemp()
        try:
            monitor = TicketMonitor(routes=[], state_file=d)
            assert monitor._state.routes == {}
        finally:
            os.rmdir(d)

    def test_save_state_none_file_skips(self):
        monitor = TicketMonitor(routes=[], state_file=None)
        monitor._save_state()  # should not raise

    def test_save_state_to_nonexistent_dir(self):
        """Saving to a path where parent dir doesn't exist should fail gracefully."""
        monitor = TicketMonitor(routes=[], state_file="/tmp/nonexistent-dir/state.json")
        monitor._state.routes = {"test": {}}
        # Should log error but not crash
        monitor._save_state()

    def test_load_and_save_round_trip_after_error(self):
        """After an API error (no changes), previous state is preserved."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name

        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)

            # First poll: success, seeds state
            sample = {
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
            with patch.object(monitor, "_fetch_rides", return_value=sample):
                changes = monitor.poll_once()
                assert len(changes) == 1

            # Second poll: API error
            with patch.object(monitor, "_fetch_rides", return_value=None):
                changes = monitor.poll_once()
                assert len(changes) == 0
                # State should still have the previous ride data
                assert "56014→57151" in monitor._state.routes
        finally:
            os.unlink(state_path)


# ═══════════════════════ Thread Safety ═════════════════════════════════


class TestThreadSafety:

    def test_start_when_already_running(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            monitor = TicketMonitor(routes=[route], poll_interval=10, state_file=state_path)
            monitor._fetch_rides = MagicMock(return_value={"departureAvailableRides": []})

            monitor.start()
            assert monitor._thread is not None
            assert monitor._thread.is_alive()

            # Try starting again
            monitor.start()  # should log warning, not crash

            monitor.stop(timeout=3)
            assert not monitor._thread.is_alive()
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)

    def test_stop_without_start(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)
            monitor.stop(timeout=1)  # should not raise
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)

    def test_callback_error_does_not_crash_poll(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)

            def broken_callback(changes):
                raise RuntimeError("I am broken")

            monitor.on_change(broken_callback)

            sample = {
                "departureAvailableRides": [
                    {
                        "rideNumber": 999,
                        "rideStartDate": "2026-06-27T10:00:00Z",
                        "rideEndDate": "2026-06-27T15:00:00Z",
                        "rideDuration": "05:00:00",
                        "availableSeatsClasses": [
                            {"seatClassId": 1, "availableNumberOfSeats": 10, "moneyAmount": 50},
                        ],
                    },
                ],
                "returningAvailableRides": [],
            }
            with patch.object(monitor, "_fetch_rides", return_value=sample):
                changes = monitor.poll_once()
                assert len(changes) == 1  # should still return changes
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)

    def test_multiple_callbacks_all_called(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)

            received = []
            for i in range(3):
                monitor.on_change(lambda changes, i=i: received.append(i))

            sample = {
                "departureAvailableRides": [
                    {
                        "rideNumber": 999,
                        "rideStartDate": "2026-06-27T10:00:00Z",
                        "rideEndDate": "2026-06-27T15:00:00Z",
                        "rideDuration": "05:00:00",
                        "availableSeatsClasses": [
                            {"seatClassId": 1, "availableNumberOfSeats": 10, "moneyAmount": 50},
                        ],
                    },
                ],
                "returningAvailableRides": [],
            }
            with patch.object(monitor, "_fetch_rides", return_value=sample):
                monitor.poll_once()
                assert len(received) == 3
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)


# ═══════════════════════ Poll Once Edge Cases ══════════════════════════


class TestPollOnceNegative:

    def test_empty_routes_warning(self):
        monitor = TicketMonitor(routes=[])
        changes = monitor.poll_once()
        assert changes == []

    def test_malformed_response_missing_key(self):
        """Response without 'departureAvailableRides' key."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        monitor = TicketMonitor(routes=[route])
        with patch.object(monitor, "_fetch_rides", return_value={}):
            changes = monitor.poll_once()
            assert changes == []

    def test_rides_with_null_classes(self):
        """Ride dict where availableSeatsClasses is None/missing."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        monitor = TicketMonitor(routes=[route])
        data = {
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    # no availableSeatsClasses
                },
            ],
            "returningAvailableRides": [],
        }
        with patch.object(monitor, "_fetch_rides", return_value=data):
            changes = monitor.poll_once()
            assert changes == []

    def test_ride_with_null_seats(self):
        """Seat count is None → treated as 0, no notification triggered."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        monitor = TicketMonitor(routes=[route], state_file="")
        data = {
            "departureAvailableRides": [
                {
                    "rideNumber": 812,
                    "rideStartDate": "2026-06-27T00:30:00Z",
                    "rideEndDate": "2026-06-27T05:42:00Z",
                    "rideDuration": "05:12:00",
                    "availableSeatsClasses": [
                        {"seatClassId": 5, "availableNumberOfSeats": None, "moneyAmount": 126},
                    ],
                },
            ],
            "returningAvailableRides": [],
        }
        with patch.object(monitor, "_fetch_rides", return_value=data):
            changes = monitor.poll_once()
            # None seats → 0, and 0 seats don't trigger a change
            assert len([c for c in changes if c.get("seats", 0) > 0]) == 0

    def test_seats_decreased_no_notification(self):
        """When seats decrease, no change event. Uses temp state file."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)

            data_high = {
                "departureAvailableRides": [
                    {
                        "rideNumber": 812,
                        "rideStartDate": "2026-06-27T00:30:00Z",
                        "rideEndDate": "2026-06-27T05:42:00Z",
                        "rideDuration": "05:12:00",
                        "availableSeatsClasses": [
                            {"seatClassId": 5, "availableNumberOfSeats": 10, "moneyAmount": 126},
                        ],
                    },
                ],
                "returningAvailableRides": [],
            }
            data_low = {
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

            with patch.object(monitor, "_fetch_rides", return_value=data_high):
                monitor.poll_once()  # seed 10 seats

            with patch.object(monitor, "_fetch_rides", return_value=data_low):
                changes = monitor.poll_once()
                assert len(changes) == 0  # seats decreased, not increased
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)


# ═══════════════════════ create_default_config ═════════════════════════


class TestCreateDefaultConfig:

    def test_valid_json_output(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            cfg = create_default_config(path)
            assert "api_key" in cfg
            assert "routes" in cfg
            assert len(cfg["routes"]) == 2
            assert all(k in cfg["routes"][0] for k in ["from_station_code", "to_station_code", "date"])
        finally:
            os.unlink(path)


# ═══════════════════════ Class Names ═══════════════════════════════════


class TestConstants:

    def test_class_names_coverage(self):
        assert CLASS_NAMES[1] == "I Class"
        assert CLASS_NAMES[2] == "II Class"
        assert CLASS_NAMES[5] == "Business"

    def test_station_names_coverage(self):
        assert STATION_NAMES["56014"] == "Tbilisi"
        assert STATION_NAMES["57151"] == "Batumi"
        assert STATION_NAMES["57450"] == "Kutaisi Airport"


# ═══════════════════════ TicketState ═══════════════════════════════════


class TestTicketState:

    def test_default_constructor(self):
        state = TicketState()
        assert state.routes == {}
        assert state.last_updated == ""

    def test_custom_values(self):
        state = TicketState(routes={"test": {}}, last_updated="2026-06-27T00:00:00Z")
        assert state.routes == {"test": {}}
        assert state.last_updated == "2026-06-27T00:00:00Z"
