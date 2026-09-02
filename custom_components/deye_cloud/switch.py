"""Switch platform for Deye Cloud."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    entities: list[SwitchEntity] = []
    for sn in coordinator.device_sns:
        entities.append(DeyeSolarSellSwitch(coordinator, sn))
        entities.append(DeyeTouSwitch(coordinator, sn))
    async_add_entities(entities)


class DeyeSolarSellSwitch(DeyeDeviceEntity, SwitchEntity):
    """Toggle grid export (solar sell).

    The Deye API accepts on/off but exposes no read-back of the current state,
    so this is an assumed-state switch reflecting the last command sent.
    """

    _attr_icon = "mdi:transmission-tower-export"
    _attr_assumed_state = True

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_solar_sell"
        self.entity_id = f"switch.{ID_PREFIX}_solar_sell"
        self._attr_name = "Solar Sell"
        self._attr_is_on = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.async_set_solar_sell(self._device_sn, enabled)
        except DeyeCloudApiError as err:
            _LOGGER.error("Failed to set solar sell: %s", err)
            return
        self._attr_is_on = enabled
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class DeyeTouSwitch(DeyeDeviceEntity, SwitchEntity):
    """Enable or disable the time-of-use schedule.

    The active 6-slot schedule is exposed as a state attribute for readback and
    templating; set it with the deye_cloud.set_tou_schedule service.
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_tou_enabled"
        self.entity_id = f"switch.{ID_PREFIX}_tou"
        self._attr_name = "Time of Use"

    @property
    def is_on(self) -> bool | None:
        action = self._device.get("config", {}).get("touAction")
        if action is None:
            return None
        return str(action).lower() == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"schedule": self._device.get("config", {}).get("timeUseSettingItems")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.async_set_tou_switch(self._device_sn, enabled)
        except DeyeCloudApiError as err:
            _LOGGER.error("Failed to set TOU switch: %s", err)
            return
        await self.coordinator.async_request_refresh()
