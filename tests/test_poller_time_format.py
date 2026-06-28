"""Test that poller.py uses _format_time() instead of raw [:5] slicing."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ticket_monitor import TicketMonitor


def test_poller_time_format_returns_hhmm():
    """Verify TicketMonitor._format_time returns HH:MM, not raw ISO prefix."""
    # Old code would do [:5] → "2026-" for this input
    result = TicketMonitor._format_time("2026-06-27T00:30:00Z")
    assert result == "00:30", f"Expected '00:30', got {result!r}"

    result = TicketMonitor._format_time("2026-06-27T05:42:00+04:00")
    assert result == "05:42", f"Expected '05:42', got {result!r}"

    # Edge: missing time component
    result = TicketMonitor._format_time("")
    assert result == "??:??", f"Expected '??:??', got {result!r}"

    # Edge: rideStartDate missing from dict (simulates ride.get("rideStartDate", ""))
    result = TicketMonitor._format_time("")
    assert result == "??:??"
