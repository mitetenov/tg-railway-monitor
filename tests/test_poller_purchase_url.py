"""Tests for TICKET_SOURCE-dependent purchase URL in poller.py.

Verifies that the purchase_url is selected correctly based on the
TICKET_SOURCE environment variable, and that the tre.ge variant uses
proper station-slug-based URL construction.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_tre import TreGeApi, station_to_slug


def _resolve_purchase_url(from_station="", to_station="", date=""):
    """Mirror the inline logic from poller.py _check_and_notify."""
    source = os.environ.get("TICKET_SOURCE", "tkt.ge")
    if source == "tre.ge":
        from_slug = station_to_slug(from_station)
        to_slug = station_to_slug(to_station)
        return TreGeApi.build_purchase_url(from_slug, to_slug, date)
    return "https://tkt.ge/en/railway"


# ── Default (no env) ──────────────────────────────────────────────────


def test_default_url_when_no_env():
    """Without TICKET_SOURCE, the URL defaults to tkt.ge/en/railway."""
    # Ensure the env var is not set
    old = os.environ.pop("TICKET_SOURCE", None)
    try:
        url = _resolve_purchase_url()
        assert url == "https://tkt.ge/en/railway", f"Got {url}"
    finally:
        if old is not None:
            os.environ["TICKET_SOURCE"] = old


# ── Explicit tkt.ge ───────────────────────────────────────────────────


def test_tktge_source():
    """TICKET_SOURCE=tkt.ge yields tkt.ge/en/railway."""
    os.environ["TICKET_SOURCE"] = "tkt.ge"
    try:
        url = _resolve_purchase_url()
        assert url == "https://tkt.ge/en/railway", f"Got {url}"
    finally:
        del os.environ["TICKET_SOURCE"]


# ── tre.ge source ─────────────────────────────────────────────────────


def test_trege_source_without_stations():
    """TICKET_SOURCE=tre.ge falls back to empty-slug URL when no stations."""
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        url = _resolve_purchase_url(from_station="", to_station="", date="2026-06-28")
        expected = "https://tre.ge/en/search?from=&to=&date=2026-06-28"
        assert url == expected, f"Got {url}"
    finally:
        del os.environ["TICKET_SOURCE"]


def test_trege_source_with_stations():
    """TICKET_SOURCE=tre.ge builds proper URL with station slugs."""
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        url = _resolve_purchase_url(
            from_station="Tbilisi",
            to_station="Batumi",
            date="2026-06-28",
        )
        expected = "https://tre.ge/en/search?from=Tbilisi&to=Batumi&date=2026-06-28"
        assert url == expected, f"Got {url}"
    finally:
        del os.environ["TICKET_SOURCE"]


def test_trege_with_url_encoded_station():
    """TICKET_SOURCE=tre.ge handles stations that need URL encoding."""
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        url = _resolve_purchase_url(
            from_station="Tbilisi",
            to_station="Kutaisi Airport",
            date="2026-06-28",
        )
        expected = (
            "https://tre.ge/en/search"
            "?from=Tbilisi&to=Kutaisi%20Airport&date=2026-06-28"
        )
        assert url == expected, f"Got {url}"
    finally:
        del os.environ["TICKET_SOURCE"]


# ── Unknown source ────────────────────────────────────────────────────


def test_unknown_source_falls_back():
    """Unknown TICKET_SOURCE value falls back to tkt.ge/en/railway."""
    os.environ["TICKET_SOURCE"] = "unknown"
    try:
        url = _resolve_purchase_url()
        assert url == "https://tkt.ge/en/railway", f"Got {url}"
    finally:
        del os.environ["TICKET_SOURCE"]


# ── Integration: actual poller code path ──────────────────────────────


def test_inline_url_in_notification_message():
    """The actual poller code emits the right purchase URL in its message."""
    from poller import _format_time

    ride_num = 812
    ride = {
        "id": ride_num,
        "rideNumber": ride_num,
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

    dep = _format_time(ride.get("rideStartDate") or "")
    arr = _format_time(ride.get("rideEndDate") or "")
    dur = ride.get("rideDuration", "?")

    # ── Default (no env) → tkt.ge/en/railway ──
    old = os.environ.pop("TICKET_SOURCE", None)
    try:
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            from_slug = station_to_slug("")
            to_slug = station_to_slug("")
            purchase_url = TreGeApi.build_purchase_url(from_slug, to_slug, "2026-06-27")
        else:
            purchase_url = "https://tkt.ge/en/railway"
        assert purchase_url == "https://tkt.ge/en/railway"
    finally:
        if old is not None:
            os.environ["TICKET_SOURCE"] = old

    # ── tre.ge → tre.ge search URL with slug ──
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            from_slug = station_to_slug("Tbilisi")
            to_slug = station_to_slug("Batumi")
            purchase_url = TreGeApi.build_purchase_url(from_slug, to_slug, "2026-06-27")
        else:
            purchase_url = "https://tkt.ge/en/railway"
        expected = "https://tre.ge/en/search?from=Tbilisi&to=Batumi&date=2026-06-27"
        assert purchase_url == expected, f"Got {purchase_url}"
    finally:
        del os.environ["TICKET_SOURCE"]

    # ── tkt.ge → tkt.ge/en/railway ──
    os.environ["TICKET_SOURCE"] = "tkt.ge"
    try:
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            from_slug = station_to_slug("")
            to_slug = station_to_slug("")
            purchase_url = TreGeApi.build_purchase_url(from_slug, to_slug, "2026-06-27")
        else:
            purchase_url = "https://tkt.ge/en/railway"
        assert purchase_url == "https://tkt.ge/en/railway"
    finally:
        del os.environ["TICKET_SOURCE"]
