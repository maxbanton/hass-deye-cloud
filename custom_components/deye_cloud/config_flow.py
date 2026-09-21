"""Config flow for Deye Cloud."""
from __future__ import annotations

from collections.abc import Mapping
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


async def _async_credentials_work(hass, data: dict[str, Any]) -> bool:
    """Return True if the given credentials authenticate against Deye Cloud."""
    client = DeyeCloudClient(
        base_url=REGIONS[data[CONF_REGION]]["base_url"],
        app_id=data[CONF_APP_ID],
        app_secret=data[CONF_APP_SECRET],
        email=data[CONF_EMAIL],
        password=data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    return await client.async_test_connection()


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

            if await _async_credentials_work(self.hass, user_input):
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the API rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials again and update the entry in place.

        The account password and the developer app secret are the two things
        that change in practice; the account email and region stay as they are.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if await _async_credentials_work(self.hass, {**entry.data, **user_input}):
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
            errors["base"] = "invalid_auth"

        schema = vol.Schema(
            {
                vol.Required(CONF_APP_SECRET, default=entry.data[CONF_APP_SECRET]): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
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
