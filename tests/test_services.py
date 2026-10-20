"""Tests for the TOU service payload mapping."""
import pytest
import voluptuous as vol

from custom_components.deye_cloud.api import _normalize_tou_time
from custom_components.deye_cloud.services import _to_items, _tou_time


def test_to_items_maps_screen_fields_to_api():
    slots = [
        {"time": "01:00", "power": 6000, "batt": 90, "grid_charge": True, "gen": False},
        {"time": "13:00", "power": 3000, "batt": 30, "grid_charge": False, "gen": True,
         "sell": True, "voltage": 52},
    ]
    items = _to_items(slots)
    assert items[0] == {
        "time": "01:00", "power": 6000, "soc": 90,
        "enableGridCharge": True, "enableGeneration": False,
    }
    assert items[1] == {
        "time": "13:00", "power": 3000, "soc": 30,
        "enableGridCharge": False, "enableGeneration": True,
        "voltage": 52, "enableSell": True,
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0100", "01:00"),
        ("100", "01:00"),
        ("01:00", "01:00"),
        ("9:5", "09:05"),
        (2100, "21:00"),
        ("2100", "21:00"),
    ],
)
def test_normalize_tou_time(value, expected):
    assert _normalize_tou_time(value) == expected


@pytest.mark.parametrize("value", ["01:00", "6:05", "2355", "0100"])
def test_tou_time_accepts_five_minute_steps(value):
    assert _tou_time(value) == value


@pytest.mark.parametrize("value", ["06:03", "0602", "noon"])
def test_tou_time_rejects_other_times(value):
    with pytest.raises(vol.Invalid):
        _tou_time(value)
