"""Tests for the TOU service payload mapping."""
from custom_components.deye_cloud.services import _to_items


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
