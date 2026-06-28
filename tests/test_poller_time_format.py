"""Test that format_time() from utils returns HH:MM, not raw [:5] slicing."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import format_time


def test_poller_time_format_returns_hhmm():
    """Verify format_time returns HH:MM, not raw ISO prefix."""
    result = format_time("2026-06-27T00:30:00Z")
    assert result == "00:30", f"Expected '00:30', got {result!r}"

    result = format_time("2026-06-27T05:42:00+04:00")
    assert result == "05:42", f"Expected '05:42', got {result!r}"

    # Edge: missing time component
    result = format_time("")
    assert result == "??:??", f"Expected '??:??', got {result!r}"

    # Edge: rideStartDate missing from dict
    result = format_time("")
    assert result == "??:??"
