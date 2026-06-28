"""Tests for _api_base.py — TicketApi ABC and shared constants.

Verifies that TicketApi is abstract (cannot be instantiated directly),
that all abstract methods are defined, and that constants are correct.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _api_base import TicketApi, API_BASE, API_KEY


# ═══════════════════════ TicketApi ABC ═════════════════════════════════


class TestTicketApiABC:

    def test_cannot_instantiate_directly(self):
        """TicketApi is abstract and cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract"):
            TicketApi()

    def test_all_abstract_methods_defined(self):
        """Verify all expected abstract methods are present."""
        expected = {
            "get_stations", "search_trips", "get_availability_calendar",
            "get_seats", "get_prices",
        }
        actual = set(TicketApi.__abstractmethods__)
        assert actual == expected, f"Expected {expected}, got {actual}"

    def test_abstract_methods_have_correct_signatures(self):
        """Check that signatures are inspectable."""
        import inspect

        methods = ["get_stations", "search_trips", "get_availability_calendar", "get_seats", "get_prices"]
        for name in methods:
            meth = getattr(TicketApi, name)
            assert callable(meth)
            # All should have 'self' and 'session' as first two params
            sig = inspect.signature(meth)
            params = list(sig.parameters.keys())
            assert params[0] == "self"


class TestConcreteSubclassCanBeInstantiated:
    """A minimal concrete subclass should instantiate fine."""

    def test_minimal_subclass(self):
        class MinimalApi(TicketApi):
            async def get_stations(self, session):
                return []
            async def search_trips(self, session, from_code, to_code, date_str, passengers=1):
                return {}
            async def get_availability_calendar(self, session, from_code, to_code):
                return {}
            async def get_seats(self, session, ride_id, class_id=None):
                raise NotImplementedError()
            async def get_prices(self, session, ride_id, class_id=None):
                raise NotImplementedError()

        api = MinimalApi()
        assert isinstance(api, TicketApi)


# ═══════════════════════ API Constants ═════════════════════════════════


class TestApiConstants:

    def test_api_base_is_https(self):
        assert API_BASE.startswith("https://")

    def test_api_base_ends_with_georgian_railway(self):
        assert API_BASE.endswith("/GeorgianRailway")

    def test_api_key_is_uuid_format(self):
        assert len(API_KEY) == 36
        assert API_KEY.count("-") == 4

    def test_api_key_matches_between_modules(self):
        from api_tkt import API_KEY as TktKey
        from api import API_KEY as ApiKey
        assert API_KEY == TktKey == ApiKey

    def test_api_base_matches_between_modules(self):
        from api_tkt import API_BASE as TktBase
        from api import API_BASE as ApiBase
        assert API_BASE == TktBase == ApiBase
