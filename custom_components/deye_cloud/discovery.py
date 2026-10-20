"""What a device can do, decided from what the Deye Cloud reports for it.

Nothing here is keyed on a model list. /device/measurePoints returns the measure
points Deye defines for the device's product, which tells a hybrid with a
battery apart from a string inverter, and the config endpoints only return the
settings the inverter actually has.
"""
from __future__ import annotations

from typing import Any

# The device types /device/measurePoints and the config endpoints answer for.
INVERTER_TYPES = frozenset({"INVERTER", "MICRO_INVERTER", "MICRO_STORAGE_IN_ONE", "MECD"})

BATTERY_POINT = "SOC"


def is_inverter(device: dict[str, Any]) -> bool:
    return device.get("info", {}).get("deviceType") in INVERTER_TYPES


def has_battery(device: dict[str, Any]) -> bool:
    """True when the product has a battery; falls back to live keys if unknown."""
    points = device.get("measure_points")
    if points is None:
        points = device.get("data", {})
    return BATTERY_POINT in points


def config_has(device: dict[str, Any], key: str) -> bool:
    return device.get("config", {}).get(key) is not None
