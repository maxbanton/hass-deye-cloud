"""Config flow for Deye Cloud."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeyeCloudClient
from .const import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REGION,
    DOMAIN,
    REGIONS,
)


class DeyeCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Deye Cloud config flow."""

    VERSION = 1

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
