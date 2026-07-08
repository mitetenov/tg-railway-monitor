"""Tests for api_tre.py — TreGeApi class and helpers."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════
# Module-level imports
# ═══════════════════════════════════════════════════════════════════════

from api_tre import (
    TreGeApi,
    station_to_slug,
    slug_to_station,
    build_purchase_url,
    STATION_SLUGS,
    SLUG_TO_STATION,
)
from _api_base import TicketApi, API_BASE, API_KEY


# ═══════════════════════════════════════════════════════════════════════
# Station slug mapping
# ═══════════════════════════════════════════════════════════════════════


class TestStationSlugMapping:
    """Verify station → slug and slug → station conversions."""

    def test_all_stations_have_slugs(self):
        """Every station in STATION_SLUGS has a reverse entry."""
        for name, slug in STATION_SLUGS.items():
            assert station_to_slug(name) == slug, f"Missing forward mapping for {name}"
            assert slug_to_station(slug) == name, f"Missing reverse mapping for {slug}"

    def test_slug_to_station_unknown_returns_none(self):
        """slug_to_station returns None for unknown slugs."""
        assert slug_to_station("UnknownCity") is None
        assert slug_to_station("") is None

    def test_case_insensitive_lookup(self):
        """station_to_slug works with different casing."""
        assert station_to_slug("tbilisi") == "Tbilisi"
        assert station_to_slug("TBILISI") == "Tbilisi"
        assert station_to_slug("kutaisi airport") == "Kutaisi%20Airport"

    def test_unknown_station_fallback_no_spaces(self):
        """station_to_slug URL-encodes unknown station names."""
        result = station_to_slug("Unknown Station Name")
        assert "%20" in result  # spaces should be encoded
        assert "Unknown" in result

    def test_slug_count_matches(self):
        """STATION_SLUGS and SLUG_TO_STATION have same count."""
        assert len(STATION_SLUGS) == len(SLUG_TO_STATION)

    def test_key_stations(self):
        """Verify key stations from the task spec."""
        # Common Georgian cities
        assert station_to_slug("Tbilisi") == "Tbilisi"
        assert station_to_slug("Batumi") == "Batumi"
        assert station_to_slug("Kutaisi") == "Kutaisi"
        assert station_to_slug("Zugdidi") == "Zugdidi"
        assert station_to_slug("Kobuleti") == "Kobuleti"
        assert station_to_slug("Poti") == "Poti"


# ═══════════════════════════════════════════════════════════════════════
# Purchase URL building
# ═══════════════════════════════════════════════════════════════════════


class TestPurchaseURL:
    """Verify purchase URL generation."""

    def test_basic_url(self):
        """Basic Tbilisi → Batumi URL with station codes."""
        url = build_purchase_url("56014", "57151", "2026-06-29")
        assert url == (
            "https://tre.ge/en/search"
            "?leavingPlace=56014"
            "&enteringPlace=57151"
            "&leaveDate=29.06.2026"
            "&passengerCount=1&wcuCount=0&depVT=railway"
        )

    def test_url_with_codes(self):
        """URL with different station codes."""
        url = build_purchase_url("56014", "57413", "2026-07-15")
        assert "leavingPlace=56014" in url
        assert "enteringPlace=57413" in url
        assert "leaveDate=15.07.2026" in url
        assert "passengerCount=1" in url
        assert "wcuCount=0" in url
        assert "depVT=railway" in url

    def test_url_static_method(self):
        """TreGeApi.build_purchase_url static method works."""
        url = TreGeApi.build_purchase_url("57151", "56014", "2026-08-01")
        assert url.startswith("https://tre.ge/en/search")
        assert "leavingPlace=57151" in url
        assert "enteringPlace=56014" in url
        assert "leaveDate=01.08.2026" in url
        assert "passengerCount=1" in url

    def test_date_conversion(self):
        """Date is correctly converted from YYYY-MM-DD to DD.MM.YYYY."""
        url = build_purchase_url("56014", "57151", "2026-12-25")
        assert "leaveDate=25.12.2026" in url

    def test_edge_dates(self):
        """Edge cases for date conversion."""
        # Single-digit day and month
        url = build_purchase_url("56014", "57151", "2026-01-05")
        assert "leaveDate=05.01.2026" in url
        # End of year
        url = build_purchase_url("56014", "57151", "2026-12-31")
        assert "leaveDate=31.12.2026" in url


# ═══════════════════════════════════════════════════════════════════════
# TreGeApi class — instantiation and properties
# ═══════════════════════════════════════════════════════════════════════


class TestTreGeApiInit:
    """Verify TreGeApi can be instantiated and has correct attributes."""

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

    def test_ticket_api_subclass(self):
        """TreGeApi is a proper TicketApi subclass."""
        assert issubclass(TreGeApi, TicketApi)
        assert isinstance(self.api, TicketApi)

    def test_api_base_trailing_slash_stripped(self):
        """Trailing slash is stripped from api_base."""
        api = TreGeApi(api_base="https://example.com/api/")
        assert api.api_base == "https://example.com/api"

    def test_api_base_no_trailing_slash_unchanged(self):
        """api_base without trailing slash is unchanged."""
        api = TreGeApi(api_base="https://example.com/api")
        assert api.api_base == "https://example.com/api"

    def test_source_attribute(self):
        """TreGeApi has the correct SOURCE attribute."""
        assert TreGeApi.SOURCE == "trege"


# ═══════════════════════════════════════════════════════════════════════
# URL builders
# ═══════════════════════════════════════════════════════════════════════


class TestTreGeApiUrlBuilders:
    """Verify internal URL builders."""

    def setup_method(self):
        self.api = TreGeApi()

    def test_build_stations_url(self):
        """Stations URL includes the API key."""
        url = self.api._build_stations_url()
        assert "/Dictionaries/civil-stations" in url
        assert "api_key=" in url

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
        assert "api_key=" in url

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
        assert "api_key=" in url


# ═══════════════════════════════════════════════════════════════════════
# Async methods (mocked)
# ═══════════════════════════════════════════════════════════════════════


class TestTreGeApiAsyncMethods:
    """Verify async methods delegate correctly to fetch_json."""

    def setup_method(self):
        self.api = TreGeApi()

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
        """get_seats raises NotImplementedError."""
        mock_session = MagicMock()
        with pytest.raises(NotImplementedError, match="does not provide a per-ride seat map"):
            await self.api.get_seats(mock_session, 123)

    @pytest.mark.asyncio
    async def test_get_prices_raises_not_implemented(self):
        """get_prices raises NotImplementedError."""
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


# ═══════════════════════════════════════════════════════════════════════
# Cross-module consistency
# ═══════════════════════════════════════════════════════════════════════


class TestTreGeApiCrossModule:
    """Verify TreGeApi from api_tre matches api.py re-export."""

    def test_tregeapi_from_api_is_same_class(self):
        """TreGeApi imported from api.py is the same class as from api_tre."""
        from api import TreGeApi as ApiTreGeApi
        assert ApiTreGeApi is TreGeApi

    def test_tregeapi_instance_compatible_with_factory(self):
        """TreGeApi instance from api_tre works with api.py's factory."""
        from api import get_ticket_api, _SOURCE_REGISTRY

        api = get_ticket_api("trege")
        assert isinstance(api, TreGeApi)
        assert callable(api.get_stations)
        assert callable(api.search_trips)
        assert callable(api.get_availability_calendar)
        assert callable(api.get_seats)
        assert callable(api.get_prices)

    def test_source_registry_has_trege(self):
        """_SOURCE_REGISTRY in api.py contains TreGeApi."""
        from api import _SOURCE_REGISTRY
        assert "trege" in _SOURCE_REGISTRY
        assert _SOURCE_REGISTRY["trege"] is TreGeApi

    def test_trege_api_has_static_methods(self):
        """TreGeApi exposes the required static/class-level helpers."""
        assert hasattr(TreGeApi, "station_to_slug")
        assert hasattr(TreGeApi, "slug_to_station")
        assert hasattr(TreGeApi, "build_purchase_url")
        assert callable(TreGeApi.station_to_slug)
        assert callable(TreGeApi.slug_to_station)
        assert callable(TreGeApi.build_purchase_url)

    def test_api_constants_match(self):
        """API_BASE and API_KEY are consistent across modules."""
        from api import API_BASE as ApiBase, API_KEY as ApiKey
        from _api_base import API_BASE as BaseBase, API_KEY as BaseKey
        assert API_BASE == ApiBase == BaseBase
