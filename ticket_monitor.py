#!/usr/bin/env python3
"""
Georgian Railway Ticket Monitor

Polling + state diff + Telegram message formatting.
Zero external dependencies — uses only Python stdlib.

Usage:
    from ticket_monitor import TicketMonitor

    monitor = TicketMonitor(config={...})
    monitor.start()            # background thread, polls every 60s
    monitor.stop()             # graceful shutdown

    # Or do a single poll:
    changes = monitor.poll_once()
    for c in changes:
        print(c["telegram_text"])
"""

import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from stations import STATION_NAMES
from _api_base import API_BASE, API_KEY
from utils import format_time, fmt_duration

DEFAULT_API_KEY = API_KEY
DEFAULT_POLL_INTERVAL = 60  # seconds
DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), "monitor_state.json")

CLASS_NAMES = {1: "I Class", 2: "II Class", 5: "Business"}
CLASS_EMOJI = {1: "💺", 2: "🪑", 5: "⭐"}

log = logging.getLogger("ticket_monitor")


# ─── Data types ──────────────────────────────────────────────────────────────

@dataclass
class RouteConfig:
    """One route to monitor."""
    from_station_code: str       # e.g. "56014"
    to_station_code: str         # e.g. "57151"
    from_station_name: str = ""  # human-friendly, auto-filled if empty
    to_station_name: str = ""
    date: str = ""               # YYYY-MM-DD, defaults to tomorrow
    class_filter: Optional[int] = None  # seatClassId filter (1, 2, 5), None=all
    passengers: int = 1

    def __post_init__(self):
        if not self.from_station_name:
            self.from_station_name = STATION_NAMES.get(self.from_station_code, self.from_station_code)
        if not self.to_station_name:
            self.to_station_name = STATION_NAMES.get(self.to_station_code, self.to_station_code)
        if not self.date:
            self.date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


@dataclass
class TicketState:
    """
    Serializable snapshot of known ticket availability.
    Structure:
        {route_key: {ride_number: {class_id: {"seats": N, "price": M}}}}
    """
    routes: dict = field(default_factory=dict)  # route_key -> ride_data
    last_updated: str = ""


# ─── Monitor class ───────────────────────────────────────────────────────────

class TicketMonitor:
    """
    Polls tkt.ge API for configured routes, diffs against last known state,
    and yields change events.

    Parameters
    ----------
    config : dict or str
        Either a dict with keys listed below, or a path to a JSON config file.
    state_file : str or None
        Path to persist last-known state. None = in-memory only (no persistence).
    api_key : str or None
        API key override. Defaults to the public tkt.ge key.
    poll_interval : int
        Seconds between polls (default 60).
    routes : list[dict]
        List of route config dicts. Each dict maps to RouteConfig fields.

    Config file schema (JSON):
    {
        "api_key": "...",
        "poll_interval": 60,
        "state_file": "/path/to/state.json",
        "routes": [
            {
                "from_station_code": "56014",
                "to_station_code": "57151",
                "from_station_name": "Tbilisi",
                "to_station_name": "Batumi",
                "date": "2026-06-27",
                "passengers": 1
            }
        ]
    }
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        state_file: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval: Optional[int] = None,
        routes: Optional[list] = None,
    ):
        self._parse_init_args(config, state_file, api_key, poll_interval, routes)

        self._state = TicketState()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_change_callbacks = []

        self._load_state()

    def _parse_init_args(self, config, state_file, api_key, poll_interval, routes):
        """Merge constructor args with optional config dict/file."""
        cfg = {}
        if config is not None:
            if isinstance(config, str):
                try:
                    with open(config, "r") as f:
                        cfg = json.load(f)
                except (json.JSONDecodeError, IOError, OSError) as e:
                    raise ValueError(
                        f"Failed to parse config file {config}: {e}"
                    ) from e
            else:
                cfg = config

        self.api_key = api_key or cfg.get("api_key") or DEFAULT_API_KEY
        self.poll_interval = int(
            poll_interval or cfg.get("poll_interval") or DEFAULT_POLL_INTERVAL
        )
        self.state_file = state_file or cfg.get("state_file") or DEFAULT_STATE_FILE

        raw_routes = routes or cfg.get("routes", [])
        self.routes = []
        for r in raw_routes:
            if isinstance(r, RouteConfig):
                self.routes.append(r)
            else:
                self.routes.append(RouteConfig(**r))

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        """Start background polling in a daemon thread."""
        if self._thread and self._thread.is_alive():
            log.warning("Monitor already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TicketMonitor")
        self._thread.start()
        log.info("Monitor started (interval=%ds, routes=%d)", self.poll_interval, len(self.routes))

    def stop(self, timeout: float = 5.0):
        """Signal the polling thread to stop and wait up to `timeout` seconds."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.warning("Monitor thread did not stop within %ds", timeout)
        log.info("Monitor stopped")

    def poll_once(self) -> list[dict]:
        """
        Execute one poll cycle: fetch rides for all routes, diff against state,
        return a list of change events.

        Each change event dict:
        {
            "type": "new_ticket" | "seats_increased",
            "route": RouteConfig,
            "ride_number": int,
            "seat_class_id": int,
            "seat_class_name": str,
            "seats": int,
            "price": float,
            "departure": str,       # "00:30"
            "arrival": str,         # "05:42"
            "duration": str,        # "05:12"
            "from_name": str,
            "to_name": str,
            "telegram_text": str    # pre-formatted Telegram message
        }
        """
        changes = []
        if not self.routes:
            log.warning("No routes configured; nothing to poll")
            return changes

        for route in self.routes:
            route_changes = self._poll_route(route)
            changes.extend(route_changes)

        if changes:
            self._save_state()
            for cb in self._on_change_callbacks:
                try:
                    cb(changes)
                except Exception as e:
                    log.error("Change callback error: %s", e)

        return changes

    def on_change(self, callback):
        """
        Register a callback invoked on each poll that detects changes.
        Callback receives a list of change-event dicts.
        """
        self._on_change_callbacks.append(callback)

    # ── Internal: polling ───────────────────────────────────────────────────

    def _poll_loop(self):
        """Background loop — calls poll_once() every poll_interval seconds."""
        while not self._stop_event.is_set():
            try:
                changes = self.poll_once()
                for c in changes:
                    log.info("CHANGE: %s", c["telegram_text"])
            except Exception as e:
                log.error("Poll error: %s", e)
            self._stop_event.wait(self.poll_interval)

    def _poll_route(self, route: RouteConfig) -> list[dict]:
        """Fetch and diff a single route."""
        rides_data = self._fetch_rides(route)
        if rides_data is None:
            return []

        rides = rides_data.get("departureAvailableRides", [])
        route_key = self._route_key(route)
        changes = []

        with self._lock:
            prev_rides = self._state.routes.get(route_key, {})
            current_rides = {}

            for ride in rides:
                ride_num = ride.get("rideNumber")
                if ride_num is None:
                    continue

                departure = format_time(ride.get("rideStartDate", ""))
                arrival = format_time(ride.get("rideEndDate", ""))
                duration = fmt_duration(ride.get("rideDuration", ""))
                from_name = route.from_station_name
                to_name = route.to_station_name

                current_rides[str(ride_num)] = {}

                for cls in ride.get("availableSeatsClasses", []):
                    cls_id = cls.get("seatClassId")
                    seats = cls.get("availableNumberOfSeats") or 0
                    price = cls.get("moneyAmount", 0)

                    # Apply class filter
                    if route.class_filter is not None and cls_id != route.class_filter:
                        continue

                    current_rides[str(ride_num)][str(cls_id)] = {
                        "seats": seats,
                        "price": price,
                    }

                    # Compare with previous state
                    prev_cls = prev_rides.get(str(ride_num), {}).get(str(cls_id))
                    prev_seats = (prev_cls.get("seats") or 0) if prev_cls else 0

                    if prev_cls is None:
                        # Brand new ticket availability
                        change_type = "new_ticket"
                    elif seats > prev_seats:
                        change_type = "seats_increased"
                    else:
                        continue  # no meaningful change

                    cls_name = CLASS_NAMES.get(cls_id, f"Class {cls_id}")
                    cls_emoji = CLASS_EMOJI.get(cls_id, "🎫")

                    telegram_text = self._format_telegram(
                        ride_num=ride_num,
                        from_name=from_name,
                        to_name=to_name,
                        departure=departure,
                        arrival=arrival,
                        duration=duration,
                        cls_name=cls_name,
                        cls_emoji=cls_emoji,
                        seats=seats,
                        price=price,
                        change_type=change_type,
                    )

                    changes.append({
                        "type": change_type,
                        "route": route,
                        "ride_number": ride_num,
                        "seat_class_id": cls_id,
                        "seat_class_name": cls_name,
                        "seats": seats,
                        "price": price,
                        "departure": departure,
                        "arrival": arrival,
                        "duration": duration,
                        "from_name": from_name,
                        "to_name": to_name,
                        "telegram_text": telegram_text,
                    })

            # Update state for this route
            self._state.routes[route_key] = current_rides
            self._state.last_updated = datetime.now(timezone.utc).isoformat()

        return changes

    def _format_telegram(
        self,
        ride_num,
        from_name,
        to_name,
        departure,
        arrival,
        duration,
        cls_name,
        cls_emoji,
        seats,
        price,
        change_type,
    ) -> str:
        """Build a Telegram-friendly message for this change."""
        if change_type == "new_ticket":
            header = f"🚄 *New ticket available!*"
        else:
            header = f"📈 *Seats increased!*"

        return (
            f"{header}\n"
            f"{from_name} → {to_name} — Train *#{ride_num}*\n"
            f"🕐 {departure} → {arrival} ({duration})\n"
            f"{cls_emoji} *{cls_name}*: {price} GEL — {seats} seat{'s' if seats != 1 else ''}"
        )

    # ── Internal: API calls ──────────────────────────────────────────────────

    def _fetch_rides(self, route: RouteConfig) -> Optional[dict]:
        """
        Call the available-rides endpoint.
        Returns parsed JSON dict, or None on failure.
        Uses urllib — zero dependencies.
        """
        date_from = f"{route.date}T00:00:00.000Z"
        url = (
            f"{API_BASE}/Availability/available-rides"
            f"?passengersNumbers={route.passengers}"
            f"&departureDateFrom={urllib.request.quote(date_from)}"
            f"&startStationCode={route.from_station_code}"
            f"&endStationCode={route.to_station_code}"
            f"&returnWay=false"
            f"&disability=false"
            f"&api_key={self.api_key}"
        )

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            log.error("HTTP %s fetching rides for %s→%s: %s",
                       e.code, route.from_station_code, route.to_station_code, body)
        except urllib.error.URLError as e:
            log.error("URL error fetching rides for %s→%s: %s",
                       route.from_station_code, route.to_station_code, e.reason)
        except json.JSONDecodeError as e:
            log.error("JSON decode error for %s→%s: %s",
                       route.from_station_code, route.to_station_code, e)
        except OSError as e:
            log.error("OS error fetching rides for %s→%s: %s",
                       route.from_station_code, route.to_station_code, e)
        except Exception as e:
            log.error("Unexpected error fetching rides for %s→%s: %s",
                       route.from_station_code, route.to_station_code, e)
        return None

    # ── Internal: state persistence ──────────────────────────────────────────

    def _route_key(self, route: RouteConfig) -> str:
        """Unique key for a route config."""
        return f"{route.from_station_code}→{route.to_station_code}"

    def _load_state(self):
        """Load persisted state from JSON file."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            self._state = TicketState(
                routes=data.get("routes", {}),
                last_updated=data.get("last_updated", ""),
            )
            log.info("Loaded state from %s (%d routes)", self.state_file, len(self._state.routes))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not load state from %s: %s", self.state_file, e)

    def _save_state(self):
        """Persist current state to JSON file."""
        if not self.state_file:
            return
        try:
            data = {"routes": self._state.routes, "last_updated": self._state.last_updated}
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
            log.debug("Saved state to %s", self.state_file)
        except OSError as e:
            log.error("Could not save state: %s", e)


# ─── Convenience helper ──────────────────────────────────────────────────────

def create_default_config(path: str = "config.json"):
    """
    Write a skeleton config.json to the given path.
    Returns the config dict.
    """
    cfg = {
        "api_key": DEFAULT_API_KEY,
        "poll_interval": 60,
        "state_file": "monitor_state.json",
        "routes": [
            {
                "from_station_code": "56014",
                "to_station_code": "57151",
                "from_station_name": "Tbilisi",
                "to_station_name": "Batumi",
                "date": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"),
                "passengers": 1,
            },
            {
                "from_station_code": "57151",
                "to_station_code": "56014",
                "from_station_name": "Batumi",
                "to_station_name": "Tbilisi",
                "date": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"),
                "passengers": 1,
            },
        ],
    }
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    log.info("Default config written to %s", path)
    return cfg


# ─── CLI entry point ─────────────────────────────────────────────────────────

def main():
    """CLI entry: runs one poll cycle and prints changes."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Locate config
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    if not os.path.exists(config_path):
        print(f"Config not found at {config_path}; creating default...")
        create_default_config(config_path)

    monitor = TicketMonitor(config=config_path)
    changes = monitor.poll_once()

    if changes:
        print(f"\n{'='*50}")
        print(f"Detected {len(changes)} change(s):\n")
        for c in changes:
            print(c["telegram_text"])
            print("-" * 40)
    else:
        print("No changes detected.")

    print(f"\nState file: {monitor.state_file}")
    print(f"Routes: {len(monitor.routes)}")
    print("Done.")


if __name__ == "__main__":
    main()
