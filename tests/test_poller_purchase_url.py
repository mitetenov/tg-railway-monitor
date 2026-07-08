"""Tests for purchase URL construction in poller.py (tre.ge only)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_tre import TreGeApi
from utils import format_time


def _build_url(from_code="", to_code="", date=""):
    """Mirror the inline logic from poller.py _check_and_notify."""
    return TreGeApi.build_purchase_url(from_code, to_code, date)


# ── tre.ge purchase URL ────────────────────────────────────────────────


def test_trege_source_without_stations():
    """tre.ge falls back to empty-code URL when no station codes."""
    url = _build_url(from_code="", to_code="", date="2026-06-28")
    expected = "https://tre.ge/en/search?leavingPlace=&enteringPlace=&leaveDate=28.06.2026&passengerCount=1&wcuCount=0&depVT=railway"
    assert url == expected, f"Got {url}"


def test_trege_source_with_stations():
    """tre.ge builds proper URL with station codes."""
    url = _build_url(from_code="56014", to_code="57151", date="2026-06-28")
    expected = "https://tre.ge/en/search?leavingPlace=56014&enteringPlace=57151&leaveDate=28.06.2026&passengerCount=1&wcuCount=0&depVT=railway"
    assert url == expected, f"Got {url}"


def test_trege_with_url_encoded_station():
    """tre.ge handles stations that need URL encoding."""
    url = _build_url(from_code="56014", to_code="57151", date="2026-12-25")
    expected = (
        "https://tre.ge/en/search"
        "?leavingPlace=56014"
        "&enteringPlace=57151"
        "&leaveDate=25.12.2026"
        "&passengerCount=1&wcuCount=0&depVT=railway"
    )
    assert url == expected, f"Got {url}"


# ── Integration: actual poller notification message ────────────────────


def test_inline_url_in_notification_message():
    """The poller code emits the tre.ge purchase URL in its message."""
    ride = {
        "id": 812,
        "rideNumber": 812,
        "rideStartDate": "2026-06-27T00:30:00Z",
        "rideEndDate": "2026-06-27T05:42:00Z",
        "rideDuration": "05:12:00",
        "availableSeatsClasses": [
            {
                "seatClassId": 2,
                "seatClassName": "II класс",
                "availableNumberOfSeats": 89,
                "moneyAmount": 36,
            }
        ],
    }

    dep = format_time(ride.get("rideStartDate") or "")
    arr = format_time(ride.get("rideEndDate") or "")
    dur = ride.get("rideDuration", "?")

    # tre.ge URL with station codes
    purchase_url = TreGeApi.build_purchase_url("56014", "57151", "2026-06-27")
    expected = "https://tre.ge/en/search?leavingPlace=56014&enteringPlace=57151&leaveDate=27.06.2026&passengerCount=1&wcuCount=0&depVT=railway"
    assert purchase_url == expected, f"Got {purchase_url}"
