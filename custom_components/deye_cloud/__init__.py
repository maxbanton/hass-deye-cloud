"""The Deye Cloud integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

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
    REGIONS,
)
from .coordinator import DeyeCloudCoordinator
from .services import async_register_services

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME, Platform.SELECT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type DeyeCloudConfigEntry = ConfigEntry[DeyeCloudCoordinator]


def build_client(hass: HomeAssistant, data: dict) -> DeyeCloudClient:
    """Build an API client from config entry (or config flow) data."""
    region = data.get(CONF_REGION, "eu")
    return DeyeCloudClient(
        base_url=REGIONS.get(region, REGIONS["eu"])["base_url"],
        app_id=data[CONF_APP_ID],
        app_secret=data[CONF_APP_SECRET],
        email=data[CONF_EMAIL],
        password=data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions, which exist without a config entry."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DeyeCloudConfigEntry) -> bool:
    """Set up Deye Cloud from a config entry."""
    coordinator = DeyeCloudCoordinator(
        hass,
        build_client(hass, dict(entry.data)),
        scan_interval=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        config_interval=entry.options.get(CONF_CONFIG_INTERVAL, DEFAULT_CONFIG_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    # Entities are created from what the first poll returns. If the cloud listed
    # devices but failed to return their data, setting up now would leave every
    # device entity unavailable until a manual reload, so retry setup instead.
    if coordinator.data["devices"] and not coordinator.device_sns:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="no_device_data"
        )

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: DeyeCloudConfigEntry) -> None:
    """Reload the entry when its polling options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DeyeCloudConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
