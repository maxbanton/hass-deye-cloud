"""Tests for the config, options and reauthentication flows."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

USER_INPUT = {
    CONF_REGION: "eu",
    CONF_APP_ID: "app-id",
    CONF_APP_SECRET: "app-secret",
    CONF_EMAIL: "user@example.com",
    CONF_PASSWORD: "hunter2",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load this custom integration in tests."""
    return


def _connection(result: bool):
    return patch(
        "custom_components.deye_cloud.config_flow.DeyeCloudClient.async_test_connection",
        return_value=result,
    )


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with (
        _connection(True),
        patch("custom_components.deye_cloud.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Deye Cloud"
    assert result["data"] == USER_INPUT


async def test_user_flow_reports_bad_credentials(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _connection(False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # The form stays usable, so a corrected entry still goes through.
    with _connection(True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_account_cannot_be_added_twice(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=f"{USER_INPUT[CONF_APP_ID]}_{USER_INPUT[CONF_EMAIL]}",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _connection(True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="app-id_user")
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with (
        _connection(True),
        patch("custom_components.deye_cloud.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_APP_SECRET: "new-secret", CONF_PASSWORD: "new-password"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_APP_SECRET] == "new-secret"
    # Untouched fields survive the update.
    assert entry.data[CONF_EMAIL] == USER_INPUT[CONF_EMAIL]


async def test_reauth_rejects_wrong_credentials(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="app-id_user")
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    with _connection(False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_APP_SECRET: "still-wrong", CONF_PASSWORD: "still-wrong"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]


async def test_options_flow_stores_intervals(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="app-id_user")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 300, CONF_CONFIG_INTERVAL: 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 300, CONF_CONFIG_INTERVAL: 30}


@pytest.mark.parametrize(
    "bad_options",
    [
        {CONF_SCAN_INTERVAL: 5, CONF_CONFIG_INTERVAL: 15},
        {CONF_SCAN_INTERVAL: 99999, CONF_CONFIG_INTERVAL: 15},
        {CONF_SCAN_INTERVAL: 180, CONF_CONFIG_INTERVAL: 0},
    ],
)
async def test_options_flow_rejects_out_of_range(hass: HomeAssistant, bad_options) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id="app-id_user")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(result["flow_id"], bad_options)
