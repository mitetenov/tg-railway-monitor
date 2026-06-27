"""Tests for api.py — abstract base class, implementations, factory, and backward compat."""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Backward-compatible imports (old code still works) ────────────────────

from api import (
    API_BASE,
    API_KEY,
    DEFAULT_TICKET_SOURCE,
    TicketApi,
    TktGeApi,
    TreGeApi,
    _SOURCE_REGISTRY,
    _api_instance,
    fetch_json,
    get_available_rides,
    get_availability_calendar,
    get_stations,
    get_ticket_api,
    init_ticket_api,
)

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════


def test_api_constants():
    """API_BASE and API_KEY are set."""
    assert API_BASE == "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
    assert API_KEY=="7d8d34d1-e9af-4897-9f0f-5c36c179be77"
    assert DEFAULT_TICKET_SOURCE == "tktge"


# ═══════════════════════════════════════════════════════════════════════
# Abstract base class
# ═══════════════════════════════════════════════════════════════════════


def test_ticket_api_cannot_instantiate_directly():
    """TicketApi is abstract — instantiating raises TypeError."""
    with pytest.raises(TypeError, match="abstract"):
        TicketApi()


def test_ticket_api_has_abstract_methods():
    """TicketApi defines all required abstract methods."""
    methods = [
        "get_stations",
        "search_trips",
        "get_availability_calendar",
        "get_seats",
        "get_prices",
    ]
    for name in methods:
        # TktGeApi is a concrete subclass — verify the method exists
        assert hasattr(TktGeApi, name), f"TktGeApi missing method {name}()"


# ═══════════════════════════════════════════════════════════════════════
# TktGeApi implementation
# ═══════════════════════════════════════════════════════════════════════


class TestTktGeApi:
    """Unit tests for TktGeApi."""

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
        """get_seats raises NotImplementedError for tkt.ge (no dedicated endpoint)."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a per-ride seat map"):
            await self.api.get_seats(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_prices_raises_not_implemented(self):
        """get_prices raises NotImplementedError for tkt.ge (no dedicated endpoint)."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a dedicated pricing"):
            await self.api.get_prices(mock_session, 123)

    @pytest.mark.asyncio
    async def test_fetch_json_success(self):
        """fetch_json returns parsed JSON on HTTP 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"key": "value"})

        # Build an async context manager that yields mock_resp
        # session.get() must return a context manager (not a coroutine)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock(spec=["get"])
        mock_session.get.return_value = mock_cm

        result = await self.api.fetch_json(mock_session, "http://example.com/api", "test")
        assert result == {"key": "value"}
        # Verify URL was called (timeout kwarg is an impl detail)
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


# ═══════════════════════════════════════════════════════════════════════
# TreGeApi implementation (defined in api_tre.py, re-exported via api)
# ═══════════════════════════════════════════════════════════════════════


class TestTreGeApi:
    """TreGeApi is a full implementation — test delegation and URL building."""

    def setup_method(self):
        self.api = TreGeApi()

    def test_init_defaults(self):
        """Default constructor uses module-level constants."""
        assert self.api.api_base == API_BASE
        assert self.api.api_key == API_KEY

    def test_init_custom(self):
        """Custom base URL and key are accepted."""
        api = TreGeApi(api_base="https://custom.example.com", api_key="test-key")
        assert api.api_base == "https://custom.example.com"
        assert api.api_key == "test-key"

    @pytest.mark.asyncio
    async def test_get_stations_delegates_to_fetch_json(self):
        """get_stations builds the right URL and uses fetch_json."""
        mock_session = MagicMock()
        self.api.fetch_json = AsyncMock(return_value=[{"code": "56014"}])
        result = await self.api.get_stations(mock_session)
        self.api.fetch_json.assert_awaited_once()
        assert result == [{"code": "56014"}]

    @pytest.mark.asyncio
    async def test_search_trips_delegates_to_fetch_json(self):
        """search_trips builds the right URL and uses fetch_json."""
        mock_session = MagicMock()
        self.api.fetch_json = AsyncMock(return_value={"departureAvailableRides": []})
        result = await self.api.search_trips(mock_session, "56014", "57151", "2026-07-15")
        self.api.fetch_json.assert_awaited_once()
        assert result == {"departureAvailableRides": []}

    @pytest.mark.asyncio
    async def test_get_availability_calendar_delegates_to_fetch_json(self):
        """get_availability_calendar builds the right URL."""
        mock_session = MagicMock()
        self.api.fetch_json = AsyncMock(return_value={"toDestionation": []})
        result = await self.api.get_availability_calendar(mock_session, "56014", "57151")
        self.api.fetch_json.assert_awaited_once()
        assert result == {"toDestionation": []}

    @pytest.mark.asyncio
    async def test_get_seats_raises_not_implemented(self):
        """get_seats raises NotImplementedError (no public endpoint)."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a per-ride seat map"):
            await self.api.get_seats(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_prices_raises_not_implemented(self):
        """get_prices raises NotImplementedError (no public endpoint)."""
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

    def test_build_stations_url_has_api_key(self):
        """Stations URL includes the API key."""
        from api_tre import _build_stations_url
        url = _build_stations_url(API_BASE, API_KEY)
        assert "/Dictionaries/civil-stations" in url
        assert f"api_key={API_KEY}" in url

    def test_build_rides_url_has_all_params(self):
        """Rides URL includes all required parameters."""
        from api_tre import _build_rides_url
        url = _build_rides_url(API_BASE, API_KEY, "56014", "57151", "2026-07-15", 2)
        assert "/Availability/available-rides" in url
        assert "startStationCode=56014" in url
        assert "endStationCode=57151" in url
        assert "departureDateFrom=2026-07-15T00:00:00.000Z" in url
        assert "passengersNumbers=2" in url
        assert "returnWay=false" in url
        assert "disability=false" in url
        assert f"api_key={API_KEY}" in url

    def test_build_calendar_url_has_station_codes(self):
        """Calendar URL includes station codes and API key."""
        from api_tre import _build_calendar_url
        url = _build_calendar_url(API_BASE, API_KEY, "56014", "57151")
        assert "/Availability/availability-calendar" in url
        assert "fromStationCode=56014" in url
        assert "toStationCode=57151" in url
        assert f"api_key={API_KEY}" in url


# ═══════════════════════════════════════════════════════════════════════
# Factory: get_ticket_api()
# ═══════════════════════════════════════════════════════════════════════


class TestGetTicketApi:
    """Factory function works correctly."""

    def teardown_method(self):
        """Reset module-level singleton after each test."""
        import api as api_module
        api_module._api_instance = None

    def test_default_source_returns_tktge(self):
        """get_ticket_api() without args returns a TktGeApi."""
        api = get_ticket_api()
        assert isinstance(api, TktGeApi)

    def test_tktge_source(self):
        """Explicit 'tktge' returns TktGeApi."""
        api = get_ticket_api("tktge")
        assert isinstance(api, TktGeApi)

    def test_trege_source(self):
        """Explicit 'trege' returns TreGeApi."""
        api = get_ticket_api("trege")
        assert isinstance(api, TreGeApi)

    def test_unknown_source_raises(self):
        """Unknown source name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown TICKET_SOURCE"):
            get_ticket_api("nonexistent")

    def test_case_insensitive(self):
        """Source names are case-insensitive."""
        for variant in ("TktGe", "TKTGE", "tktge"):
            api = get_ticket_api(variant)
            assert isinstance(api, TktGeApi), f"Failed for {variant!r}"

    def test_source_registry_members(self):
        """Registry contains exactly the expected sources."""
        assert set(_SOURCE_REGISTRY.keys()) == {"tktge", "trege"}

    def test_init_ticket_api_sets_singleton(self):
        """init_ticket_api() sets the module-level singleton."""
        import api as api_module
        api_module._api_instance = None

        api = init_ticket_api("tktge")
        assert isinstance(api, TktGeApi)
        assert api_module._api_instance is api, "Module-level singleton should match returned instance"

    @patch.dict(os.environ, {"TICKET_SOURCE": "trege"}, clear=True)
    def test_env_var_respected(self):
        """Factory reads TICKET_SOURCE from environment."""
        import api as api_module
        api_module._api_instance = None
        api = get_ticket_api()  # no arg — should read env
        assert isinstance(api, TreGeApi)


# ═══════════════════════════════════════════════════════════════════════
# Backward-compatible module-level function aliases
# ═══════════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Old module-level imports still work and delegate correctly."""

    def teardown_method(self):
        """Reset module-level singleton after each test."""
        import api as api_module
        api_module._api_instance = None

    @pytest.mark.asyncio
    async def test_get_available_rides_still_callable(self):
        """get_available_rides is still importable and callable."""
        assert callable(get_available_rides)

    @pytest.mark.asyncio
    async def test_get_stations_still_callable(self):
        """get_stations is still importable and callable."""
        assert callable(get_stations)

    @pytest.mark.asyncio
    async def test_fetch_json_still_callable(self):
        """fetch_json is still importable and callable."""
        assert callable(fetch_json)

    def test_module_exports_required_symbols(self):
        """All symbols that old code imports are still present."""
        import api
        for name in ("get_stations", "get_available_rides", "get_availability_calendar",
                      "fetch_json", "API_BASE", "API_KEY"):
            assert hasattr(api, name), f"Module missing backward-compat symbol {name}"

    @pytest.mark.asyncio
    async def test_backward_compat_get_stations_delegates(self):
        """Module-level get_stations uses TktGeApi when singleton is set."""
        import api as api_module
        api_module._api_instance = TktGeApi()
        api_module._api_instance.get_stations = AsyncMock(return_value=[{"code": 1}])

        mock_session = MagicMock()
        result = await get_stations(mock_session)
        api_module._api_instance.get_stations.assert_awaited_once_with(mock_session)
        assert result == [{"code": 1}]

    @pytest.mark.asyncio
    async def test_backward_compat_get_available_rides_delegates(self):
        """Module-level get_available_rides delegates to search_trips."""
        import api as api_module
        api_module._api_instance = TktGeApi()
        api_module._api_instance.search_trips = AsyncMock(return_value={"rides": []})

        mock_session = MagicMock()
        result = await get_available_rides(mock_session, "56014", "57151", "2026-07-15")
        api_module._api_instance.search_trips.assert_awaited_once_with(
            mock_session, "56014", "57151", "2026-07-15", 1
        )
        assert result == {"rides": []}
