"""Setup, unload and action-registration tests for the integration."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_cloud.api import DeyeCloudApiError, DeyeCloudAuthError
from custom_components.deye_cloud.const import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_CONFIG_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

ENTRY_DATA = {
    CONF_REGION: "eu",
    CONF_APP_ID: "app-id",
    CONF_APP_SECRET: "app-secret",
    CONF_EMAIL: "user@example.com",
    CONF_PASSWORD: "hunter2",
}

STATIONS = [
    {
        "id": "1",
        "name": "Home",
        "deviceListItems": [{"deviceSn": "SN1", "deviceType": "INVERTER"}],
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


def patched_client(**overrides):
    """Patch the API client so no network calls happen during setup."""
    defaults = {
        "async_get_stations_with_devices": AsyncMock(return_value=STATIONS),
        "async_get_station_latest": AsyncMock(return_value={"generationPower": 1200}),
        "async_get_device_latest": AsyncMock(
            return_value={
                "SN1": {
                    "data": {"SOC": 80, "InverterOutputFrequency": 50},
                    "units": {"SOC": "%", "InverterOutputFrequency": "Hz"},
                }
            }
        ),
        "async_get_system_config": AsyncMock(return_value={"energyPattern": "LOAD_FIRST"}),
        "async_get_battery_config": AsyncMock(return_value={"maxChargeCurrent": 40}),
        "async_get_tou": AsyncMock(
            return_value={"touAction": "on", "timeUseSettingItems": []}
        ),
    }
    defaults.update(overrides)
    return patch.multiple(
        "custom_components.deye_cloud.api.DeyeCloudClient", **defaults
    )


async def _setup(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="app-id_user")
    entry.add_to_hass(hass)
    with patched_client(**overrides):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_creates_entities_and_runtime_data(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.device_sns == ["SN1"]
    assert hass.states.get("sensor.deye_soc").state == "80.0"
    # Secondary measure points are discovered but stay disabled until wanted.
    registry = er.async_get(hass)
    entry_id = registry.async_get("sensor.deye_inverter_output_frequency")
    assert entry_id is not None
    assert entry_id.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_actions_are_registered(hass: HomeAssistant) -> None:
    await _setup(hass)

    assert hass.services.has_service(DOMAIN, "set_tou_schedule")
    assert hass.services.has_service(DOMAIN, "set_tou_days")


async def test_unload_releases_the_entry(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_the_api_is_down(hass: HomeAssistant) -> None:
    entry = await _setup(
        hass,
        async_get_stations_with_devices=AsyncMock(
            side_effect=DeyeCloudApiError("cloud offline")
        ),
    )
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_credentials_start_a_reauth_flow(hass: HomeAssistant) -> None:
    entry = await _setup(
        hass,
        async_get_stations_with_devices=AsyncMock(
            side_effect=DeyeCloudAuthError("token rejected")
        ),
    )

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_options_change_reloads_with_the_new_interval(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    with patched_client():
        hass.config_entries.async_update_entry(
            entry, options={CONF_SCAN_INTERVAL: 600, CONF_CONFIG_INTERVAL: 30}
        )
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 600
