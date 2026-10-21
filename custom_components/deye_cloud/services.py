"""Services for Deye Cloud (time-of-use control)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .api import DeyeCloudApiError, _normalize_tou_time
from .const import DOMAIN
from .entity import rejected
from .tou import TOU_SLOT_COUNT, effective_tou_slots, set_pending_tou

SERVICE_SET_TOU_SCHEDULE = "set_tou_schedule"
SERVICE_SET_TOU_DAYS = "set_tou_days"

WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

def _tou_time(value: object) -> str:
    """Slot time as given; the update endpoint only takes 5-minute steps."""
    text = cv.string(value)
    try:
        minute = int(_normalize_tou_time(text)[3:])
    except ValueError as err:
        raise vol.Invalid(f"invalid time {text!r}, expected HH:MM") from err
    if minute % 5:
        raise vol.Invalid(f"time {text!r} must be on a 5-minute step (e.g. 06:05)")
    return text


# Field names mirror the inverter's Time Of Use screen (Time / Power / Batt /
# Grid Charge / Gen) so they are familiar to anyone who set these on the unit.
# A field left out keeps the current value, including edits that have not read
# back yet, so a partial schedule never undoes a recent change.
_SLOT = vol.Schema(
    {
        vol.Optional("time"): _tou_time,  # "HH:MM"
        vol.Optional("power"): vol.Coerce(int),
        vol.Optional("batt"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("voltage"): vol.Coerce(int),
        vol.Optional("grid_charge"): cv.boolean,
        vol.Optional("gen"): cv.boolean,
        vol.Optional("sell"): cv.boolean,
    }
)

_API_FIELDS = {
    "time": "time",
    "power": "power",
    "batt": "soc",
    "voltage": "voltage",
    "grid_charge": "enableGridCharge",
    "gen": "enableGeneration",
    "sell": "enableSell",
}
_REQUIRED = ("time", "power", "batt", "grid_charge", "gen")

_SET_TOU_SCHEMA = vol.Schema(
    {
        vol.Optional("device_sn"): cv.string,
        vol.Optional("device_id"): cv.string,
        # The update endpoint takes the full table, all six slots in order.
        vol.Required("slots"): vol.All(cv.ensure_list, [_SLOT], vol.Length(min=6, max=6)),
    }
)

_SET_TOU_DAYS_SCHEMA = vol.Schema(
    {
        vol.Optional("device_sn"): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
    }
)


def _device_sn(hass: HomeAssistant, device_id: str) -> str:
    """The inverter serial behind a device registry id."""
    device = dr.async_get(hass).async_get(device_id)
    for domain, ident in device.identifiers if device else ():
        if domain == DOMAIN and not ident.startswith("station_"):
            return ident
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_device",
        translation_placeholders={"device_sn": device_id},
    )


def _resolve(hass: HomeAssistant, device_sn: str | None):
    """Return (coordinator, device_sn); pick the only device if none given."""
    devices = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = entry.runtime_data
        for sn in coordinator.device_sns:
            devices.append((coordinator, sn))
    if device_sn:
        for coordinator, sn in devices:
            if sn == device_sn:
                return coordinator, sn
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_device",
            translation_placeholders={"device_sn": device_sn},
        )
    if len(devices) == 1:
        return devices[0]
    if not devices:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_devices"
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="device_sn_required"
    )


def _to_items(slots: list[dict]) -> list[dict]:
    """Map the fields given in each slot to the API's names."""
    return [
        {_API_FIELDS[field]: value for field, value in slot.items() if field in _API_FIELDS}
        for slot in slots
    ]


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_TOU_SCHEDULE):
        return

    async def _set_tou_schedule(call: ServiceCall) -> None:
        device_sn = call.data.get("device_sn")
        if device_id := call.data.get("device_id"):
            device_sn = _device_sn(hass, device_id)
        coordinator, sn = _resolve(hass, device_sn)
        changes = _to_items(call.data["slots"])
        async with coordinator.tou_lock:
            current = effective_tou_slots(coordinator, sn)
            if len(current) < TOU_SLOT_COUNT:
                if not all(all(f in s for f in _REQUIRED) for s in call.data["slots"]):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN, translation_key="tou_not_read"
                    )
                current = [{} for _ in range(TOU_SLOT_COUNT)]
            items = [{**slot, **change} for slot, change in zip(current, changes, strict=False)]
            try:
                await coordinator.client.async_set_tou(sn, items)
            except DeyeCloudApiError as err:
                raise rejected("Time Of Use schedule", err) from err
            # /config/tou reads times back as HHMM.
            set_pending_tou(
                coordinator,
                sn,
                [{**i, "time": _normalize_tou_time(i["time"]).replace(":", "")} for i in items],
            )
        # Entities show pending values, so let them redraw before the read-back.
        coordinator.async_update_listeners()
        await coordinator.async_request_config_refresh()

    async def _set_tou_days(call: ServiceCall) -> None:
        coordinator, sn = _resolve(hass, call.data.get("device_sn"))
        try:
            await coordinator.client.async_set_tou_switch(
                sn, call.data["enabled"], call.data.get("days")
            )
        except DeyeCloudApiError as err:
            raise rejected("Time Of Use days", err) from err
        coordinator.set_pending(sn, "touAction", "on" if call.data["enabled"] else "off")
        await coordinator.async_request_config_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TOU_SCHEDULE, _set_tou_schedule, schema=_SET_TOU_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TOU_DAYS, _set_tou_days, schema=_SET_TOU_DAYS_SCHEMA
    )
