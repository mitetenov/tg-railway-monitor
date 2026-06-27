"""
Async API client for Georgian Railway ticket services.
Provides an abstract base class (TicketApi), concrete implementations
(TktGeApi in api_tkt.py, TreGeApi in api_tre.py), and a factory function
(get_ticket_api()).

Backward-compatible aliases are maintained at module level so existing
code (poller.py, bot.py) continues to work unchanged.
"""
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp

from api_tkt import TktGeApi

# ── Module-level constants (backward-compatible) ──────────────────────
API_BASE = "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
API_KEY = "7d8d34d1-e9af-4897-9f0f-5c36c179be77"  # public key embedded in client-side JS

# ── Default API source name ──────────────────────────────────────────
DEFAULT_TICKET_SOURCE = "tktge"


# ═══════════════════════ Abstract Base Class ═══════════════════════════


class TicketApi(ABC):
    """Abstract base class for ticket API implementations.

    Every implementation must provide the core ticket-searching and
    station-lookup methods listed below.  Methods that have no
    corresponding endpoint on a particular provider should raise
    NotImplementedError with a descriptive message.
    """

    @abstractmethod
    async def get_stations(self, session: aiohttp.ClientSession) -> Optional[list]:
        """Fetch the full list of available stations.

        Returns a list of station dicts (keys vary by provider) or None
        on failure.
        """
        ...

    @abstractmethod
    async def search_trips(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
        date_str: str,
        passengers: int = 1,
    ) -> Optional[dict]:
        """Search for available trips on a given route and date.

        Args:
            session: Active aiohttp session.
            from_code: Station code for departure.
            to_code: Station code for arrival.
            date_str: Date in YYYY-MM-DD format.
            passengers: Number of passengers (default 1).

        Returns:
            A dict whose structure is provider-specific, or None on
            failure.  The response typically includes a list of rides
            with per-class seat counts and prices.
        """
        ...

    @abstractmethod
    async def get_availability_calendar(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
    ) -> Optional[dict]:
        """Get a multi-day availability calendar for a route.

        Returns a dict with date→availability mappings (or None on
        failure).  The exact shape is provider-specific.
        """
        ...

    @abstractmethod
    async def get_seats(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Get seat-level details for a specific ride.

        Args:
            session: Active aiohttp session.
            ride_id: Provider-specific ride identifier.
            class_id: Optional seat-class filter.

        Returns:
            Seat-map / availability dict, or None on failure.  Providers
            that do not offer per-ride seat maps should raise
            NotImplementedError.
        """
        ...

    @abstractmethod
    async def get_prices(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Get pricing details for a specific ride.

        Args:
            session: Active aiohttp session.
            ride_id: Provider-specific ride identifier.
            class_id: Optional seat-class filter.

        Returns:
            Pricing dict, or None on failure.  Providers that embed
            prices inside the search_trips response (rather than a
            dedicated endpoint) should raise NotImplementedError for
            standalone calls.
        """
        ...


# ══════════════════════ TreGeApi Import ══════════════════════════════════

from api_tre import TreGeApi  # noqa: E402 — separate module, after ABC def


# ═══════════════════════ Factory ══════════════════════════════════════

_SOURCE_REGISTRY: dict[str, type[TicketApi]] = {
    "tktge": TktGeApi,
    "trege": TreGeApi,
}

# Module-level singleton — set by get_ticket_api() or by init_ticket_api()
_api_instance: Optional[TicketApi] = None


def get_ticket_api(source: Optional[str] = None) -> TicketApi:
    """Factory: return a TicketApi instance matching *source*.

    If *source* is None, the value is read from the ``TICKET_SOURCE``
    environment variable.  If that is also unset, the default
    ``"tktge"`` is used.

    The first call to ``get_ticket_api()`` stores the result as a
    module-level singleton so that subsequent calls (including
    module-level function aliases) use the same instance.

    Raises ValueError on an unknown source name.
    """
    global _api_instance

    src = (source or os.environ.get("TICKET_SOURCE") or DEFAULT_TICKET_SOURCE).lower().strip()
    cls = _SOURCE_REGISTRY.get(src)
    if cls is None:
        raise ValueError(
            f"Unknown TICKET_SOURCE {src!r}. "
            f"Available: {', '.join(sorted(_SOURCE_REGISTRY))}"
        )

    # Create and cache the singleton
    _api_instance = cls()
    return _api_instance


def init_ticket_api(source: Optional[str] = None) -> TicketApi:
    """Explicitly initialise the module-level ticket API singleton.

    This is called during application startup (bot.post_init) to
    ensure the factory is connected.  Returns the created instance.
    """
    return get_ticket_api(source)


# ═══════════════════════ Backward-Compatible Aliases ══════════════════

# These module-level functions delegate to the cached _api_instance.
# If _api_instance is None they fall back to a default TktGeApi()
# instance so that existing importers (poller.py, bot.py) continue to
# work without changes.


def _resolve_api() -> TicketApi:
    """Return the cached singleton, or a default TktGeApi()."""
    if _api_instance is not None:
        return _api_instance
    # Lazy fallback — create a default TktGeApi but do NOT cache it
    # so that a subsequent get_ticket_api() call still becomes the
    # canonical singleton.
    return TktGeApi()


async def fetch_json(session: aiohttp.ClientSession, url: str, label: str = "") -> Optional[Any]:
    """Backward-compatible alias for TktGeApi.fetch_json()."""
    api = _resolve_api()
    if isinstance(api, TktGeApi):
        return await api.fetch_json(session, url, label)
    raise NotImplementedError(
        f"fetch_json() is only supported by TktGeApi, not {type(api).__name__}"
    )


async def get_stations(session: aiohttp.ClientSession) -> Optional[list]:
    """Backward-compatible alias delegating to the active API instance."""
    api = _resolve_api()
    return await api.get_stations(session)


async def get_available_rides(
    session: aiohttp.ClientSession,
    from_code: str,
    to_code: str,
    date_str: str,
    passengers: int = 1,
) -> Optional[dict]:
    """Backward-compatible alias for ``search_trips()``."""
    api = _resolve_api()
    return await api.search_trips(session, from_code, to_code, date_str, passengers)


async def get_availability_calendar(
    session: aiohttp.ClientSession,
    from_code: str,
    to_code: str,
) -> Optional[dict]:
    """Backward-compatible alias delegating to the active API instance."""
    api = _resolve_api()
    return await api.get_availability_calendar(session, from_code, to_code)
