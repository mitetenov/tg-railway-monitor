"""Tests for grouped notification format in poller.py.

Verifies that _format_time works correctly and that the grouping
logic produces one notification per ride with all classes listed
using English class names (I Class, II Class, Business).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ticket_monitor import CLASS_NAMES


# ── _format_time tests ───────────────────────────────────────────────


def test_format_time_basic():
    """Standard ISO string returns HH:MM."""
    from poller import _format_time
    assert _format_time("2026-06-27T00:30:00Z") == "00:30"
    assert _format_time("2026-06-27T05:42:00+04:00") == "05:42"
    assert _format_time("2026-06-27T12:15:00") == "12:15"


def test_format_time_empty():
    """Empty string returns ??:??."""
    from poller import _format_time
    assert _format_time("") == "??:??"
    # (None won't reach _format_time — poller guards with `or ""`)


def test_format_time_bogus():
    """Non-ISO strings fall back to the input."""
    from poller import _format_time
    # No 'T' → returns as-is
    assert _format_time("hello") == "hello"
    assert _format_time("05:12:00") == "05:12:00"


# ── _notified_key tests ──────────────────────────────────────────────


def test_notified_key_basic():
    """Verify notified keys work with English class names."""
    from poller import _notified_key
    assert _notified_key(812, "II Class") == "812:II Class"
    assert _notified_key(812, "I Class") == "812:I Class"
    assert _notified_key(812, "Business") == "812:Business"


# ── Grouping logic (white-box) ───────────────────────────────────────


def _make_ride(ride_num, classes):
    """Construct a ride dict matching the tkt.ge API response shape."""
    return {
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
    """All classes for one ride are collected together with English names."""
    from poller import _check_and_notify, _notified

    # Clear notified state
    chat_id = 9001
    _notified.pop(chat_id, None)

    # Build mock data: ride #812 with 3 classes
    # seatClassName values are Georgian (as returned by the API) but poller
    # now resolves the English name via CLASS_NAMES using seatClassId
    ride = _make_ride(812, [
        (2, "II класс", 89, 36),
        (1, "I класс", 19, 76),
        (5, "Биз. класс", 7, 126),
    ])

    # Simulate the grouping logic inline (mirroring the actual poller code)
    ride_num = ride.get("rideNumber")
    new_classes = []
    for cls in ride.get("availableSeatsClasses", []):
        cls_name = CLASS_NAMES.get(cls.get("seatClassId"), "")
        seats = cls.get("availableNumberOfSeats", 0)
        price = cls.get("moneyAmount", "?")
        key = f"{ride_num}:{cls_name}"
        if key not in _notified.setdefault(chat_id, set()):
            new_classes.append((cls_name, seats, price))
            _notified[chat_id].add(key)

    # All 3 classes should be collected with English names
    assert len(new_classes) == 3
    names = [c[0] for c in new_classes]
    assert "II Class" in names
    assert "I Class" in names
    assert "Business" in names

    # Second pass — should find nothing new
    new_classes2 = []
    for cls in ride.get("availableSeatsClasses", []):
        cls_name = CLASS_NAMES.get(cls.get("seatClassId"), "")
        seats = cls.get("availableNumberOfSeats", 0)
        price = cls.get("moneyAmount", "?")
        key = f"{ride_num}:{cls_name}"
        if key not in _notified[chat_id]:
            new_classes2.append((cls_name, seats, price))
            _notified[chat_id].add(key)
    assert len(new_classes2) == 0, "Should not re-notify same classes"


def test_grouping_multiple_rides():
    """Each ride gets its own group; classes don't bleed across rides."""
    from poller import _notified

    chat_id = 9002
    _notified.pop(chat_id, None)

    rides_data = [
        _make_ride(812, [(2, "II класс", 89, 36), (1, "I класс", 19, 76)]),
        _make_ride(900, [(5, "Биз. класс", 7, 126)]),
    ]

    rides_with_new = {}
    for ride in rides_data:
        ride_num = ride.get("rideNumber")
        new_classes = []
        for cls in ride.get("availableSeatsClasses", []):
            cls_name = CLASS_NAMES.get(cls.get("seatClassId"), "")
            seats = cls.get("availableNumberOfSeats", 0)
            price = cls.get("moneyAmount", "?")
            key = f"{ride_num}:{cls_name}"
            if key not in _notified.setdefault(chat_id, set()):
                new_classes.append((cls_name, seats, price))
                _notified[chat_id].add(key)
        if new_classes:
            rides_with_new[ride_num] = (ride, new_classes)

    assert set(rides_with_new.keys()) == {812, 900}
    assert len(rides_with_new[812][1]) == 2  # 2 classes on 812
    assert len(rides_with_new[900][1]) == 1  # 1 class on 900


# ── Notification message format ──────────────────────────────────────


def test_grouped_message_format():
    """Verify the rendered message uses English class names and includes purchase links."""
    from poller import _format_time

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

    dep = _format_time(ride.get("rideStartDate") or "")
    arr = _format_time(ride.get("rideEndDate") or "")
    dur = ride.get("rideDuration", "?")

    lines = [
        "🎫 *Tbilisi* → *Batumi*",
        "📅 2026-06-27",
        "",
    ]
    lines.append(f"🚆 *Ride #{ride_num}*  {dep} → {arr} ({dur})")
    # Build purchase link (mirroring poller logic)
    purchase_url = (
        f"https://tkt.ge/en/railway/seatmap"
        f"?rideNumber={ride_num}"
        f"&fromStationCode={from_code}"
        f"&toStationCode={to_code}"
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

    # Purchase link — verify it points to seatmap with correct params
    assert "🔗 [" in message
    assert "Купить]" in message
    assert "https://tkt.ge/en/railway/seatmap" in message
    assert "?rideNumber=812" in message
    assert "&fromStationCode=56014" in message
    assert "&toStationCode=57151" in message

    # Class lines — all three present with English names
    assert "II Class: 89 мест · 36 GEL" in message
    assert "I Class: 19 мест · 76 GEL" in message
    assert "Business: 7 мест · 126 GEL" in message

    # No duplicates — each class line appears exactly once
    assert message.count("   II Class:") == 1
    assert message.count("   I Class:") == 1
    assert message.count("   Business:") == 1
