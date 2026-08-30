"""Tests for the validated monitoring configuration value object."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monitor_config import ConfigValidationError, MonitorConfig


def _valid_config(**overrides):
    config = {
        "from_station_code": "56014",
        "to_station_code": "57151",
        "date": "2099-07-15",
        "seat_class": "Any",
        "from_station": "Tbilisi",
        "to_station": "Batumi",
    }
    config.update(overrides)
    return config


def test_round_trip_preserves_monitoring_fields():
    config = MonitorConfig.from_dict(_valid_config())

    assert config.to_dict() == _valid_config()
    assert not config.is_expired(date(2099, 7, 15))


@pytest.mark.parametrize(
    "overrides",
    [
        {"from_station_code": None},
        {"to_station_code": "not-a-code"},
        {"to_station_code": "56014"},
        {"date": "2099-99-15"},
        {"date": None},
        {"seat_class": "Sleeper"},
    ],
)
def test_invalid_monitor_configs_are_rejected(overrides):
    with pytest.raises(ConfigValidationError):
        MonitorConfig.from_dict(_valid_config(**overrides))
