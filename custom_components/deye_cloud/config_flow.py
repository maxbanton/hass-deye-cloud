"""Config flow for Deye Cloud."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeyeCloudClient
from .const import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_CONFIG_INTERVAL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONFIG_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_CONFIG_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_CONFIG_INTERVAL,
    MIN_SCAN_INTERVAL,
    REGIONS,
)


class DeyeCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Deye Cloud config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DeyeCloudOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_APP_ID]}_{user_input[CONF_EMAIL]}"
            )
            self._abort_if_unique_id_configured()

            base_url = REGIONS[user_input[CONF_REGION]]["base_url"]
            client = DeyeCloudClient(
                base_url=base_url,
                app_id=user_input[CONF_APP_ID],
                app_secret=user_input[CONF_APP_SECRET],
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )
            if await client.async_test_connection():
                return self.async_create_entry(title="Deye Cloud", data=user_input)
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_REGION, default="eu"): vol.In(
                    {key: value["name"] for key, value in REGIONS.items()}
                ),
                vol.Required(CONF_APP_ID): str,
                vol.Required(CONF_APP_SECRET): str,
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )


class DeyeCloudOptionsFlow(OptionsFlow):
    """Polling options.

    The Deye Cloud API is quota limited and loggers only upload every 3-5
    minutes, so these let a user trade freshness against API calls.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_CONFIG_INTERVAL,
                    default=options.get(CONF_CONFIG_INTERVAL, DEFAULT_CONFIG_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_CONFIG_INTERVAL, max=MAX_CONFIG_INTERVAL),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
