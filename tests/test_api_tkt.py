"""Tests for api_tkt.py — TktGeApi class (previously untested).

Covers: init, URL builders, async fetch_json (success, HTTP errors,
connection errors), get_stations/search_trips/get_availability_calendar
delegation, get_seats/get_prices NotImplementedError, trailing slash
stripping, custom api_base/key.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_tkt import TktGeApi, API_BASE, API_KEY
from _api_base import TicketApi


# ═══════════════════════ TktGeApi — Init ═══════════════════════════════


class TestTktGeApiInit:
    def test_default_constructor(self):
        api = TktGeApi()
        assert api.api_base == API_BASE
        assert api.api_key == API_KEY

    def test_custom_base_and_key(self):
        api = TktGeApi(api_base="https://custom.example.com", api_key="my-key")
        assert api.api_base == "https://custom.example.com"
        assert api.api_key == "my-key"

    def test_trailing_slash_stripped(self):
        api = TktGeApi(api_base="https://example.com/api/")
        assert api.api_base == "https://example.com/api"

    def test_no_trailing_slash_preserved(self):
        api = TktGeApi(api_base="https://example.com/api")
        assert api.api_base == "https://example.com/api"

    def test_is_subclass_of_ticket_api(self):
        """After fix: TktGeApi inherits from TicketApi."""
        assert issubclass(TktGeApi, TicketApi)
        api = TktGeApi()
        assert isinstance(api, TicketApi)


# ═══════════════════════ URL Builders ══════════════════════════════════


class TestTktGeApiUrlBuilders:
    def setup_method(self):
        self.api = TktGeApi()

    def test_build_stations_url(self):
        url = self.api._build_stations_url()
        assert "/Dictionaries/civil-stations" in url
        assert "api_key=" in url
        assert url.startswith(API_BASE)

    def test_build_rides_url_minimal(self):
        url = self.api._build_rides_url("56014", "57151", "2026-07-15")
        assert "/Availability/available-rides" in url
        assert "startStationCode=56014" in url
        assert "endStationCode=57151" in url
        assert "departureDateFrom=2026-07-15T00:00:00.000Z" in url
        assert "passengersNumbers=1" in url  # default
        assert "returnWay=false" in url
        assert "disability=false" in url
        assert "api_key=" in url

    def test_build_rides_url_custom_passengers(self):
        url = self.api._build_rides_url("56014", "57151", "2026-07-15", 3)
        assert "passengersNumbers=3" in url

    def test_build_rides_url_zero_passengers(self):
        """Edge: zero passengers still builds valid URL."""
        url = self.api._build_rides_url("56014", "57151", "2026-07-15", 0)
        assert "passengersNumbers=0" in url

    def test_build_rides_url_negative_passengers(self):
        """Edge: negative passengers are passed through."""
        url = self.api._build_rides_url("56014", "57151", "2026-07-15", -1)
        assert "passengersNumbers=-1" in url

    def test_build_calendar_url(self):
        url = self.api._build_calendar_url("56014", "57151")
        assert "/Availability/availability-calendar" in url
        assert "fromStationCode=56014" in url
        assert "toStationCode=57151" in url
        assert "api_key=" in url

    def test_build_stations_url_with_custom_base(self):
        api = TktGeApi(api_base="https://other.example.com/api")
        url = api._build_stations_url()
        assert url.startswith("https://other.example.com/api/")

    def test_all_urls_include_api_key(self):
        for url in [
            self.api._build_stations_url(),
            self.api._build_rides_url("56014", "57151", "2026-07-15"),
            self.api._build_calendar_url("56014", "57151"),
        ]:
            assert f"api_key={API_KEY}" in url


# ═══════════════════════ fetch_json (async) ════════════════════════════


class TestTktGeApiFetchJson:
    def setup_method(self):
        self.api = TktGeApi()

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"data": [1, 2, 3]})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result == {"data": [1, 2, 3]}
        mock_session.get.assert_called_once_with("http://test.local/api", timeout=mock_session.get.call_args[1]["timeout"])

    @pytest.mark.asyncio
    async def test_http_404(self):
        mock_resp = MagicMock()
        mock_resp.status = 404

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_500(self):
        mock_resp = MagicMock()
        mock_resp.status = 500

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_301_redirect(self):
        """Non-200 status codes (including redirects) return None."""
        mock_resp = MagicMock()
        mock_resp.status = 301

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self):
        mock_resp = MagicMock()
        mock_resp.status = 429

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = OSError("Connection refused")

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        import asyncio
        mock_session = MagicMock()
        mock_session.get.side_effect = asyncio.TimeoutError("timeout")

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_json_decode_error(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_response_body(self):
        """HTTP 200 but body is empty / null JSON."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=None)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "test")
        assert result is None  # None is valid JSON, just empty

    @pytest.mark.asyncio
    async def test_label_in_error_does_not_crash(self):
        """Even with label, errors are caught silently."""
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("unknown error")

        result = await self.api.fetch_json(mock_session, "http://test.local/api", "some label")
        assert result is None


# ═══════════════════════ Async API Methods ═════════════════════════════


class TestTktGeApiAsyncMethods:
    def setup_method(self):
        self.api = TktGeApi()

    @pytest.mark.asyncio
    async def test_get_stations_delegates(self):
        mock_session = MagicMock()
        expected_url = self.api._build_stations_url()
        self.api.fetch_json = AsyncMock(return_value=[{"code": 56014, "stationName": "Tbilisi"}])
        result = await self.api.get_stations(mock_session)
        self.api.fetch_json.assert_awaited_once_with(mock_session, expected_url, "stations")
        assert result == [{"code": 56014, "stationName": "Tbilisi"}]

    @pytest.mark.asyncio
    async def test_get_stations_returns_none_on_error(self):
        mock_session = MagicMock()
        self.api.fetch_json = AsyncMock(return_value=None)
        result = await self.api.get_stations(mock_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_search_trips_delegates(self):
        mock_session = MagicMock()
        expected_url = self.api._build_rides_url("56014", "57151", "2026-07-15", 2)
        fake_data = {"departureAvailableRides": []}
        self.api.fetch_json = AsyncMock(return_value=fake_data)
        result = await self.api.search_trips(mock_session, "56014", "57151", "2026-07-15", 2)
        self.api.fetch_json.assert_awaited_once_with(mock_session, expected_url, "rides")
        assert result == fake_data

    @pytest.mark.asyncio
    async def test_search_trips_default_passengers(self):
        mock_session = MagicMock()
        expected_url = self.api._build_rides_url("56014", "57151", "2026-07-15")
        self.api.fetch_json = AsyncMock(return_value={})
        await self.api.search_trips(mock_session, "56014", "57151", "2026-07-15")
        self.api.fetch_json.assert_awaited_once_with(mock_session, expected_url, "rides")

    @pytest.mark.asyncio
    async def test_get_availability_calendar_delegates(self):
        mock_session = MagicMock()
        expected_url = self.api._build_calendar_url("56014", "57151")
        fake_data = {"toDestionation": []}
        self.api.fetch_json = AsyncMock(return_value=fake_data)
        result = await self.api.get_availability_calendar(mock_session, "56014", "57151")
        self.api.fetch_json.assert_awaited_once_with(mock_session, expected_url, "calendar")
        assert result == fake_data

    @pytest.mark.asyncio
    async def test_get_seats_raises_not_implemented(self):
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a per-ride seat"):
            await self.api.get_seats(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_prices_raises_not_implemented(self):
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a dedicated pricing"):
            await self.api.get_prices(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_seats_with_class_id(self):
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError):
            await self.api.get_seats(mock_session, 123, class_id=5)

    @pytest.mark.asyncio
    async def test_get_prices_with_class_id(self):
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError):
            await self.api.get_prices(mock_session, 123, class_id=1)
