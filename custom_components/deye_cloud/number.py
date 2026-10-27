"""Number platform for Deye Cloud set-points."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .const import ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .discovery import config_has
from .entity import DeyeDeviceEntity, async_add_discovered, rejected
from .tou import DeyeTouSlotEntity, tou_slot_indices

_LOGGER = logging.getLogger(__name__)

# Writes go to a rate-limited cloud API, so they are serialized.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def discover() -> Iterator[NumberEntity]:
        for sn in coordinator.device_sns:
            device = coordinator.data["devices"][sn]
            for cls in (
                DeyeMaxChargeCurrent,
                DeyeMaxDischargeCurrent,
                DeyeGridChargeCurrent,
                DeyeMaxSellPower,
                DeyeLowBatterySoc,
            ):
                if config_has(device, cls._config_key):
                    yield cls(coordinator, sn)
            for i in tou_slot_indices(device):
                yield DeyeTouSlotSoc(coordinator, sn, i)
                yield DeyeTouSlotPower(coordinator, sn, i)
                yield DeyeTouSlotVoltage(coordinator, sn, i)

    async_add_discovered(entry, async_add_entities, discover)


class _DeyeNumber(DeyeDeviceEntity, NumberEntity):
    """Base set-point number; reads current value from config, writes via API.

    These are set-once inverter parameters, grouped under Configuration.
    """

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _config_key: str = ""
    _slug: str = ""

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_{self._slug}"
        self.entity_id = f"number.{ID_PREFIX}_{self._slug}"
        self._attr_translation_key = self._slug

    @property
    def native_value(self) -> float | None:
        value = self._device.get("config", {}).get(self._config_key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._apply(int(value))
        except DeyeCloudApiError as err:
            raise rejected(self.name, err, value) from err
        await self.coordinator.async_request_config_refresh()

    async def _apply(self, value: int) -> None:
        raise NotImplementedError


# The API exposes no per-model current limit and no stable nominal voltage, so
# there is nothing to derive a real ceiling from. Deriving one from live values
# (e.g. RatedPower / BatteryVoltage) is wrong: the pack voltage fluctuates, so a
# low battery would shrink the control's range and falsely limit the setting.
# Instead this is a fixed, stable, permissive input bound only -- the inverter
# firmware is the authority on the true per-model limit and rejects anything it
# will not accept, which surfaces via HomeAssistantError.
_CURRENT_UI_MAX = 250.0


class _DeyeCurrentNumber(_DeyeNumber):
    """Battery current set-point; the inverter enforces the real per-model limit."""

    _attr_entity_category = None  # primary control, not Configuration
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_max_value = _CURRENT_UI_MAX
    _attr_native_step = 1


class DeyeMaxChargeCurrent(_DeyeCurrentNumber):
    _config_key = "maxChargeCurrent"
    _slug = "max_charge_current"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "MAX_CHARGE_CURRENT", value
        )


class DeyeMaxDischargeCurrent(_DeyeCurrentNumber):
    _attr_entity_registry_enabled_default = False
    _config_key = "maxDischargeCurrent"
    _slug = "max_discharge_current"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "MAX_DISCHARGE_CURRENT", value
        )


class DeyeGridChargeCurrent(_DeyeCurrentNumber):
    """How much of the battery charge current may come from the grid."""

    _config_key = "gridChargeAmpere"
    _slug = "grid_charge_current"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "GRID_CHARGE_AMPERE", value
        )


class DeyeMaxSellPower(_DeyeNumber):
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_max_value = 30000
    _attr_native_step = 100
    _config_key = "maxSellPower"
    _slug = "max_sell_power"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_power_param(
            self._device_sn, "MAX_SELL_POWER", value
        )


class DeyeLowBatterySoc(_DeyeNumber):
    """Low Battery SOC (the inverter's Low Batt / battLowCapacity setting)."""

    _attr_entity_category = None  # primary control, not Configuration
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 5
    _attr_native_max_value = 100
    _attr_native_step = 1
    _config_key = "battLowCapacity"
    _slug = "low_battery_soc"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "BATT_LOW", value
        )


class _DeyeTouSlotNumber(DeyeTouSlotEntity, NumberEntity):
    """Base for one numeric field of one Time Of Use slot."""

    _domain = "number"
    _attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        try:
            return float(self._raw())
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._commit(int(value))
        except (DeyeCloudApiError, ValueError) as err:
            raise rejected(self.name, err, value) from err


class DeyeTouSlotSoc(_DeyeTouSlotNumber):
    _field = "soc"
    _slug = "soc"
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1


class DeyeTouSlotPower(_DeyeTouSlotNumber):
    """Per-slot charge/discharge power; slider scales to the device's rated power."""

    _field = "power"
    _slug = "power"
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 100
    _attr_entity_registry_enabled_default = False
    _fallback_max = 16000

    @property
    def native_max_value(self) -> float:
        # Bound the slider by what this specific inverter reports it can do, so
        # the control is right on any model; fall back until data arrives.
        rated = self._device.get("data", {}).get("RatedPower")
        try:
            rated = float(rated)
        except (TypeError, ValueError):
            rated = 0.0
        return rated if rated > 0 else self._fallback_max


class DeyeTouSlotVoltage(_DeyeTouSlotNumber):
    """Per-slot battery target voltage (only used in voltage mode)."""

    _field = "voltage"
    _slug = "voltage"
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_native_min_value = 40
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_entity_registry_enabled_default = False
