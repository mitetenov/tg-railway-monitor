"""Shared utility functions used across the project."""


def format_time(iso_str: str) -> str:
    """Extract HH:MM from an ISO 8601 datetime string.

    Handles timezone offsets (``+04:00``, ``Z``), milliseconds, and
    missing times gracefully.
    """
    if not iso_str:
        return "??:??"
    try:
        if "T" in iso_str:
            time_part = iso_str.split("T")[1]
            for sep in ("+", "-", "Z"):
                if sep in time_part[2:]:
                    time_part = time_part.split(sep)[0]
            return time_part[:5]
        return iso_str
    except (IndexError, ValueError):
        return iso_str


def fmt_duration(dur: str) -> str:
    """Convert ``"05:12:00"`` to ``"5h 12m"``."""
    if not dur:
        return "??:??"
    parts = dur.split(":")
    if len(parts) >= 2:
        h = int(parts[0])
        m = int(parts[1])
        return f"{h}h {m:02d}m"
    return dur
