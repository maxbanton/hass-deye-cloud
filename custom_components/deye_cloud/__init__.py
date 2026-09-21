"""The Deye Cloud integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
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
    COORDINATOR,
    DEFAULT_CONFIG_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REGIONS,
)
from .coordinator import DeyeCloudCoordinator
from .services import async_register_services, async_unregister_services

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Cloud from a config entry."""
    region = entry.data.get(CONF_REGION, "eu")
    base_url = REGIONS.get(region, REGIONS["eu"])["base_url"]

    client = DeyeCloudClient(
        base_url=base_url,
        app_id=entry.data[CONF_APP_ID],
        app_secret=entry.data[CONF_APP_SECRET],
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )

    coordinator = DeyeCloudCoordinator(
        hass,
        client,
        scan_interval=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        config_interval=entry.options.get(CONF_CONFIG_INTERVAL, DEFAULT_CONFIG_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its polling options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            async_unregister_services(hass)
    return unload_ok
