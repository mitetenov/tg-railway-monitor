"""
Async API client for tkt.ge Georgian Railway.
Wraps the public endpoints in non-blocking aiohttp calls.
"""
import aiohttp
from typing import Any, Optional

API_BASE = "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
API_KEY = "7d8d34d1-e9af-4897-9f0f-5c36c179be77"  # public key embedded in client-side JS


async def fetch_json(session: aiohttp.ClientSession, url: str, label: str = "") -> Optional[Any]:
    """Fetch JSON from a URL. Returns None on any error."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"[api] {label}: HTTP {resp.status}")
                return None
            return await resp.json()
    except Exception as e:
        print(f"[api] {label}: {e}")
        return None


async def get_stations(session: aiohttp.ClientSession) -> Optional[list]:
    """Fetch list of railway stations from the dictionary endpoint."""
    url = f"{API_BASE}/Dictionaries/civil-stations?api_key={API_KEY}"
    return await fetch_json(session, url, "stations")


async def get_available_rides(
    session: aiohttp.ClientSession,
    from_code: str,
    to_code: str,
    date_str: str,
    passengers: int = 1,
) -> Optional[dict]:
    """Get actual train rides for a specific route/date.

    Args:
        from_code: Station code for departure.
        to_code: Station code for arrival.
        date_str: Date in YYYY-MM-DD format.
        passengers: Number of passengers (default 1).
    """
    url = (
        f"{API_BASE}/Availability/available-rides"
        f"?passengersNumbers={passengers}"
        f"&departureDateFrom={date_str}T00:00:00.000Z"
        f"&startStationCode={from_code}"
        f"&endStationCode={to_code}"
        f"&returnWay=false&disability=false"
        f"&api_key={API_KEY}"
    )
    return await fetch_json(session, url, "rides")


async def get_availability_calendar(
    session: aiohttp.ClientSession,
    from_code: str,
    to_code: str,
) -> Optional[dict]:
    """Get daily ticket availability calendar (30-day window)."""
    url = (
        f"{API_BASE}/Availability/availability-calendar"
        f"?fromStationCode={from_code}&toStationCode={to_code}&api_key={API_KEY}"
    )
    return await fetch_json(session, url, "calendar")
