"""
Tre.ge API implementation for the Georgian Railway ticket system.

Provides TreGeApi, a concrete TicketApi subclass that combines the
public gateway.tkt.ge REST API (same backend used by tre.ge/tkt.ge)
with tre.ge-specific features:

  - Station name → URL slug mapping for tre.ge search URLs
  - Purchase URL generation: https://tre.ge/en/search?from={slug}&to={slug}&date={date}
  - Trip searching via the shared gateway API

Endpoint reference: see api-docs.md for the wider picture.
"""
import os
from typing import Any, Optional
import logging

import aiohttp

from _api_base import API_BASE, API_KEY, TicketApi
from stations import STATION_SLUGS, SLUG_TO_STATION, station_to_slug, slug_to_station

logger = logging.getLogger(__name__)


def build_purchase_url(from_code: str, to_code: str, date_str: str) -> str:
    """Build a tre.ge purchase/search URL.

    Args:
        from_code: Departure station code (e.g. ``"56014"``).
        to_code: Arrival station code (e.g. ``"57151"``).
        date_str: Travel date in ``YYYY-MM-DD`` format.

    Returns:
        A fully-qualified URL pointing to the tre.ge search results page:
        ``https://tre.ge/en/search?leavingPlace={from_code}&enteringPlace={to_code}&leaveDate={DD.MM.YYYY}&passengerCount=1&wcuCount=0&depVT=railway``
    """
    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = dt.strftime("%d.%m.%Y")
    return (
        f"https://tre.ge/en/search"
        f"?leavingPlace={from_code}"
        f"&enteringPlace={to_code}"
        f"&leaveDate={formatted_date}"
        f"&passengerCount=1&wcuCount=0&depVT=railway"
    )


# ═══════════════════════════════════════════════════════════════════════
# TreGeApi
# ═══════════════════════════════════════════════════════════════════════


class TreGeApi(TicketApi):
    """Concrete implementation for the tre.ge Georgian Railway API.

    Combines the shared gateway.tkt.ge REST backend (stations, rides,
    calendar) with tre.ge-specific features like station slug mapping
    and purchase URL generation.  Trip data comes from the same public
    endpoints used by both tre.ge and tkt.ge, so ``search_trips()``
    accepts the same numeric station codes as ``TktGeApi``.

    Three core REST endpoints are available:
      - Stations dictionary  (GET /Dictionaries/civil-stations)
      - Available rides      (GET /Availability/available-rides)
      - Availability calendar (GET /Availability/availability-calendar)

    Per-ride seat maps and standalone pricing are **not** available via
    the public API; ``get_seats()`` and ``get_prices()`` raise
    ``NotImplementedError``.

    Additional tre.ge-specific functionality:
      - ``build_purchase_url(from_code, to_code, date)`` — generate a
        tre.ge purchase URL from numeric station codes.
      - ``station_to_slug(name)`` / ``slug_to_station(slug)`` — convert
        between station names and tre.ge URL slugs.
    """

    # ── Tre.ge-specific: TICKET_SOURCE value ──────────────────────────
    SOURCE = "trege"

    def __init__(
        self,
        api_base: str = API_BASE,
        api_key: str = API_KEY,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    # ── Static helpers (station-slug mapping) ─────────────────────────

    @staticmethod
    def station_to_slug(name: str) -> str:
        """Convert a station name to the tre.ge URL slug.

        See :func:`station_to_slug` (module-level) for details.
        """
        return station_to_slug(name)

    @staticmethod
    def slug_to_station(slug: str) -> Optional[str]:
        """Convert a tre.ge URL slug back to a station name.

        See :func:`slug_to_station` (module-level) for details.
        """
        return slug_to_station(slug)

    @staticmethod
    def build_purchase_url(from_code: str, to_code: str, date_str: str) -> str:
        """Build a tre.ge purchase/search URL.

        See :func:`build_purchase_url` (module-level) for details.
        """
        return build_purchase_url(from_code, to_code, date_str)

    # ── Internal: HTTP helper ─────────────────────────────────────────

    async def fetch_json(
        self, session: aiohttp.ClientSession, url: str, label: str = ""
    ) -> Optional[Any]:
        """Fetch JSON from *url*.  Returns ``None`` on any error."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error("[tre] %s: HTTP %s", label, resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.error("[tre] %s: %s", label, e)
            return None

    # ── Internal: URL builders ────────────────────────────────────────

    def _build_stations_url(self) -> str:
        """Build the stations-dictionary URL."""
        return f"{self.api_base}/Dictionaries/civil-stations?api_key={self.api_key}"

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

    # ── Abstract method implementations ───────────────────────────────

    async def get_stations(self, session: aiohttp.ClientSession) -> Optional[list]:
        """Fetch the full list of railway stations."""
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
        """Search for available train rides on a given route and date.

        Uses the same gateway.tkt.ge REST endpoint as TktGeApi (the
        tre.ge and tkt.ge platforms share a common backend).

        Args:
            session: Active aiohttp session.
            from_code: Numeric departure station code (e.g. ``"56014"``
                for Tbilisi).  Use :meth:`station_to_slug` if you need
                the tre.ge URL slug instead.
            to_code: Numeric arrival station code.
            date_str: Date in YYYY-MM-DD format.
            passengers: Number of passengers (default 1).

        Returns:
            A dict with ``departureAvailableRides``, ``returningAvailableRides``
            keys, or None on failure.
        """
        url = self._build_rides_url(from_code, to_code, date_str, passengers)
        return await self.fetch_json(session, url, "rides")

    async def get_availability_calendar(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
    ) -> Optional[dict]:
        """Get daily ticket availability calendar (approx. 30-day window)."""
        url = self._build_calendar_url(from_code, to_code)
        return await self.fetch_json(session, url, "calendar")

    async def get_seats(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Seat-level details require an authenticated session on the web
        platform; no public REST endpoint exists."""
        raise NotImplementedError(
            "TreGeApi does not provide a per-ride seat map endpoint. "
            "Use search_trips() for per-class seat counts."
        )

    async def get_prices(
        self,
        session: aiohttp.ClientSession,
        ride_id: int,
        class_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Pricing is embedded in the ``search_trips()`` response — there
        is no dedicated pricing endpoint."""
        raise NotImplementedError(
            "TreGeApi does not provide a dedicated pricing endpoint. "
            "Use search_trips() for per-class pricing."
        )
