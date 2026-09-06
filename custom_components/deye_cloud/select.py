"""Select platform for Deye Cloud."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DeyeCloudApiError
from .const import COORDINATOR, DOMAIN, ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCloudCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities(
        DeyeEnergyPatternSelect(coordinator, sn) for sn in coordinator.device_sns
    )


# Human-readable labels shown in HA, mapped to the API's raw enum values.
_PATTERN_LABELS = {"LOAD_FIRST": "Load First", "BATTERY_FIRST": "Battery First"}
_LABEL_TO_API = {label: api for api, label in _PATTERN_LABELS.items()}


class DeyeEnergyPatternSelect(DeyeDeviceEntity, SelectEntity):
    """Energy management pattern: whether load or battery is served first."""

    _attr_icon = "mdi:home-lightning-bolt"
    _attr_options = list(_PATTERN_LABELS.values())

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_energy_pattern"
        self.entity_id = f"select.{ID_PREFIX}_energy_pattern"
        self._attr_name = "Energy Pattern"
        self._optimistic: str | None = None

    @property
    def current_option(self) -> str | None:
        api_value = self._device.get("config", {}).get("energyPattern")
        # Cloud read-back lags a write by minutes; show the requested value until
        # it catches up.
        if self._optimistic is not None:
            if api_value == self._optimistic:
                self._optimistic = None
            else:
                return _PATTERN_LABELS.get(self._optimistic)
        return _PATTERN_LABELS.get(api_value)

    async def async_select_option(self, option: str) -> None:
        api_value = _LABEL_TO_API.get(option)
        if api_value is None:
            raise HomeAssistantError(f"Unknown Energy Pattern: {option}")
        try:
            await self.coordinator.client.async_set_energy_pattern(
                self._device_sn, api_value
            )
        except DeyeCloudApiError as err:
            raise HomeAssistantError(f"Inverter rejected Energy Pattern: {err}") from err
        self._optimistic = api_value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
