"""Time Of Use writes, pending values and command errors."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_cloud.api import DeyeCloudApiError
from custom_components.deye_cloud.const import DOMAIN

from .test_init import ENTRY_DATA, patched_client


def _slots(soc1: int = 90, soc2: int = 30) -> list[dict]:
    times = ["0100", "0500", "0900", "1300", "1700", "2100"]
    slots = [
        {"time": t, "power": 3000, "soc": 50, "voltage": 52,
         "enableGridCharge": False, "enableGeneration": False}
        for t in times
    ]
    slots[0]["soc"] = soc1
    slots[1]["soc"] = soc2
    return slots


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def get_tou():
    return AsyncMock(return_value={"touAction": "on", "timeUseSettingItems": _slots()})


@pytest.fixture
def set_tou():
    return AsyncMock(return_value=None)


@pytest.fixture
async def entry(hass: HomeAssistant, get_tou, set_tou):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="app-id_user")
    entry.add_to_hass(hass)
    with patched_client(
        async_get_tou=get_tou,
        async_set_tou=set_tou,
        async_set_tou_switch=AsyncMock(side_effect=DeyeCloudApiError("offline")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


async def _set_soc(hass: HomeAssistant, slot: int, value: int) -> None:
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": f"number.deye_tou{slot}_soc", "value": value},
        blocking=True,
    )


async def test_second_edit_keeps_the_first_before_read_back(
    hass: HomeAssistant, entry, set_tou
) -> None:
    await _set_soc(hass, 1, 70)
    # The cloud still reads back the old table here.
    await _set_soc(hass, 2, 40)

    sent = set_tou.await_args_list[-1].args[1]
    assert [s["soc"] for s in sent[:2]] == [70, 40]
    assert hass.states.get("number.deye_tou1_soc").state == "70.0"
    assert hass.states.get("number.deye_tou2_soc").state == "40.0"


async def test_action_table_replaces_pending_slot_edits(
    hass: HomeAssistant, entry, set_tou
) -> None:
    await _set_soc(hass, 1, 70)
    slots = [
        {"time": f"{h:02d}:00", "power": 2000, "batt": 60, "grid_charge": True, "gen": False}
        for h in (1, 5, 9, 13, 17, 21)
    ]
    await hass.services.async_call(
        DOMAIN, "set_tou_schedule", {"slots": slots}, blocking=True
    )
    await _set_soc(hass, 2, 40)

    sent = set_tou.await_args_list[-1].args[1]
    assert [s["soc"] for s in sent[:3]] == [60, 40, 60]
    assert sent[0]["enableGridCharge"] is True
    assert hass.states.get("time.deye_tou1_time").state == "01:00:00"


async def test_pending_value_drops_once_read_back_matches(
    hass: HomeAssistant, entry, get_tou
) -> None:
    await _set_soc(hass, 1, 70)
    get_tou.return_value = {"touAction": "on", "timeUseSettingItems": _slots(soc1=70)}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data._pending == {}
    assert hass.states.get("number.deye_tou1_soc").state == "70.0"


async def test_rejected_value_expires_after_a_later_read(
    hass: HomeAssistant, entry, get_tou
) -> None:
    long_ago = time.monotonic() - 600
    with patch("custom_components.deye_cloud.coordinator.time.monotonic", return_value=long_ago):
        await _set_soc(hass, 1, 70)
    assert hass.states.get("number.deye_tou1_soc").state == "70.0"

    # The inverter clamped the write; a read well after it is the real value.
    get_tou.return_value = {"touAction": "on", "timeUseSettingItems": _slots(soc1=65)}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("number.deye_tou1_soc").state == "65.0"


async def test_failed_switch_command_raises(hass: HomeAssistant, entry) -> None:
    with pytest.raises(HomeAssistantError, match="Time Of Use"):
        await hass.services.async_call(
            "switch", "turn_off",
            {"entity_id": "switch.deye_maintain_battery_level"},
            blocking=True,
        )
    assert hass.states.get("switch.deye_maintain_battery_level").state == "on"


async def test_one_call_for_every_slot_sets_them_all(hass: HomeAssistant, entry, set_tou) -> None:
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": [f"number.deye_tou{n}_soc" for n in range(1, 7)], "value": 25},
        blocking=True,
    )

    assert [s["soc"] for s in set_tou.await_args_list[-1].args[1]] == [25] * 6


async def test_concurrent_edits_on_different_platforms_both_apply(
    hass: HomeAssistant, entry, set_tou
) -> None:
    async def slow_write(*args):
        await asyncio.sleep(0.01)

    set_tou.side_effect = slow_write
    await asyncio.gather(
        _set_soc(hass, 1, 70),
        hass.services.async_call(
            "time", "set_value",
            {"entity_id": "time.deye_tou2_time", "time": "06:00"},
            blocking=True,
        ),
    )

    sent = set_tou.await_args_list[-1].args[1]
    assert sent[0]["soc"] == 70
    assert sent[1]["time"] == "0600"


async def test_failed_action_raises(hass: HomeAssistant, entry, set_tou) -> None:
    set_tou.side_effect = DeyeCloudApiError("offline")
    slots = [{"time": "01:00", "power": 2000, "batt": 60, "grid_charge": True, "gen": False}]
    with pytest.raises(HomeAssistantError, match="Time Of Use schedule"):
        await hass.services.async_call(
            DOMAIN, "set_tou_schedule", {"slots": slots}, blocking=True
        )
