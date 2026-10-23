"""Sensor platform for Deye Cloud (dynamic measure-point discovery)."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .const import ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity, DeyeStationEntity, async_add_discovered
from .naming import (
    DEVICE_SENSOR_NAMES,
    STATION_SENSOR_NAMES,
    device_class_for,
    device_sensor_enabled_default,
    humanize_key,
    map_api_unit,
    slugify_key,
    state_class_for,
    unit_fallback,
)

# Read-only entities served from the coordinator; no API calls of their own.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a sensor for every measure point the cloud reports a value for.

    The station endpoint returns every field for every station and leaves the
    ones a plant does not have (battery, grid meter) null, so null is skipped.
    """
    coordinator = entry.runtime_data

    def discover() -> Iterator[SensorEntity]:
        for sn in coordinator.device_sns:
            for key, value in coordinator.data["devices"][sn]["data"].items():
                if value is not None:
                    yield DeyeDeviceSensor(coordinator, sn, key)
        for station_id in coordinator.station_ids:
            station = coordinator.data["stations"][station_id]
            for key, value in station.get("data", {}).items():
                if value is not None:
                    yield DeyeStationSensor(coordinator, station_id, key)

    async_add_discovered(entry, async_add_entities, discover)


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
        # Keys the API adds later have no translation and keep a generated name.
        if key in DEVICE_SENSOR_NAMES:
            self._attr_translation_key = slugify_key(key)
        else:
            self._attr_name = humanize_key(key)
        self._attr_device_class = device_class_for(key)
        self._attr_state_class = state_class_for(key)
        if not device_sensor_enabled_default(key):
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

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
        if key in STATION_SENSOR_NAMES:
            self._attr_translation_key = f"station_{slugify_key(key)}"
        else:
            self._attr_name = f"{humanize_key(key)} (Station)"
        self._attr_device_class = device_class_for(key)
        self._attr_state_class = state_class_for(key)
        _, self._attr_native_unit_of_measurement = unit_fallback(key)

    @property
    def native_value(self) -> float | str | None:
        return _coerce(self._station.get("data", {}).get(self._key))
