"""Shared ticket-domain vocabulary used by the active monitoring flow."""

from typing import Final


CLASS_NAMES: Final[dict[int, str]] = {
    1: "I Class",
    2: "II Class",
    5: "Business",
}
"""tre.ge seat class identifier to the display name used in notifications."""

CLASS_FILTER_IDS: Final[dict[str, int]] = {
    "I": 1,
    "II": 2,
    "Business": 5,
}
"""Wizard seat-class value to the tre.ge seat class identifier."""
