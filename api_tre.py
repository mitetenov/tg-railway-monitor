"""
Tre.ge API implementation for the Georgian Railway ticket system.

Provides TreGeApi, a concrete TicketApi subclass that talks to the same
gateway.tkt.ge REST endpoints used by the tre.ge / tkt.ge web platform.

Endpoint reference: see api_tre_notes.md (or api-docs.md for the wider picture).
"""
from typing import Any, Optional

import aiohttp

from api import API_BASE, API_KEY, TicketApi

# ── Internal helpers ──────────────────────────────────────────────────


def _build_stations_url(api_base: str, api_key: str) -> str:
    """Build the stations-dictionary URL."""
    return f"{api_base}/Dictionaries/civil-stations?api_key={api_key}"


def _build_rides_url(
    api_base: str,
    api_key: str,
    from_code: str,
    to_code: str,
    date_str: str,
    passengers: int = 1,
) -> str:
    """Build the available-rides endpoint URL."""
    return (
        f"{api_base}/Availability/available-rides"
        f"?passengersNumbers={passengers}"
        f"&departureDateFrom={date_str}T00:00:00.000Z"
        f"&startStationCode={from_code}"
        f"&endStationCode={to_code}"
        f"&returnWay=false&disability=false"
        f"&api_key={api_key}"
    )


def _build_calendar_url(api_base: str, api_key: str, from_code: str, to_code: str) -> str:
    """Build the availability-calendar URL."""
    return (
        f"{api_base}/Availability/availability-calendar"
        f"?fromStationCode={from_code}&toStationCode={to_code}"
        f"&api_key={api_key}"
    )


# ═══════════════════════════════════════════════════════════════════════
# TreGeApi
# ═══════════════════════════════════════════════════════════════════════


class TreGeApi(TicketApi):
    """Concrete implementation for the tre.ge (tkt.ge) Georgian Railway API.

    Uses the same gateway.tkt.ge infrastructure as TktGeApi, but may
    diverge in the future if tre.ge exposes different endpoints or
    requires alternative authentication.

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

    # ── Abstract method implementations ───────────────────────────────

    async def get_stations(self, session: aiohttp.ClientSession) -> Optional[list]:
        """Fetch the full list of railway stations."""
        url = _build_stations_url(self.api_base, self.api_key)
        return await self.fetch_json(session, url, "stations")

    async def search_trips(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
        date_str: str,
        passengers: int = 1,
    ) -> Optional[dict]:
        """Search for available train rides on a given route and date."""
        url = _build_rides_url(self.api_base, self.api_key, from_code, to_code, date_str, passengers)
        return await self.fetch_json(session, url, "rides")

    async def get_availability_calendar(
        self,
        session: aiohttp.ClientSession,
        from_code: str,
        to_code: str,
    ) -> Optional[dict]:
        """Get daily ticket availability calendar (approx. 30-day window)."""
        url = _build_calendar_url(self.api_base, self.api_key, from_code, to_code)
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
