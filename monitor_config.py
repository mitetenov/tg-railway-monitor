"""Validated monitoring configuration and lifecycle rules."""
from dataclasses import dataclass
from datetime import date


SEAT_CLASSES = frozenset({"Any", "I", "II", "Business"})


class ConfigValidationError(ValueError):
    """Raised when stored monitoring fields do not form a usable config."""


@dataclass(frozen=True)
class MonitorConfig:
    """A complete route, date, and seat-class monitor definition."""

    from_station_code: str
    to_station_code: str
    date: str
    seat_class: str
    from_station: str = ""
    to_station: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MonitorConfig":
        """Create a configuration after validating persisted values."""
        from_code = data.get("from_station_code")
        to_code = data.get("to_station_code")
        travel_date = data.get("date")
        seat_class = data.get("seat_class")
        if not isinstance(from_code, str) or not from_code.isdigit():
            raise ConfigValidationError("from_station_code must be numeric")
        if not isinstance(to_code, str) or not to_code.isdigit():
            raise ConfigValidationError("to_station_code must be numeric")
        if from_code == to_code:
            raise ConfigValidationError("departure and arrival must differ")
        if not isinstance(travel_date, str):
            raise ConfigValidationError("date must be YYYY-MM-DD")
        try:
            date.fromisoformat(travel_date)
        except ValueError as error:
            raise ConfigValidationError("date must be YYYY-MM-DD") from error
        if seat_class not in SEAT_CLASSES:
            raise ConfigValidationError("unknown seat_class")
        return cls(
            from_station_code=from_code,
            to_station_code=to_code,
            date=travel_date,
            seat_class=seat_class,
            from_station=str(data.get("from_station") or ""),
            to_station=str(data.get("to_station") or ""),
        )

    def to_dict(self) -> dict:
        """Return the JSON-compatible monitoring fields."""
        return {
            "from_station_code": self.from_station_code,
            "to_station_code": self.to_station_code,
            "date": self.date,
            "seat_class": self.seat_class,
            "from_station": self.from_station,
            "to_station": self.to_station,
        }

    def is_expired(self, today: date) -> bool:
        """Return whether the travel date is before *today*."""
        return date.fromisoformat(self.date) < today
