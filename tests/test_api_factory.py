"""Tests for api.py — factory functions, backward-compatible aliases, singleton."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api
from api import (
    get_ticket_api,
    init_ticket_api,
    get_stations,
    get_available_rides,
    get_availability_calendar,
    fetch_json,
    _SOURCE_REGISTRY,
    DEFAULT_TICKET_SOURCE,
)
from api_tre import TreGeApi
from _api_base import TicketApi


# ═══════════════════════ Factory: get_ticket_api ═══════════════════════


class TestGetTicketApi:
    def teardown_method(self):
        """Reset module-level singleton cache between tests."""
        api._api_instance = None

    def test_factory_returns_trege_by_default(self):
        inst = get_ticket_api()
        assert isinstance(inst, TreGeApi)

    def test_factory_returns_trege_for_trege_source(self):
        inst = get_ticket_api("trege")
        assert isinstance(inst, TreGeApi)

    def test_factory_uses_env_var(self):
        os.environ["TICKET_SOURCE"] = "trege"
        try:
            inst = get_ticket_api()
            assert isinstance(inst, TreGeApi)
        finally:
            del os.environ["TICKET_SOURCE"]

    def test_factory_unknown_source_raises(self):
        with pytest.raises(ValueError, match="Unknown TICKET_SOURCE"):
            get_ticket_api("nonexistent")

    def test_factory_unknown_source_tktge_raises(self):
        """tktge is no longer a registered source."""
        with pytest.raises(ValueError, match="Unknown TICKET_SOURCE"):
            get_ticket_api("tktge")

    def test_factory_caches_singleton(self):
        """get_ticket_api() returns the same instance on repeated calls."""
        inst1 = get_ticket_api()
        inst2 = get_ticket_api()
        assert inst1 is inst2

    def test_source_registry_keys(self):
        assert set(_SOURCE_REGISTRY.keys()) == {"trege"}


# ═══════════════════════ init_ticket_api ═══════════════════════════════


class TestInitTicketApi:
    def teardown_method(self):
        api._api_instance = None

    def test_init_returns_instance(self):
        inst = init_ticket_api()
        assert isinstance(inst, TicketApi)
        assert hasattr(inst, "get_stations")
        assert hasattr(inst, "search_trips")

    def test_init_accepts_source(self):
        inst = init_ticket_api("trege")
        assert isinstance(inst, TreGeApi)


# ═══════════════════════ _resolve_api fallback ═════════════════════════


class TestResolveApi:
    def teardown_method(self):
        api._api_instance = None

    def test_resolve_with_no_cache_returns_trege(self):
        resolved = api._resolve_api()
        assert isinstance(resolved, TreGeApi)

    def test_resolve_with_no_cache_does_not_cache(self):
        resolved = api._resolve_api()
        assert api._api_instance is None  # NOT cached

    def test_resolve_with_cache_returns_cached(self):
        cached = get_ticket_api()
        resolved = api._resolve_api()
        assert resolved is cached


# ═══════════════════════ Backward-Compatible Aliases ═══════════════════


class TestBackwardCompatAliases:
    def teardown_method(self):
        api._api_instance = None

    @pytest.mark.asyncio
    async def test_get_stations_alias(self):
        mock_session = MagicMock()
        expected = [{"code": "56014"}]
        inst = get_ticket_api()
        inst.get_stations = AsyncMock(return_value=expected)
        result = await get_stations(mock_session)
        assert result == expected
        inst.get_stations.assert_awaited_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_get_available_rides_alias(self):
        mock_session = MagicMock()
        expected = {"departureAvailableRides": []}
        inst = get_ticket_api()
        inst.search_trips = AsyncMock(return_value=expected)
        result = await get_available_rides(mock_session, "56014", "57151", "2026-07-15")
        assert result == expected
        inst.search_trips.assert_awaited_once_with(mock_session, "56014", "57151", "2026-07-15", 1)

    @pytest.mark.asyncio
    async def test_get_available_rides_alias_custom_passengers(self):
        mock_session = MagicMock()
        inst = get_ticket_api()
        inst.search_trips = AsyncMock(return_value={})
        await get_available_rides(mock_session, "56014", "57151", "2026-07-15", passengers=3)
        inst.search_trips.assert_awaited_once_with(mock_session, "56014", "57151", "2026-07-15", 3)

    @pytest.mark.asyncio
    async def test_get_availability_calendar_alias(self):
        mock_session = MagicMock()
        expected = {"toDestionation": []}
        inst = get_ticket_api()
        inst.get_availability_calendar = AsyncMock(return_value=expected)
        result = await get_availability_calendar(mock_session, "56014", "57151")
        assert result == expected
        inst.get_availability_calendar.assert_awaited_once_with(mock_session, "56014", "57151")

    @pytest.mark.asyncio
    async def test_fetch_json_alias_with_trege(self):
        mock_session = MagicMock()
        inst = get_ticket_api()
        assert isinstance(inst, TreGeApi)
        inst.fetch_json = AsyncMock(return_value={"ok": True})
        result = await fetch_json(mock_session, "http://example.com", "test")
        assert result == {"ok": True}
