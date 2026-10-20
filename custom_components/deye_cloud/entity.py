"""Base entities for Deye Cloud."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeCloudCoordinator


@callback
def async_add_discovered(
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discover: Callable[[], Iterable[Entity]],
) -> None:
    """Add entities as the cloud reports them, now and on every later poll.

    The first poll can be incomplete (a config read failed, a station value was
    still null), so later polls add whatever shows up after setup.
    """
    known: set[str | None] = set()

    @callback
    def _add() -> None:
        new = [entity for entity in discover() if entity.unique_id not in known]
        known.update(entity.unique_id for entity in new)
        if new:
            async_add_entities(new)

    _add()
    entry.async_on_unload(entry.runtime_data.async_add_listener(_add))


class DeyeDeviceEntity(CoordinatorEntity[DeyeCloudCoordinator]):
    """Base for entities tied to a Deye device (inverter)."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator)
        self._device_sn = device_sn

    @property
    def _device(self) -> dict[str, Any]:
        return self.coordinator.data.get("devices", {}).get(self._device_sn, {})

    @property
    def device_info(self) -> dict[str, Any]:
        info = self._device.get("info", {})
        device_type = info.get("deviceType")
        return {
            "identifiers": {(DOMAIN, self._device_sn)},
            "name": f"Deye {device_type}" if device_type else f"Deye {self._device_sn}",
            "manufacturer": "Deye",
            "model": info.get("deviceModel") or info.get("deviceType") or "Inverter",
            "sw_version": info.get("firmwareVersion"),
            "serial_number": self._device_sn,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self._device.get("data"))


class DeyeStationEntity(CoordinatorEntity[DeyeCloudCoordinator]):
    """Base for station-level entities."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: DeyeCloudCoordinator, station_id: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id

    @property
    def _station(self) -> dict[str, Any]:
        return self.coordinator.data.get("stations", {}).get(self._station_id, {})

    @property
    def device_info(self) -> dict[str, Any]:
        info = self._station.get("info", {})
        return {
            "identifiers": {(DOMAIN, f"station_{self._station_id}")},
            "name": info.get("name") or f"Deye Station {self._station_id}",
            "manufacturer": "Deye",
            "model": "Station",
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
