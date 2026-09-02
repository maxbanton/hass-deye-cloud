"""Services for Deye Cloud (time-of-use control)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import COORDINATOR, DOMAIN

SERVICE_SET_TOU_SCHEDULE = "set_tou_schedule"
SERVICE_SET_TOU_DAYS = "set_tou_days"

WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

# Field names mirror the inverter's Time Of Use screen (Time / Power / Batt /
# Grid Charge / Gen) so they are familiar to anyone who set these on the unit.
_SLOT = vol.Schema(
    {
        vol.Required("time"): cv.string,  # "HH:MM"
        vol.Required("power"): vol.Coerce(int),
        vol.Required("batt"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("voltage"): vol.Coerce(int),
        vol.Required("grid_charge"): cv.boolean,
        vol.Required("gen"): cv.boolean,
        vol.Optional("sell"): cv.boolean,
    }
)

_SET_TOU_SCHEMA = vol.Schema(
    {
        vol.Optional("device_sn"): cv.string,
        vol.Required("slots"): vol.All(cv.ensure_list, [_SLOT], vol.Length(min=1, max=6)),
    }
)

_SET_TOU_DAYS_SCHEMA = vol.Schema(
    {
        vol.Optional("device_sn"): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
    }
)


def _resolve(hass: HomeAssistant, device_sn: str | None):
    """Return (client, device_sn); pick the only device if none given."""
    devices = []
    for entry in hass.data.get(DOMAIN, {}).values():
        coordinator = entry[COORDINATOR]
        for sn in coordinator.device_sns:
            devices.append((coordinator.client, sn))
    if device_sn:
        for client, sn in devices:
            if sn == device_sn:
                return client, sn
        raise vol.Invalid(f"Unknown device_sn: {device_sn}")
    if len(devices) == 1:
        return devices[0]
    raise vol.Invalid("Multiple Deye devices configured; specify device_sn")


def _to_items(slots: list[dict]) -> list[dict]:
    items = []
    for s in slots:
        item = {
            "time": s["time"],
            "power": s["power"],
            "soc": s["batt"],
            "enableGridCharge": s["grid_charge"],
            "enableGeneration": s["gen"],
        }
        if "voltage" in s:
            item["voltage"] = s["voltage"]
        if "sell" in s:
            item["enableSell"] = s["sell"]
        items.append(item)
    return items


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_TOU_SCHEDULE):
        return

    async def _set_tou_schedule(call: ServiceCall) -> None:
        client, sn = _resolve(call.hass, call.data.get("device_sn"))
        await client.async_set_tou(sn, _to_items(call.data["slots"]))

    async def _set_tou_days(call: ServiceCall) -> None:
        client, sn = _resolve(call.hass, call.data.get("device_sn"))
        await client.async_set_tou_switch(
            sn, call.data["enabled"], call.data.get("days")
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TOU_SCHEDULE, _set_tou_schedule, schema=_SET_TOU_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TOU_DAYS, _set_tou_days, schema=_SET_TOU_DAYS_SCHEMA
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    for service in (SERVICE_SET_TOU_SCHEDULE, SERVICE_SET_TOU_DAYS):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
