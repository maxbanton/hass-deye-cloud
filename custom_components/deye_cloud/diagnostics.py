"""Diagnostics, including a fresh read of what the cloud reports per inverter.

The probe re-reads measure points and every config endpoint, also the ones the
poller skips for an inverter without a battery, so a report shows exactly what
the cloud returns for a model nobody here owns. Credentials, serials and the
plant's location are redacted because users share this file publicly.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .const import CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD
from .discovery import has_battery, is_inverter

TO_REDACT = {
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_EMAIL,
    CONF_PASSWORD,
    "deviceSn",
    "deviceId",
    "stationId",
    "id",
    "name",
    "ownerName",
    "contactPhone",
    "locationAddress",
    "locationLat",
    "locationLng",
}


async def _probe(request: Awaitable[Any]) -> Any:
    try:
        return await request
    except DeyeCloudApiError as err:
        return {"error": str(err)}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeyeCloudConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    client = coordinator.client
    data = coordinator.data or {}

    devices = []
    for sn, device in data.get("devices", {}).items():
        report: dict[str, Any] = {
            "info": device.get("info", {}),
            "measure_points": device.get("measure_points"),
            "has_battery": has_battery(device),
            "data": device.get("data", {}),
            "units": device.get("units", {}),
            "config": device.get("config", {}),
        }
        if is_inverter(device):
            device_type = device["info"]["deviceType"]
            report["probe"] = {
                "measure_points": await _probe(
                    client.async_get_measure_points(sn, device_type)
                ),
                "config_system": await _probe(client.async_get_system_config(sn)),
                "config_battery": await _probe(client.async_get_battery_config(sn)),
                "config_tou": await _probe(client.async_get_tou(sn)),
                "config_dynamic": await _probe(client.async_get_dynamic_config(sn)),
            }
        devices.append(report)

    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "stations": list(data.get("stations", {}).values()),
            "devices": devices,
        },
        TO_REDACT,
    )
