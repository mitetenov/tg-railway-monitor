"""Tests for presentation helpers used by notification rendering."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import fmt_duration, format_time


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2099-07-15T00:30:00Z", "00:30"),
        ("2099-07-15T23:59:59-05:00", "23:59"),
        ("2099-07-15T12:30:45.123Z", "12:30"),
        ("", "??:??"),
        ("not-a-time", "not-a-time"),
    ],
)
def test_format_time(value, expected):
    assert format_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("05:12:00", "5h 12m"),
        ("00:00:00", "0h 00m"),
        ("", "??:??"),
        ("not-a-duration", "not-a-duration"),
    ],
)
def test_format_duration(value, expected):
    assert fmt_duration(value) == expected
