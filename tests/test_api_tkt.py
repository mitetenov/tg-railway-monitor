"""Tests for api_tkt.py — standalone TktGeApi module.

These tests verify that TktGeApi can be imported directly from api_tkt
without going through api.py, proving the extraction is clean.
"""
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════
# Module-level imports — standalone, no dependency on api.py
# ═══════════════════════════════════════════════════════════════════════

from api_tkt import TktGeApi, API_BASE, API_KEY


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════


def test_api_tkt_constants():
    """api_tkt has API_BASE and API_KEY constants."""
    assert API_BASE == "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
    assert API_KEY == "7d8d34d1-e9af-4897-9f0f-5c36c179be77"
    assert len(API_KEY) == 36  # UUID length


# ═══════════════════════════════════════════════════════════════════════
# Standalone instantiation
# ═══════════════════════════════════════════════════════════════════════


class TestTktGeApiStandalone:
    """TktGeApi works as a standalone class without api.py."""

    def setup_method(self):
        self.api = TktGeApi()

    def test_init_defaults(self):
        """Default constructor uses module-level constants."""
        assert self.api.api_base == API_BASE
        assert self.api.api_key == API_KEY

    def test_init_custom(self):
        """Custom base URL and key are accepted."""
        api = TktGeApi(api_base="https://custom.example.com", api_key="test-key")
        assert api.api_base == "https://custom.example.com"
        assert api.api_key == "test-key"

    def test_build_stations_url(self):
        """Stations URL includes the API key."""
        url = self.api._build_stations_url()
        assert "/Dictionaries/civil-stations" in url
        assert "api_key=" in url
        assert API_KEY in url

    def test_build_rides_url(self):
        """Rides URL includes all required parameters."""
        url = self.api._build_rides_url("56014", "57151", "2026-07-15", 2)
        assert "/Availability/available-rides" in url
        assert "startStationCode=56014" in url
        assert "endStationCode=57151" in url
        assert "departureDateFrom=2026-07-15T00:00:00.000Z" in url
        assert "passengersNumbers=2" in url
        assert "returnWay=false" in url
        assert "disability=false" in url
        assert f"api_key={API_KEY}" in url

    def test_build_rides_url_default_passengers(self):
        """Rides URL defaults to 1 passenger."""
        url = self.api._build_rides_url("56014", "57151", "2026-07-15")
        assert "passengersNumbers=1" in url

    def test_build_calendar_url(self):
        """Calendar URL includes station codes and API key."""
        url = self.api._build_calendar_url("56014", "57151")
        assert "/Availability/availability-calendar" in url
        assert "fromStationCode=56014" in url
        assert "toStationCode=57151" in url
        assert f"api_key={API_KEY}" in url

    @pytest.mark.asyncio
    async def test_get_stations_delegates_to_fetch_json(self):
        """get_stations builds the right URL and uses fetch_json."""
        mock_session = MagicMock()
        url = self.api._build_stations_url()
        self.api.fetch_json = AsyncMock(return_value=[{"code": 56014}])
        result = await self.api.get_stations(mock_session)
        self.api.fetch_json.assert_awaited_once_with(mock_session, url, "stations")
        assert result == [{"code": 56014}]

    @pytest.mark.asyncio
    async def test_search_trips_delegates_to_fetch_json(self):
        """search_trips builds the right URL and uses fetch_json."""
        mock_session = MagicMock()
        url = self.api._build_rides_url("56014", "57151", "2026-07-15")
        self.api.fetch_json = AsyncMock(return_value={"departureAvailableRides": []})
        result = await self.api.search_trips(mock_session, "56014", "57151", "2026-07-15")
        self.api.fetch_json.assert_awaited_once_with(mock_session, url, "rides")
        assert result == {"departureAvailableRides": []}

    @pytest.mark.asyncio
    async def test_get_availability_calendar_delegates_to_fetch_json(self):
        """get_availability_calendar builds the right URL."""
        mock_session = MagicMock()
        url = self.api._build_calendar_url("56014", "57151")
        self.api.fetch_json = AsyncMock(return_value={"toDestionation": []})
        result = await self.api.get_availability_calendar(mock_session, "56014", "57151")
        self.api.fetch_json.assert_awaited_once_with(mock_session, url, "calendar")
        assert result == {"toDestionation": []}

    @pytest.mark.asyncio
    async def test_get_seats_raises_not_implemented(self):
        """get_seats raises NotImplementedError when used standalone."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a per-ride seat map"):
            await self.api.get_seats(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_prices_raises_not_implemented(self):
        """get_prices raises NotImplementedError when used standalone."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a dedicated pricing"):
            await self.api.get_prices(mock_session, 123)

    @pytest.mark.asyncio
    async def test_fetch_json_success(self):
        """fetch_json returns parsed JSON on HTTP 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"key": "value"})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock(spec=["get"])
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://example.com/api", "test")
        assert result == {"key": "value"}
        mock_session.get.assert_called_once()
        assert mock_session.get.call_args[0][0] == "http://example.com/api"

    @pytest.mark.asyncio
    async def test_fetch_json_http_error(self):
        """fetch_json returns None on non-200."""
        mock_resp = MagicMock()
        mock_resp.status = 500

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock(spec=["get"])
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://example.com/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_json_exception(self):
        """fetch_json returns None on network error."""
        mock_session = MagicMock(spec=["get"])
        mock_session.get.side_effect = OSError("connection lost")

        result = await self.api.fetch_json(mock_session, "http://example.com/api", "test")
        assert result is None

    def test_api_base_trailing_slash_stripped(self):
        """Trailing slash is stripped from api_base."""
        api = TktGeApi(api_base="https://example.com/api/")
        assert api.api_base == "https://example.com/api"

    def test_api_base_no_trailing_slash_unchanged(self):
        """api_base without trailing slash is unchanged."""
        api = TktGeApi(api_base="https://example.com/api")
        assert api.api_base == "https://example.com/api"


# ═══════════════════════════════════════════════════════════════════════
# Cross-module consistency: api.py re-exports TktGeApi from api_tkt
# ═══════════════════════════════════════════════════════════════════════


def test_tktgeapi_from_api_is_same_class():
    """TktGeApi imported from api.py is the same class as from api_tkt."""
    from api import TktGeApi as ApiTktGeApi
    assert ApiTktGeApi is TktGeApi


def test_tktgeapi_instance_compatible_with_factory():
    """TktGeApi instance from api_tkt works with api.py's factory."""
    from api import get_ticket_api, _SOURCE_REGISTRY

    api = get_ticket_api("tktge")
    assert isinstance(api, TktGeApi)
    assert callable(api.get_stations)
    assert callable(api.search_trips)
    assert callable(api.get_availability_calendar)
    assert callable(api.get_seats)
    assert callable(api.get_prices)
