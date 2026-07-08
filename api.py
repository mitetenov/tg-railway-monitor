"""
Async API client for Georgian Railway ticket services (tre.ge).

Provides TicketApi abstract base class, TreGeApi implementation, and a
factory function (get_ticket_api()).

Backward-compatible aliases are maintained at module level so existing
code (poller.py, bot.py) continues to work unchanged.
"""
import os
from typing import Any, Optional

import aiohttp

from _api_base import API_BASE, API_KEY, TicketApi
from api_tre import TreGeApi

# ── Default API source name ──────────────────────────────────────────
DEFAULT_TICKET_SOURCE = "trege"


# ═══════════════════════ Factory ══════════════════════════════════════

_SOURCE_REGISTRY: dict[str, type[TicketApi]] = {
    "trege": TreGeApi,
}

# Module-level singleton — set by get_ticket_api() or by init_ticket_api()
_api_instance: Optional[TicketApi] = None


def get_ticket_api(source: Optional[str] = None) -> TicketApi:
    """Factory: return a TicketApi instance matching *source*.

    If *source* is None, the value is read from the ``TICKET_SOURCE``
    environment variable.  If that is also unset, the default
    ``"trege"`` is used.

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

    # Return cached singleton if type matches
    if _api_instance is not None and isinstance(_api_instance, cls):
        return _api_instance

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
# If _api_instance is None they fall back to a default TreGeApi()
# instance so that existing importers (poller.py, bot.py) continue to
# work without changes.


def _resolve_api() -> Any:
    """Return the cached singleton, or a default TreGeApi()."""
    if _api_instance is not None:
        return _api_instance
    # Lazy fallback — create a default TreGeApi but do NOT cache it
    # so that a subsequent get_ticket_api() call still becomes the
    # canonical singleton.
    return TreGeApi()


async def fetch_json(session: aiohttp.ClientSession, url: str, label: str = "") -> Optional[Any]:
    """Backward-compatible alias for TreGeApi.fetch_json()."""
    api = _resolve_api()
    if hasattr(api, "fetch_json"):
        return await api.fetch_json(session, url, label)
    raise NotImplementedError(
        f"fetch_json() is not supported by {type(api).__name__}"
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
