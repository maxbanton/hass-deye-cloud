"""Switch platform for Deye Cloud."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .const import ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .discovery import config_has
from .entity import DeyeDeviceEntity, async_add_discovered, rejected
from .tou import DeyeTouSlotEntity, effective_tou_slots, tou_slot_indices

_LOGGER = logging.getLogger(__name__)

# Writes go to a rate-limited cloud API, so they are serialized.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def discover() -> Iterator[SwitchEntity]:
        for sn in coordinator.device_sns:
            device = coordinator.data["devices"][sn]
            # Solar sell has no read-back; inverters with a system work mode have it.
            if config_has(device, "systemWorkMode"):
                yield DeyeSolarSellSwitch(coordinator, sn)
            if config_has(device, "touAction"):
                yield DeyeTouSwitch(coordinator, sn)
            for i in tou_slot_indices(device):
                yield DeyeTouSlotGridCharge(coordinator, sn, i)
                yield DeyeTouSlotGen(coordinator, sn, i)

    async_add_discovered(entry, async_add_entities, discover)


class DeyeSolarSellSwitch(DeyeDeviceEntity, SwitchEntity):
    """Toggle grid export (solar sell).

    The Deye API accepts on/off but exposes no read-back of the current state,
    so this is an assumed-state switch reflecting the last command sent.
    """

    _attr_assumed_state = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_solar_sell"
        self.entity_id = f"switch.{ID_PREFIX}_solar_sell"
        self._attr_translation_key = "solar_sell"
        self._attr_is_on = None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.async_set_solar_sell(self._device_sn, enabled)
        except DeyeCloudApiError as err:
            raise rejected(self.name, err) from err
        self._attr_is_on = enabled
        self.async_write_ha_state()
        await self.coordinator.async_request_config_refresh()


class DeyeTouSwitch(DeyeDeviceEntity, SwitchEntity):
    """Enable or disable the time-of-use schedule.

    The active 6-slot schedule is exposed as a state attribute for readback and
    templating; set it with the deye_cloud.set_tou_schedule service.
    """

    _attr_entity_category = EntityCategory.CONFIG
    # The slot entities already record the table's history.
    _unrecorded_attributes = frozenset({"schedule"})

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_tou_enabled"
        # entity_id kept stable (was "Maintain Battery Level") so refs/history survive
        self.entity_id = f"switch.{ID_PREFIX}_maintain_battery_level"
        self._attr_translation_key = "time_of_use"

    @property
    def is_on(self) -> bool | None:
        action = self.coordinator.pending_value(
            self._device_sn, "touAction", self._device.get("config", {}).get("touAction")
        )
        if action is None:
            return None
        return str(action).lower() == "on"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Includes edits that have not read back yet, like the slot entities.
        return {"schedule": effective_tou_slots(self.coordinator, self._device_sn) or None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.async_set_tou_switch(self._device_sn, enabled)
        except DeyeCloudApiError as err:
            raise rejected(self.name, err) from err
        self.coordinator.set_pending(self._device_sn, "touAction", "on" if enabled else "off")
        self.async_write_ha_state()
        await self.coordinator.async_request_config_refresh()


class _DeyeTouSlotSwitch(DeyeTouSlotEntity, SwitchEntity):
    """One boolean field of one Time Of Use slot (read-modify-write)."""

    _domain = "switch"

    @property
    def is_on(self) -> bool | None:
        value = self._raw()
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle(False)

    async def _toggle(self, enabled: bool) -> None:
        try:
            await self._commit(enabled)
        except DeyeCloudApiError as err:
            raise rejected(self.name, err) from err


# Disabled by default: users typically set grid-charge / generator behaviour on
# the inverter first, then enable these in HA only if they want per-slot control.
class DeyeTouSlotGridCharge(_DeyeTouSlotSwitch):
    _field = "enableGridCharge"
    _slug = "grid_charge"
    _attr_entity_registry_enabled_default = False


class DeyeTouSlotGen(_DeyeTouSlotSwitch):
    _field = "enableGeneration"
    _slug = "gen"
    _attr_entity_registry_enabled_default = False
