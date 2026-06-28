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
from datetime import datetime
from typing import Any, Optional

import aiohttp

from _api_base import API_BASE, API_KEY, TicketApi

# ═══════════════════════════════════════════════════════════════════════
# Station → Slug mapping for tre.ge
# ═══════════════════════════════════════════════════════════════════════

# Maps common Georgian city names to the Latin slugs used in tre.ge URLs.
# Slugs must match what tre.ge expects in the ?from= and ?to= query params.
# tre.ge uses simple English city names — no URL encoding of special chars.
STATION_SLUGS: dict[str, str] = {
    "Tbilisi": "Tbilisi",
    "Batumi": "Batumi",
    "Kutaisi": "Kutaisi",
    "Kutaisi Airport": "Kutaisi%20Airport",
    "Zugdidi": "Zugdidi",
    "Kobuleti": "Kobuleti",
    "Ozurgeti": "Ozurgeti",
    "Senaki": "Senaki",
    "Samtredia": "Samtredia",
    "Ureki": "Ureki",
    "Poti": "Poti",
    "Gori": "Gori",
    "Khashuri": "Khashuri",
    "Zestafoni": "Zestafoni",
    "Rioni": "Rioni",
    "Nigoiti": "Nigoiti",
    "Mtskheta": "Mtskheta",
    "Kaspi": "Kaspi",
    "Borjomi": "Borjomi",
    "Akhaltsikhe": "Akhaltsikhe",
}

# Reverse mapping: slug → canonical station name
SLUG_TO_STATION: dict[str, str] = {v: k for k, v in STATION_SLUGS.items()}


def station_to_slug(name: str) -> str:
    """Convert a station name to the tre.ge URL slug.

    Accepts both exact names (e.g. ``"Tbilisi"``) and known variants.
    Falls back to URL-encoding the input if no mapping is found.

    Examples:
        >>> station_to_slug("Tbilisi")
        'Tbilisi'
        >>> station_to_slug("Kutaisi Airport")
        'Kutaisi%20Airport'
    """
    # Direct lookup
    slug = STATION_SLUGS.get(name)
    if slug is not None:
        return slug

    # Try case-insensitive lookup
    lower = name.lower().strip()
    for station_name, station_slug in STATION_SLUGS.items():
        if station_name.lower() == lower:
            return station_slug

    # Fallback: URL-encode the input for use as a slug
    import urllib.parse
    return urllib.parse.quote(name, safe="")


def slug_to_station(slug: str) -> Optional[str]:
    """Convert a tre.ge URL slug back to a canonical station name.

    Returns None if the slug is unknown.
    """
    return SLUG_TO_STATION.get(slug)


def build_purchase_url(from_slug: str, to_slug: str, date_str: str) -> str:
    """Build a tre.ge purchase/search URL.

    Args:
        from_slug: Departure station slug (e.g. ``"Tbilisi"``).
        to_slug: Arrival station slug (e.g. ``"Batumi"``).
        date_str: Travel date in ``YYYY-MM-DD`` format.

    Returns:
        A fully-qualified URL pointing to the tre.ge search results page:
        ``https://tre.ge/en/search?from={from_slug}&to={to_slug}&date={date}``
        where *date* is formatted as ``DD.MM.YYYY``.
    """
    # tre.ge expects the date in DD.MM.YYYY format
    formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    return f"https://tre.ge/en/search?from={from_slug}&to={to_slug}&date={formatted_date}"


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
      - ``build_purchase_url(from_slug, to_slug, date)`` — generate a
        tre.ge purchase URL from city-name slugs.
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
    def build_purchase_url(from_slug: str, to_slug: str, date_str: str) -> str:
        """Build a tre.ge purchase/search URL.

        See :func:`build_purchase_url` (module-level) for details.
        """
        return build_purchase_url(from_slug, to_slug, date_str)

    # ── Internal: HTTP helper ─────────────────────────────────────────

    async def fetch_json(
        self, session: aiohttp.ClientSession, url: str, label: str = ""
    ) -> Optional[Any]:
        """Fetch JSON from *url*.  Returns ``None`` on any error."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    print(f"[tre] {label}: HTTP {resp.status}")
                    return None
                return await resp.json()
        except Exception as e:
            print(f"[tre] {label}: {e}")
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
