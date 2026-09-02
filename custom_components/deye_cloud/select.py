"""Select platform for Deye Cloud (work mode, energy pattern)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DeyeCloudApiError
from .const import (
    COORDINATOR,
    DOMAIN,
    ENERGY_PATTERN_LABELS,
    ENERGY_PATTERNS,
    ID_PREFIX,
    WORK_MODE_LABELS,
    WORK_MODES,
)
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCloudCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    entities: list[SelectEntity] = []
    for sn in coordinator.device_sns:
        entities.append(DeyeWorkModeSelect(coordinator, sn))
        entities.append(DeyeEnergyPatternSelect(coordinator, sn))
    async_add_entities(entities)


class _DeyeLabelledSelect(DeyeDeviceEntity, SelectEntity):
    """Select that shows friendly labels but sends raw enum values to the API."""

    _values: list[str] = []
    _labels: dict[str, str] = {}
    _config_keys: tuple[str, ...] = ()

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_options = list(self._labels.values())
        self._label_to_value = {v: k for k, v in self._labels.items()}

    @property
    def current_option(self) -> str | None:
        config = self._device.get("config", {})
        for key in self._config_keys:
            value = config.get(key)
            if value in self._values:
                return self._labels.get(value, value)
        return None

    async def async_select_option(self, option: str) -> None:
        value = self._label_to_value.get(option, option)
        if value not in self._values:
            _LOGGER.error("Invalid option %s", option)
            return
        try:
            await self._apply(value)
        except DeyeCloudApiError as err:
            _LOGGER.error("Failed to set %s: %s", self._attr_name, err)
            return
        await self.coordinator.async_request_refresh()

    async def _apply(self, value: str) -> None:
        raise NotImplementedError


class DeyeWorkModeSelect(_DeyeLabelledSelect):
    _attr_icon = "mdi:cog"
    _values = WORK_MODES
    _labels = WORK_MODE_LABELS
    _config_keys = ("workMode", "systemWorkMode")

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_work_mode"
        self.entity_id = f"select.{ID_PREFIX}_work_mode"
        self._attr_name = "Work Mode"

    async def _apply(self, value: str) -> None:
        await self.coordinator.client.async_set_work_mode(self._device_sn, value)


class DeyeEnergyPatternSelect(_DeyeLabelledSelect):
    _attr_icon = "mdi:battery-arrow-up"
    _values = ENERGY_PATTERNS
    _labels = ENERGY_PATTERN_LABELS
    _config_keys = ("energyPattern", "systemEnergyPattern")

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_energy_pattern"
        self.entity_id = f"select.{ID_PREFIX}_energy_pattern"
        self._attr_name = "Energy Pattern"

    async def _apply(self, value: str) -> None:
        await self.coordinator.client.async_set_energy_pattern(self._device_sn, value)
