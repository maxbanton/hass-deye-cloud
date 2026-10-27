"""Entities follow what the cloud reports for each inverter and station."""

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.deye_cloud.api import DeyeCloudApiError

from .test_init import _setup, patched_client

CLOUD_ERROR = DeyeCloudApiError("Connection error: 500")

SLOTS = [
    {
        "time": f"{hour:02d}00",
        "power": 3000,
        "soc": 30,
        "voltage": 49,
        "enableGridCharge": False,
        "enableGeneration": False,
    }
    for hour in (1, 5, 9, 13, 17, 21)
]

HYBRID = {
    "async_get_measure_points": AsyncMock(return_value=["SOC", "BatteryPower"]),
    "async_get_device_latest": AsyncMock(
        return_value={"SN1": {"data": {"SOC": 80, "BatteryPower": 10}, "units": {}}}
    ),
    "async_get_system_config": AsyncMock(
        return_value={
            "energyPattern": "LOAD_FIRST",
            "systemWorkMode": "ZERO_EXPORT_TO_LOAD",
            "maxSellPower": 5000,
        }
    ),
    "async_get_battery_config": AsyncMock(
        return_value={
            "maxChargeCurrent": 40,
            "maxDischargeCurrent": 100,
            "battLowCapacity": 15,
        }
    ),
    "async_get_tou": AsyncMock(
        return_value={"touAction": "on", "timeUseSettingItems": SLOTS}
    ),
    "async_get_dynamic_config": AsyncMock(
        return_value={
            "gridChargeAmpere": 30,
            "solarSellAction": "off",
            "touAction": "on",
        }
    ),
}

# A string inverter: no battery measure points, and the system config holds
# nothing but nulls.
ON_GRID = {
    "async_get_measure_points": AsyncMock(
        return_value=["DailyActiveProduction", "TotalDCInputPower"]
    ),
    "async_get_device_latest": AsyncMock(
        return_value={
            "SN1": {"data": {"DailyActiveProduction": 12.5}, "units": {}}
        }
    ),
    "async_get_station_latest": AsyncMock(
        return_value={
            "generationPower": 1200.0,
            "wirePower": 1150.0,
            "batteryPower": None,
            "batterySOC": None,
            "consumptionPower": None,
        }
    ),
    "async_get_system_config": AsyncMock(
        return_value={"energyPattern": None, "systemWorkMode": None, "maxSellPower": None}
    ),
    "async_get_battery_config": AsyncMock(side_effect=AssertionError("not read")),
    "async_get_tou": AsyncMock(side_effect=AssertionError("not read")),
    "async_get_dynamic_config": AsyncMock(side_effect=AssertionError("not read")),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


def _registered(hass: HomeAssistant, domain: str) -> set[str]:
    """Entity ids registered for a domain, including ones disabled by default."""
    return {
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.domain == domain
    }


async def test_hybrid_with_battery_gets_every_control(hass: HomeAssistant) -> None:
    await _setup(hass, **HYBRID)

    assert {
        "number.deye_max_charge_current",
        "number.deye_max_discharge_current",
        "number.deye_grid_charge_current",
        "number.deye_max_sell_power",
        "number.deye_low_battery_soc",
        "number.deye_tou1_soc",
        "number.deye_tou6_voltage",
    } <= _registered(hass, "number")
    assert {
        "switch.deye_solar_sell",
        "switch.deye_maintain_battery_level",
        "switch.deye_tou6_gen",
    } <= _registered(hass, "switch")
    assert _registered(hass, "select") == {"select.deye_energy_pattern"}
    assert len(_registered(hass, "time")) == 6


async def test_on_grid_inverter_gets_no_battery_entities(hass: HomeAssistant) -> None:
    await _setup(hass, **ON_GRID)

    for domain in ("number", "switch", "select", "time"):
        assert _registered(hass, domain) == set(), domain
    assert _registered(hass, "sensor") == {
        "sensor.deye_daily_active_production",
        "sensor.deye_station_generation_power",
        "sensor.deye_station_wire_power",
    }


async def test_unknown_measure_points_fall_back_to_live_keys(hass: HomeAssistant) -> None:
    await _setup(
        hass,
        **{
            **HYBRID,
            "async_get_measure_points": AsyncMock(side_effect=CLOUD_ERROR),
        },
    )

    assert "number.deye_max_charge_current" in _registered(hass, "number")


async def test_controls_appear_once_a_failed_config_read_recovers(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(
        hass,
        **{**HYBRID, "async_get_tou": AsyncMock(side_effect=CLOUD_ERROR)},
    )
    assert _registered(hass, "time") == set()

    with patched_client(**HYBRID):
        entry.runtime_data.poller.request_config_catchup()
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert len(_registered(hass, "time")) == 6



async def test_new_station_values_keep_a_generated_name(hass: HomeAssistant) -> None:
    await _setup(
        hass,
        async_get_station_latest=AsyncMock(
            return_value={"generationPower": 1200.0, "lastUpdateTime": 1760000000}
        ),
    )

    entry = er.async_get(hass).async_get("sensor.deye_station_last_update_time")
    assert entry.original_name == "Last Update Time (Station)"
    assert entry.translation_key is None


async def test_text_and_missing_readings_are_shown_as_they_are(hass: HomeAssistant) -> None:
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        entry = await _setup(
            hass,
            async_get_device_latest=AsyncMock(
                return_value={"SN1": {"data": {"SOC": 80, "RunStatus": "Normal"}, "units": {}}}
            ),
        )
    assert hass.states.get("sensor.deye_run_status").state == "Normal"

    entry.runtime_data.data["devices"]["SN1"]["data"]["RunStatus"] = None
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.deye_run_status").state == "unknown"
