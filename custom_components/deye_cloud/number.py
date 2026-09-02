"""Number platform for Deye Cloud set-points."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent, UnitOfPower
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
    entities: list[NumberEntity] = []
    for sn in coordinator.device_sns:
        entities.append(DeyeMaxChargeCurrent(coordinator, sn))
        entities.append(DeyeMaxDischargeCurrent(coordinator, sn))
        entities.append(DeyeMaxSellPower(coordinator, sn))
        entities.append(DeyeLowBatterySoc(coordinator, sn))
    async_add_entities(entities)


class _DeyeNumber(DeyeDeviceEntity, NumberEntity):
    """Base set-point number; reads current value from config, writes via API."""

    _attr_mode = NumberMode.BOX
    _config_key: str = ""
    _slug: str = ""

    def __init__(self, coordinator: DeyeCloudCoordinator, device_sn: str) -> None:
        super().__init__(coordinator, device_sn)
        self._attr_unique_id = f"{device_sn}_{self._slug}"
        self.entity_id = f"number.{ID_PREFIX}_{self._slug}"

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
            _LOGGER.error("Failed to set %s: %s", self._attr_name, err)
            return
        await self.coordinator.async_request_refresh()

    async def _apply(self, value: int) -> None:
        raise NotImplementedError


class DeyeMaxChargeCurrent(_DeyeNumber):
    _attr_name = "Max Charge Current"
    _attr_icon = "mdi:current-dc"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_max_value = 250
    _attr_native_step = 1
    _config_key = "maxChargeCurrent"
    _slug = "max_charge_current"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "MAX_CHARGE_CURRENT", value
        )


class DeyeMaxDischargeCurrent(_DeyeNumber):
    _attr_name = "Max Discharge Current"
    _attr_icon = "mdi:current-dc"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 0
    _attr_native_max_value = 250
    _attr_native_step = 1
    _config_key = "maxDischargeCurrent"
    _slug = "max_discharge_current"

    async def _apply(self, value: int) -> None:
        await self.coordinator.client.async_set_battery_param(
            self._device_sn, "MAX_DISCHARGE_CURRENT", value
        )


class DeyeMaxSellPower(_DeyeNumber):
    _attr_name = "Max Sell Power"
    _attr_icon = "mdi:transmission-tower-export"
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

    _attr_name = "Low Battery SOC"
    _attr_icon = "mdi:battery-low"
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
