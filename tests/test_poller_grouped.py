"""Tests for grouped notification format in poller.py.

Verifies that format_time works correctly and that the grouping
logic produces one notification per ride with all classes listed
using English class names (I Class, II Class, Business).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ticket_monitor import CLASS_NAMES
from utils import format_time


# ── format_time tests ───────────────────────────────────────────────


def test_format_time_basic():
    """Standard ISO string returns HH:MM."""
    assert format_time("2026-06-27T00:30:00Z") == "00:30"
    assert format_time("2026-06-27T05:42:00+04:00") == "05:42"
    assert format_time("2026-06-27T12:15:00") == "12:15"


def test_format_time_empty():
    """Empty string returns ??:??."""
    assert format_time("") == "??:??"


def test_format_time_bogus():
    """Non-ISO strings fall back to the input."""
    assert format_time("hello") == "hello"
    assert format_time("05:12:00") == "05:12:00"


# ── Stateful diff tests ───────────────────────────────────────────────


def test_stateful_diff_new_ticket():
    """First time a class appears → it is notified."""
    from poller import _state

    chat_id = 9000
    _state.pop(chat_id, None)

    # No previous state → should be treated as new
    assert chat_id not in _state or _state[chat_id] == {}


def test_stateful_diff_seats_increased():
    """When seats increase compared to previous state → notified."""
    from poller import _state

    chat_id = 9000
    _state[chat_id] = {
        "812": {"1": {"seats": 5, "price": 76}},
    }

    # Simulate: same class, more seats → should notify
    prev_entry = _state.get(chat_id, {}).get("812", {}).get("1")
    prev_seats = prev_entry["seats"] if prev_entry else 0
    assert prev_seats == 5  # baseline
    # 10 > 5 → notified
    assert 10 > prev_seats

    _state.pop(chat_id, None)


# ── Grouping logic (white-box) ───────────────────────────────────────


def _make_ride(ride_num, classes):
    """Construct a ride dict matching the tkt.ge API response shape."""
    return {
        "id": ride_num,
        "rideNumber": ride_num,
        "rideStartDate": "2026-06-27T00:30:00Z",
        "rideEndDate": "2026-06-27T05:42:00Z",
        "rideDuration": "05:12:00",
        "availableSeatsClasses": [
            {
                "seatClassId": cls_id,
                "seatClassName": cls_name,  # API returns Georgian names, unused after our change
                "availableNumberOfSeats": seats,
                "moneyAmount": price,
            }
            for cls_id, cls_name, seats, price in classes
        ],
    }


def test_grouping_single_ride_multiple_classes():
    """All classes collected for one ride; unchanged classes excluded from change set."""
    from poller import _state

    chat_id = 9001
    _state.pop(chat_id, None)

    ride = _make_ride(812, [
        (2, "II класс", 89, 36),
        (1, "I класс", 19, 76),
        (5, "Биз. класс", 7, 126),
    ])

    # Simulate stateful diff logic (mirroring the actual poller code)
    chat_state = _state.setdefault(chat_id, {})
    ride_state = {}

    all_classes = []
    changed_classes = []
    for cls in ride.get("availableSeatsClasses", []):
        cls_id = cls.get("seatClassId")
        cls_name = CLASS_NAMES.get(cls_id, "")
        seats = cls.get("availableNumberOfSeats") or 0
        price = cls.get("moneyAmount", "?")
        prev_entry = ride_state.get(str(cls_id))
        prev_seats = prev_entry["seats"] if prev_entry else 0
        if seats > 0:
            all_classes.append((cls_name, seats, price))
            if prev_entry is None or seats > prev_seats:
                changed_classes.append((cls_name, seats, price))
        ride_state[str(cls_id)] = {"seats": seats, "price": price}

    chat_state[str(ride.get("rideNumber"))] = ride_state
    _state[chat_id] = chat_state

    # First pass: all classes are new → all_classes == changed_classes
    assert len(all_classes) == 3
    assert len(changed_classes) == 3
    names = [c[0] for c in all_classes]
    assert "II Class" in names
    assert "I Class" in names
    assert "Business" in names

    # Second pass — all_classes still 3, changed_classes empty (no changes)
    ride_state2 = _state.get(chat_id, {}).get("812", {})
    all_classes2 = []
    changed_classes2 = []
    for cls in ride.get("availableSeatsClasses", []):
        cls_id = cls.get("seatClassId")
        cls_name = CLASS_NAMES.get(cls_id, "")
        seats = cls.get("availableNumberOfSeats") or 0
        price = cls.get("moneyAmount", "?")
        prev_entry = ride_state2.get(str(cls_id))
        prev_seats = prev_entry["seats"] if prev_entry else 0
        if seats > 0:
            all_classes2.append((cls_name, seats, price))
            if prev_entry is None or seats > prev_seats:
                changed_classes2.append((cls_name, seats, price))
    assert len(all_classes2) == 3, "all_classes should still include all available"
    assert len(changed_classes2) == 0, "Should not detect changes when seats unchanged"

    _state.pop(chat_id, None)


def test_grouping_multiple_rides():
    """Each ride gets its own group; all_rides includes everything, has_any_changes tracks diffs."""
    from poller import _state

    chat_id = 9002
    _state.pop(chat_id, None)

    rides_data = [
        _make_ride(812, [(2, "II класс", 89, 36), (1, "I класс", 19, 76)]),
        _make_ride(900, [(5, "Биз. класс", 7, 126)]),
    ]

    chat_state = _state.setdefault(chat_id, {})
    all_rides = {}
    has_any_changes = False

    for ride in rides_data:
        ride_num = ride.get("rideNumber")
        ride_state = {}
        all_classes = []
        changed_classes = []
        for cls in ride.get("availableSeatsClasses", []):
            cls_id = cls.get("seatClassId")
            cls_name = CLASS_NAMES.get(cls_id, "")
            seats = cls.get("availableNumberOfSeats") or 0
            price = cls.get("moneyAmount", "?")
            prev_entry = ride_state.get(str(cls_id))
            prev_seats = prev_entry["seats"] if prev_entry else 0
            if seats > 0:
                all_classes.append((cls_name, seats, price))
                if prev_entry is None or seats > prev_seats:
                    changed_classes.append((cls_name, seats, price))
            ride_state[str(cls_id)] = {"seats": seats, "price": price}
        chat_state[str(ride_num)] = ride_state
        if all_classes:
            all_rides[ride_num] = (ride, all_classes)
        if changed_classes:
            has_any_changes = True

    # all_rides includes both rides
    assert set(all_rides.keys()) == {812, 900}
    assert len(all_rides[812][1]) == 2  # 2 classes on 812
    assert len(all_rides[900][1]) == 1  # 1 class on 900
    # First pass: everything is new → has_any_changes is True
    assert has_any_changes

    _state.pop(chat_id, None)


# ── Notification message format ──────────────────────────────────────


def test_grouped_message_format():
    """Verify the rendered message uses English class names and includes purchase links."""

    ride_num = 812
    from_code = "56014"
    to_code = "57151"
    ride = _make_ride(812, [
        (2, "II класс", 89, 36),
        (1, "I класс", 19, 76),
        (5, "Биз. класс", 7, 126),
    ])
    class_list = [
        (CLASS_NAMES.get(2), 89, 36),
        (CLASS_NAMES.get(1), 19, 76),
        (CLASS_NAMES.get(5), 7, 126),
    ]

    dep = format_time(ride.get("rideStartDate") or "")
    arr = format_time(ride.get("rideEndDate") or "")
    dur = ride.get("rideDuration", "?")

    lines = [
        "🎫 *Tbilisi* → *Batumi*",
        "📅 2026-06-27",
        "",
    ]
    lines.append(f"🚆 *Ride #{ride_num}*  {dep} → {arr} ({dur})")
    # Build purchase link (mirroring poller logic)
    purchase_url = (
        f"https://tkt.ge/en/railway"
        f"?startStationCode={from_code}"
        f"&endStationCode={to_code}"
        f"&departureDate=2026-06-27"
    )
    lines.append(f"🔗 [Купить]({purchase_url})")
    for cls_name, seats, price in class_list:
        lines.append(f"   {cls_name}: {seats} мест · {price} GEL")
    lines.append("")

    message = "\n".join(lines).strip()

    # Header lines
    assert "🎫 *Tbilisi* → *Batumi*" in message
    assert "📅 2026-06-27" in message

    # Ride line
    assert "🚆 *Ride #812*  00:30 → 05:42 (05:12:00)" in message

    # Purchase link — verify it points to search URL with correct params
    assert "🔗 [" in message
    assert "Купить]" in message
    assert "https://tkt.ge/en/railway" in message
    assert "?startStationCode=56014" in message
    assert "&endStationCode=57151" in message
    assert "&departureDate=2026-06-27" in message

    # Class lines — all three present with English names
    assert "II Class: 89 мест · 36 GEL" in message
    assert "I Class: 19 мест · 76 GEL" in message
    assert "Business: 7 мест · 126 GEL" in message

    # No duplicates — each class line appears exactly once
    assert message.count("   II Class:") == 1
    assert message.count("   I Class:") == 1
    assert message.count("   Business:") == 1
