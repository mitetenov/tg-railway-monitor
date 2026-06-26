"""Tests for api.py — data parsing and URL construction."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import API_BASE, API_KEY


def test_api_constants():
    """API_BASE and API_KEY are set."""
    assert API_BASE == "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
    assert API_KEY.startswith("7d8d")
    assert len(API_KEY) == 36  # UUID length


def test_api_has_required_functions():
    """Required async functions exist as callable attributes."""
    from api import get_stations, get_available_rides, get_availability_calendar
    for fn in (get_stations, get_available_rides, get_availability_calendar):
        assert callable(fn)


def test_fetch_json_exists():
    """fetch_json utility is importable."""
    from api import fetch_json
    assert callable(fetch_json)
