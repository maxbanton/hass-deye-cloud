"""Select platform for Deye Cloud."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .const import DOMAIN, ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .discovery import config_has, has_battery
from .entity import DeyeDeviceEntity, async_add_discovered, rejected

_LOGGER = logging.getLogger(__name__)

# Writes go to a rate-limited cloud API, so they are serialized.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def discover() -> Iterator[SelectEntity]:
        for sn in coordinator.device_sns:
            device = coordinator.data["devices"][sn]
            # Battery First means nothing without a battery, even on a hybrid.
            if has_battery(device) and config_has(device, "energyPattern"):
                yield DeyeEnergyPatternSelect(coordinator, sn)

    async_add_discovered(entry, async_add_entities, discover)


# Human-readable labels shown in HA, mapped to the API's raw enum values.
_PATTERN_LABELS = {"LOAD_FIRST": "Load First", "BATTERY_FIRST": "Battery First"}
_LABEL_TO_API = {label: api for api, label in _PATTERN_LABELS.items()}


class DeyeEnergyPatternSelect(DeyeDeviceEntity, SelectEntity):
    """Energy management pattern: whether load or battery is served first."""

    _attr_options = list(_PATTERN_LABELS.values())

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_energy_pattern"
        self.entity_id = f"select.{ID_PREFIX}_energy_pattern"
        self._attr_translation_key = "energy_pattern"

    @property
    def current_option(self) -> str | None:
        # Cloud read-back lags a write by minutes; show the requested value until
        # it catches up.
        api_value = self.coordinator.pending_value(
            self._device_sn,
            "energyPattern",
            self._device.get("config", {}).get("energyPattern"),
        )
        return _PATTERN_LABELS.get(api_value)

    async def async_select_option(self, option: str) -> None:
        api_value = _LABEL_TO_API.get(option)
        if api_value is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_option",
                translation_placeholders={"name": str(self.name), "option": option},
            )
        try:
            await self.coordinator.client.async_set_energy_pattern(
                self._device_sn, api_value
            )
        except DeyeCloudApiError as err:
            raise rejected(self.name, err) from err
        self.coordinator.set_pending(self._device_sn, "energyPattern", api_value)
        self.async_write_ha_state()
        await self.coordinator.async_request_config_refresh()
