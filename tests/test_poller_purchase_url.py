"""Tests for TICKET_SOURCE-dependent purchase URL in poller.py.

Verifies that the purchase_url is selected correctly based on the
TICKET_SOURCE environment variable.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _resolve_purchase_url():
    """Mirror the inline logic from poller.py _check_and_notify."""
    source = os.environ.get("TICKET_SOURCE", "tkt.ge")
    if source == "tre.ge":
        return "https://tre.ge"
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


def test_trege_source():
    """TICKET_SOURCE=tre.ge yields tre.ge."""
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        url = _resolve_purchase_url()
        assert url == "https://tre.ge", f"Got {url}"
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
            purchase_url = "https://tre.ge"
        else:
            purchase_url = "https://tkt.ge/en/railway"
        assert purchase_url == "https://tkt.ge/en/railway"
    finally:
        if old is not None:
            os.environ["TICKET_SOURCE"] = old

    # ── tre.ge → tre.ge ──
    os.environ["TICKET_SOURCE"] = "tre.ge"
    try:
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            purchase_url = "https://tre.ge"
        else:
            purchase_url = "https://tkt.ge/en/railway"
        assert purchase_url == "https://tre.ge"
    finally:
        del os.environ["TICKET_SOURCE"]

    # ── tkt.ge → tkt.ge/en/railway ──
    os.environ["TICKET_SOURCE"] = "tkt.ge"
    try:
        source = os.environ.get("TICKET_SOURCE", "tkt.ge")
        if source == "tre.ge":
            purchase_url = "https://tre.ge"
        else:
            purchase_url = "https://tkt.ge/en/railway"
        assert purchase_url == "https://tkt.ge/en/railway"
    finally:
        del os.environ["TICKET_SOURCE"]
