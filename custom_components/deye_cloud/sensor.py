"""Sensor platform for Deye Cloud (dynamic measure-point discovery)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN, ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity, DeyeStationEntity
from .naming import (
    DEVICE_SENSOR_NAMES,
    STATION_SENSOR_NAMES,
    device_class_for,
    humanize_key,
    map_api_unit,
    slugify_key,
    state_class_for,
    unit_fallback,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a sensor for every measure point discovered in the first poll."""
    coordinator: DeyeCloudCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    entities: list[SensorEntity] = []
    for sn in coordinator.device_sns:
        for key in coordinator.data["devices"][sn]["data"]:
            entities.append(DeyeDeviceSensor(coordinator, sn, key))
    for station_id in coordinator.station_ids:
        for key in coordinator.data["stations"][station_id].get("data", {}):
            entities.append(DeyeStationSensor(coordinator, station_id, key))

    async_add_entities(entities)


def _coerce(value: Any) -> float | str | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


class DeyeDeviceSensor(DeyeDeviceEntity, SensorEntity):
    """A single device measure point."""

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str, key: str) -> None:
        super().__init__(coordinator, device_sn)
        self._key = key
        self._attr_unique_id = f"{device_sn}_{key}"
        self.entity_id = f"sensor.{ID_PREFIX}_{slugify_key(key)}"
        self._attr_name = DEVICE_SENSOR_NAMES.get(key) or humanize_key(key)
        self._attr_device_class = device_class_for(key)
        self._attr_state_class = state_class_for(key)

    @property
    def native_unit_of_measurement(self) -> str | None:
        api_unit = map_api_unit(self._device.get("units", {}).get(self._key))
        if api_unit is not None:
            return api_unit
        has_override, unit = unit_fallback(self._key)
        return unit if has_override else None

    @property
    def native_value(self) -> float | str | None:
        return _coerce(self._device.get("data", {}).get(self._key))


class DeyeStationSensor(DeyeStationEntity, SensorEntity):
    """A single station measure point (station payload carries no units)."""

    def __init__(self, coordinator: DeyeCloudCoordinator, station_id: str, key: str) -> None:
        super().__init__(coordinator, station_id)
        self._key = key
        self._attr_unique_id = f"{station_id}_{key}"
        self.entity_id = f"sensor.{ID_PREFIX}_station_{slugify_key(key)}"
        base = STATION_SENSOR_NAMES.get(key) or humanize_key(key)
        self._attr_name = f"{base} (Station)"
        self._attr_device_class = device_class_for(key)
        self._attr_state_class = state_class_for(key)
        _, self._attr_native_unit_of_measurement = unit_fallback(key)

    @property
    def native_value(self) -> float | str | None:
        return _coerce(self._station.get("data", {}).get(self._key))
