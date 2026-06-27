"""
Shared base for Georgian Railway ticket API implementations.

Provides the TicketApi abstract base class and module-level constants
used by both TktGeApi and TreGeApi.  This module has zero imports from
the API implementation modules, so it is safe to import from anywhere.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp

# ── API constants (shared by all implementations) ─────────────────────
API_BASE = "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
API_KEY = "7d8d34d1-e9af-4897-9f0f-5c36c179be77"  # public key embedded in client-side JS


# ═══════════════════════════════════════════════════════════════════════
# TicketApi — Abstract Base Class
# ═══════════════════════════════════════════════════════════════════════


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
