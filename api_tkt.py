"""
Concrete TicketApi implementation for tkt.ge (Georgian Railway).

This module contains the TktGeApi class that implements the TicketApi
abstract interface for the tkt.ge gateway API.

API base: https://gateway.tkt.ge/integrations/api/GeorgianRailway
See api-docs.md for full endpoint reference.
"""
from typing import Any, Optional
import logging

import aiohttp

from _api_base import TicketApi, API_BASE, API_KEY

logger = logging.getLogger(__name__)


class TktGeApi(TicketApi):
    """Concrete implementation for the tkt.ge Georgian Railway API.

    Three core endpoints are available:
      - Stations dictionary  (GET /Dictionaries/civil-stations)
      - Available rides      (GET /Availability/available-rides)
      - Availability calendar (GET /Availability/availability-calendar)

    Per-ride seat maps and standalone pricing are **not** available via
    the public API; ``get_seats()`` and ``get_prices()`` raise
    ``NotImplementedError``.
    """

    def __init__(
        self,
        api_base: str = API_BASE,
        api_key: str = API_KEY,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    # ── Internal helpers ──────────────────────────────────────────────

    async def fetch_json(
        self, session: aiohttp.ClientSession, url: str, label: str = ""
    ) -> Optional[Any]:
        """Fetch JSON from a URL.  Returns None on any error."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error("[api] %s: HTTP %s", label, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.error("[api] %s: %s", label, e)
            return None

    def _build_rides_url(
        self,
        from_code: str,
        to_code: str,
        date_str: str,
        passengers: int = 1,
    ) -> str:
        """Build the available-rides endpoint URL."""
        return (
            f"{self.api_base}/Availability/available-rides"
            f"?passengersNumbers={passengers}"
            f"&departureDateFrom={date_str}T00:00:00.000Z"
            f"&startStationCode={from_code}"
            f"&endStationCode={to_code}"
            f"&returnWay=false&disability=false"
            f"&api_key={self.api_key}"
        )

    def _build_calendar_url(self, from_code: str, to_code: str) -> str:
        """Build the availability-calendar URL."""
        return (
            f"{self.api_base}/Availability/availability-calendar"
            f"?fromStationCode={from_code}&toStationCode={to_code}"
            f"&api_key={self.api_key}"
        )

    def _build_stations_url(self) -> str:
        """Build the stations-dictionary URL."""
        return f"{self.api_base}/Dictionaries/civil-stations?api_key={self.api_key}"

    # ── Public API methods ────────────────────────────────────────────

    async def get_stations(self, session: aiohttp.ClientSession) -> Optional[list]:
        """Fetch list of railway stations from the dictionary endpoint."""
        url = self._build_stations_url()
        return await self.fetch_json(session, url, "stations")

    async def search_trips(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
        date_str: str,
        passengers: int = 1,
    ) -> Optional[dict]:
        """Get available train rides for a specific route/date.

        This is the primary endpoint used by the ticket monitor.
        """
        url = self._build_rides_url(from_code, to_code, date_str, passengers)
        return await self.fetch_json(session, url, "rides")

    async def get_availability_calendar(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
    ) -> Optional[dict]:
        """Get daily ticket availability calendar (30-day window)."""
        url = self._build_calendar_url(from_code, to_code)
        return await self.fetch_json(session, url, "calendar")

    async def get_seats(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Seat-level details are not available via a dedicated tkt.ge
        endpoint.  Use search_trips() which includes per-class seat
        counts."""
        raise NotImplementedError(
            "TktGeApi does not provide a per-ride seat map endpoint. "
            "Use search_trips() for per-class seat counts."
        )

    async def get_prices(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Pricing is embedded in the search_trips() response."""
        raise NotImplementedError(
            "TktGeApi does not provide a dedicated pricing endpoint. "
            "Use search_trips() for per-class pricing."
        )
