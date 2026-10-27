"""Actions: picking the inverter, Time Of Use days and a table not read yet."""
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.deye_cloud.api import DeyeCloudApiError
from custom_components.deye_cloud.const import DOMAIN
from custom_components.deye_cloud.services import async_register_services

from .test_init import _setup, patched_client

FULL_TABLE = [
    {"time": f"{h:02d}:00", "power": 2000, "batt": 60, "grid_charge": False, "gen": False}
    for h in (1, 5, 9, 13, 17, 21)
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def test_days_action_switches_the_schedule_for_those_days(hass: HomeAssistant) -> None:
    await _setup(hass)
    switch = AsyncMock(return_value=None)

    with patched_client(async_set_tou_switch=switch):
        await hass.services.async_call(
            DOMAIN,
            "set_tou_days",
            {"enabled": False, "days": ["MONDAY", "FRIDAY"]},
            blocking=True,
        )

    switch.assert_awaited_once_with("SN1", False, ["MONDAY", "FRIDAY"])
    assert hass.states.get("switch.deye_maintain_battery_level").state == "off"


async def test_failed_days_action_raises(hass: HomeAssistant) -> None:
    await _setup(hass)

    with (
        patched_client(async_set_tou_switch=AsyncMock(side_effect=DeyeCloudApiError("offline"))),
        pytest.raises(HomeAssistantError, match="Time Of Use days"),
    ):
        await hass.services.async_call(
            DOMAIN, "set_tou_days", {"enabled": True}, blocking=True
        )
    assert hass.states.get("switch.deye_maintain_battery_level").state == "on"


async def test_unknown_serial_is_rejected(hass: HomeAssistant) -> None:
    await _setup(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_tou_days", {"device_sn": "SN9", "enabled": True}, blocking=True
        )


async def test_actions_need_a_loaded_inverter(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_tou_days", {"enabled": True}, blocking=True)
    assert err.value.translation_key == "no_devices"


async def test_serial_is_required_with_several_inverters(hass: HomeAssistant) -> None:
    stations = [
        {
            "id": "1",
            "name": "Home",
            "deviceListItems": [
                {"deviceSn": "SN1", "deviceType": "INVERTER"},
                {"deviceSn": "SN2", "deviceType": "INVERTER"},
            ],
        }
    ]
    reading = {"data": {"SOC": 80}, "units": {"SOC": "%"}}
    await _setup(
        hass,
        async_get_stations_with_devices=AsyncMock(return_value=stations),
        async_get_device_latest=AsyncMock(return_value={"SN1": reading, "SN2": reading}),
    )
    switch = AsyncMock(return_value=None)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_tou_days", {"enabled": True}, blocking=True)
    assert err.value.translation_key == "device_sn_required"

    with patched_client(async_set_tou_switch=switch):
        await hass.services.async_call(
            DOMAIN, "set_tou_days", {"device_sn": "SN2", "enabled": True}, blocking=True
        )
    switch.assert_awaited_once_with("SN2", True, None)


async def test_full_table_can_be_sent_before_the_first_read(hass: HomeAssistant) -> None:
    await _setup(hass)
    set_tou = AsyncMock(return_value=None)

    with patched_client(async_set_tou=set_tou):
        await hass.services.async_call(
            DOMAIN, "set_tou_schedule", {"slots": FULL_TABLE}, blocking=True
        )

    sent = set_tou.await_args.args[1]
    assert [s["time"] for s in sent] == ["01:00", "05:00", "09:00", "13:00", "17:00", "21:00"]
    assert {s["soc"] for s in sent} == {60}


async def test_actions_are_registered_once(hass: HomeAssistant) -> None:
    await _setup(hass)
    before = hass.services.async_services()[DOMAIN]

    async_register_services(hass)

    assert hass.services.async_services()[DOMAIN] == before


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"enabled": True, "power": 3000}, ("SN1", True, 3000)),
        ({"enabled": False}, ("SN1", False, None)),
    ],
)
async def test_peak_shaving_action_sends_only_what_was_given(
    hass: HomeAssistant, data, expected
) -> None:
    await _setup(hass)
    shaving = AsyncMock(return_value=None)

    with patched_client(async_set_peak_shaving=shaving):
        await hass.services.async_call(DOMAIN, "set_grid_peak_shaving", data, blocking=True)

    shaving.assert_awaited_once_with(*expected)


async def test_failed_peak_shaving_action_raises(hass: HomeAssistant) -> None:
    await _setup(hass)

    with (
        patched_client(async_set_peak_shaving=AsyncMock(side_effect=DeyeCloudApiError("offline"))),
        pytest.raises(HomeAssistantError, match="Grid peak shaving"),
    ):
        await hass.services.async_call(
            DOMAIN, "set_grid_peak_shaving", {"enabled": True}, blocking=True
        )


async def test_peak_shaving_limit_cannot_be_negative(hass: HomeAssistant) -> None:
    await _setup(hass)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_grid_peak_shaving", {"enabled": True, "power": -1}, blocking=True
        )
