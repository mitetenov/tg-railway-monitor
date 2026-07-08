#!/usr/bin/env python3
"""
Tests for ticket_monitor.py — unit tests for state diff, formatting,
config loading, and a live API integration test.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# Add parent to path so we can import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ticket_monitor import (
    TicketMonitor,
    RouteConfig,
    TicketState,
    create_default_config,
    STATION_NAMES,
    CLASS_NAMES,
    CLASS_EMOJI,
)
from utils import format_time, fmt_duration


class TestRouteConfig(unittest.TestCase):
    """RouteConfig auto-fill and defaults."""

    def test_auto_name_from_code(self):
        r = RouteConfig(from_station_code="56014", to_station_code="57151")
        self.assertEqual(r.from_station_name, "Tbilisi")
        self.assertEqual(r.to_station_name, "Batumi")

    def test_auto_date_tomorrow(self):
        from datetime import datetime, timezone, timedelta
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        r = RouteConfig(from_station_code="56014", to_station_code="57151")
        self.assertEqual(r.date, tomorrow)

    def test_explicit_values(self):
        r = RouteConfig(
            from_station_code="56014",
            to_station_code="57151",
            from_station_name="MyCity",
            to_station_name="OtherCity",
            date="2026-07-01",
            class_filter=1,
            passengers=2,
        )
        self.assertEqual(r.from_station_name, "MyCity")
        self.assertEqual(r.to_station_name, "OtherCity")
        self.assertEqual(r.date, "2026-07-01")
        self.assertEqual(r.class_filter, 1)
        self.assertEqual(r.passengers, 2)

    def test_unknown_code(self):
        r = RouteConfig(from_station_code="99999", to_station_code="88888")
        self.assertEqual(r.from_station_name, "99999")
        self.assertEqual(r.to_station_name, "88888")


class TestFormatting(unittest.TestCase):
    """Message formatting helpers."""

    def setUp(self):
        self.monitor = TicketMonitor(routes=[])

    def test_format_time_iso(self):
        self.assertEqual(format_time("2026-06-27T00:30:00Z"), "00:30")
        self.assertEqual(format_time("2026-06-27T05:42:00+04:00"), "05:42")

    def test_format_time_empty(self):
        self.assertEqual(format_time(""), "??:??")

    def test_fmt_duration_full(self):
        self.assertEqual(fmt_duration("05:12:00"), "5h 12m")

    def test_fmt_duration_single_digit(self):
        self.assertEqual(fmt_duration("01:05:00"), "1h 05m")

    def test_fmt_duration_empty(self):
        self.assertEqual(fmt_duration(""), "??:??")

    def test_telegram_new_ticket(self):
        text = self.monitor._format_telegram(
            ride_num=812,
            from_name="Tbilisi",
            to_name="Batumi",
            departure="00:30",
            arrival="05:42",
            duration="5h 12m",
            cls_name="Business",
            cls_emoji="⭐",
            seats=3,
            price=126,
            change_type="new_ticket",
        )
        self.assertIn("New ticket available", text)
        self.assertIn("#812", text)
        self.assertIn("Tbilisi", text)
        self.assertIn("Batumi", text)
        self.assertIn("00:30", text)
        self.assertIn("05:42", text)
        self.assertIn("126 GEL", text)
        self.assertIn("3 seats", text)

    def test_telegram_increased(self):
        text = self.monitor._format_telegram(
            ride_num=812,
            from_name="Tbilisi",
            to_name="Batumi",
            departure="00:30",
            arrival="05:42",
            duration="5h 12m",
            cls_name="I Class",
            cls_emoji="💺",
            seats=15,
            price=76,
            change_type="seats_increased",
        )
        self.assertIn("Seats increased", text)
        self.assertIn("15 seats", text)


class TestStateDiff(unittest.TestCase):
    """State comparison logic using mocked API data."""

    SAMPLE_RIDES = {
        "isAnyDepartureTripAvailable": True,
        "isAnyReturningTripAvailable": False,
        "departureAvailableRides": [
            {
                "rideNumber": 812,
                "rideStartDate": "2026-06-27T00:30:00Z",
                "rideEndDate": "2026-06-27T05:42:00Z",
                "rideDuration": "05:12:00",
                "stationFromName": "თბილისი",
                "stationToName": "ბათუმი",
                "rideStationFromName": "თბილისი",
                "rideStationToName": "ბათუმი",
                "availableSeatsClasses": [
                    {"seatClassId": 2, "availableNumberOfSeats": 1, "moneyAmount": 36, "seatClassName": "II კლასი"},
                    {"seatClassId": 1, "availableNumberOfSeats": 15, "moneyAmount": 76, "seatClassName": "I კლასი"},
                    {"seatClassId": 5, "availableNumberOfSeats": 3, "moneyAmount": 126, "seatClassName": "ბიზ. კლასი"},
                ],
            },
            {
                "rideNumber": 302,
                "rideStartDate": "2026-06-27T07:00:00Z",
                "rideEndDate": "2026-06-27T12:00:00Z",
                "rideDuration": "05:00:00",
                "rideStationFromName": "თბილისი",
                "rideStationToName": "ბათუმი",
                "availableSeatsClasses": [
                    {"seatClassId": 1, "availableNumberOfSeats": 5, "moneyAmount": 76, "seatClassName": "I კლასი"},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    def setUp(self):
        self._state_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._state_file.close()
        self.route = RouteConfig(
            from_station_code="56014",
            to_station_code="57151",
            date="2026-06-27",
        )
        self.monitor = TicketMonitor(routes=[self.route], state_file=self._state_file.name)

    def tearDown(self):
        try:
            os.unlink(self._state_file.name)
        except OSError:
            pass

    def test_first_poll_all_new(self):
        """First poll with empty state should detect all tickets as new."""
        with patch.object(self.monitor, "_fetch_rides", return_value=self.SAMPLE_RIDES):
            changes = self.monitor.poll_once()
            # 3 classes on ride 812 + 1 class on ride 302 = 4 new tickets
            self.assertEqual(len(changes), 4)
            for c in changes:
                self.assertEqual(c["type"], "new_ticket")

    def test_second_poll_no_changes(self):
        """Second poll with same data should detect no changes."""
        with patch.object(self.monitor, "_fetch_rides", return_value=self.SAMPLE_RIDES):
            self.monitor.poll_once()  # first poll
            changes = self.monitor.poll_once()  # second poll
            self.assertEqual(len(changes), 0)

    def test_seats_increased(self):
        """Detect when available seats increase."""
        with patch.object(self.monitor, "_fetch_rides", return_value=self.SAMPLE_RIDES):
            self.monitor.poll_once()  # seed state

        # Now return modified data with more seats on ride 812, class I (id=1)
        modified_rides = json.loads(json.dumps(self.SAMPLE_RIDES))
        modified_rides["departureAvailableRides"][0]["availableSeatsClasses"][1]["availableNumberOfSeats"] = 25

        with patch.object(self.monitor, "_fetch_rides", return_value=modified_rides):
            changes = self.monitor.poll_once()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["type"], "seats_increased")
            self.assertEqual(changes[0]["ride_number"], 812)
            self.assertEqual(changes[0]["seat_class_id"], 1)
            self.assertEqual(changes[0]["seats"], 25)

    def test_api_failure(self):
        """API failure should not crash the monitor or corrupt state."""
        with patch.object(self.monitor, "_fetch_rides", return_value=None):
            changes = self.monitor.poll_once()
            self.assertEqual(len(changes), 0)

    def test_class_filter(self):
        """class_filter should only report changes for the matching class."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as sf:
            state_path = sf.name
        try:
            filtered_route = RouteConfig(
                from_station_code="56014",
                to_station_code="57151",
                date="2026-06-27",
                class_filter=5,  # Business only
            )
            monitor = TicketMonitor(routes=[filtered_route], state_file=state_path)
            with patch.object(monitor, "_fetch_rides", return_value=self.SAMPLE_RIDES):
                changes = monitor.poll_once()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["seat_class_id"], 5)
        finally:
            os.unlink(state_path)


class TestConfigLoading(unittest.TestCase):
    """Config-from-file and create_default_config."""

    def test_create_default_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            cfg = create_default_config(path)
            self.assertIn("api_key", cfg)
            self.assertIn("routes", cfg)
            self.assertGreater(len(cfg["routes"]), 0)
            # Verify we can load it back
            monitor = TicketMonitor(config=path)
            self.assertGreater(len(monitor.routes), 0)
        finally:
            os.unlink(path)

    def test_config_dict_injection(self):
        cfg = {
            "api_key": "test-key",
            "poll_interval": 30,
            "routes": [
                {"from_station_code": "56014", "to_station_code": "57151"},
            ],
        }
        monitor = TicketMonitor(config=cfg)
        self.assertEqual(monitor.api_key, "test-key")
        self.assertEqual(monitor.poll_interval, 30)
        self.assertEqual(len(monitor.routes), 1)

    def test_constructor_override_config(self):
        cfg = {"poll_interval": 120, "routes": []}
        monitor = TicketMonitor(config=cfg, api_key="override-key", poll_interval=99)
        self.assertEqual(monitor.api_key, "override-key")
        self.assertEqual(monitor.poll_interval, 99)


class TestStatePersistence(unittest.TestCase):
    """State save/load round-trip."""

    SAMPLE_RIDES = {
        "isAnyDepartureTripAvailable": True,
        "isAnyReturningTripAvailable": False,
        "departureAvailableRides": [
            {
                "rideNumber": 812,
                "rideStartDate": "2026-06-27T00:30:00Z",
                "rideEndDate": "2026-06-27T05:42:00Z",
                "rideDuration": "05:12:00",
                "stationFromName": "თბილისი",
                "stationToName": "ბათუმი",
                "rideStationFromName": "თბილისი",
                "rideStationToName": "ბათუმი",
                "availableSeatsClasses": [
                    {"seatClassId": 2, "availableNumberOfSeats": 1, "moneyAmount": 36, "seatClassName": "II კლასი"},
                    {"seatClassId": 1, "availableNumberOfSeats": 15, "moneyAmount": 76, "seatClassName": "I კლასი"},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    def test_round_trip(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date="2026-06-27")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = f.name

        try:
            monitor = TicketMonitor(routes=[route], state_file=state_path)
            # First poll seeds state and saves it
            with patch.object(monitor, "_fetch_rides", return_value=self.SAMPLE_RIDES):
                monitor.poll_once()

            # Verify file was written
            with open(state_path) as f:
                saved = json.load(f)
            self.assertIn("routes", saved)
            self.assertIn("56014→57151", saved["routes"])
            self.assertIn("812", saved["routes"]["56014→57151"])

            # Create a new monitor that loads from saved state
            monitor2 = TicketMonitor(routes=[route], state_file=state_path)
            self.assertIn("812", monitor2._state.routes.get("56014→57151", {}))

            # Second poll with same data → no changes
            with patch.object(monitor2, "_fetch_rides", return_value=self.SAMPLE_RIDES):
                changes = monitor2.poll_once()
            self.assertEqual(len(changes), 0)
        finally:
            os.unlink(state_path)


class TestLiveAPI(unittest.TestCase):
    """Live integration test against the API.
    Marked as optional — skip if network is unavailable or expected to fail.
    """

    def test_live_fetch(self):
        """Actually hit the API for Tbilisi→Batumi, tomorrow."""
        from datetime import datetime, timezone, timedelta
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        route = RouteConfig(from_station_code="56014", to_station_code="57151", date=tomorrow)
        monitor = TicketMonitor(routes=[route])
        changes = monitor.poll_once()
        # We don't expect specific changes — just that it doesn't crash
        # and returns a list
        self.assertIsInstance(changes, list)
        print(f"\n  Live API returned {len(monitor._state.routes.get('56014→57151', {}))} rides")
        if changes:
            for c in changes[:2]:  # show first 2
                print(f"  {c['telegram_text'][:80]}...")


class TestBackgroundThread(unittest.TestCase):
    """Threaded polling smoke test."""

    SAMPLE_RIDES = {
        "isAnyDepartureTripAvailable": True,
        "departureAvailableRides": [
            {
                "rideNumber": 999,
                "rideStartDate": "2026-06-27T10:00:00Z",
                "rideEndDate": "2026-06-27T15:00:00Z",
                "rideDuration": "05:00:00",
                "stationFromName": "A",
                "stationToName": "B",
                "rideStationFromName": "A",
                "rideStationToName": "B",
                "availableSeatsClasses": [
                    {"seatClassId": 1, "availableNumberOfSeats": 10, "moneyAmount": 50},
                ],
            },
        ],
        "returningAvailableRides": [],
    }

    def test_start_stop(self):
        route = RouteConfig(from_station_code="56014", to_station_code="57151")
        monitor = TicketMonitor(routes=[route], poll_interval=1)
        # Mock the fetch so the thread doesn't hit the real API
        monitor._fetch_rides = MagicMock(return_value=self.SAMPLE_RIDES)

        monitor.start()
        self.assertTrue(monitor._thread is not None)
        self.assertTrue(monitor._thread.is_alive())

        # Let it poll once
        time.sleep(0.3)

        monitor.stop(timeout=3)
        self.assertFalse(monitor._thread.is_alive())

    def test_on_change_callback(self):
        """Callback should fire when changes are detected."""
        route = RouteConfig(from_station_code="56014", to_station_code="57151")
        monitor = TicketMonitor(routes=[route], poll_interval=1)
        monitor._fetch_rides = MagicMock(return_value=self.SAMPLE_RIDES)

        callback_results = []
        monitor.on_change(lambda changes: callback_results.extend(changes))

        monitor.poll_once()
        self.assertGreater(len(callback_results), 0)
        self.assertEqual(callback_results[0]["type"], "new_ticket")


if __name__ == "__main__":
    verbosity = 2 if "-v" in sys.argv else 1
    unittest.main(verbosity=verbosity)
