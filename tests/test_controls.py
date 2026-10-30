"""Inverter controls: what each one sends, what it shows and how a refusal surfaces."""
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deye_cloud.api import (
    DeyeCloudApiError,
    DeyeCloudBusyError,
    DeyeCloudOfflineError,
    DeyeCloudPermissionError,
)
from custom_components.deye_cloud.const import DOMAIN

from .test_discovery import HYBRID
from .test_init import ENTRY_DATA, patched_client

OFFLINE = DeyeCloudApiError("offline")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def writes() -> dict[str, AsyncMock]:
    return {
        name: AsyncMock(return_value=None)
        for name in (
            "async_set_battery_param",
            "async_set_power_param",
            "async_set_energy_pattern",
            "async_set_solar_sell",
            "async_set_tou_switch",
            "async_set_tou",
        )
    }


@pytest.fixture
async def entry(hass: HomeAssistant, writes):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="app-id_user")
    entry.add_to_hass(hass)
    # Most controls are disabled by default; these tests need every one of them.
    with (
        patched_client(**HYBRID, **writes),
        patch(
            "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry


def _device(entry) -> dict:
    return entry.runtime_data.data["devices"]["SN1"]


async def _cloud_reports(hass: HomeAssistant, entry, **config) -> None:
    """Change what the last poll read and let the entities redraw."""
    _device(entry)["config"].update(config)
    entry.runtime_data.async_update_listeners()
    await hass.async_block_till_done()


async def _call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )


# --- set-points --------------------------------------------------------------


@pytest.mark.parametrize(
    "entity_id,write,param",
    [
        ("number.deye_max_charge_current", "async_set_battery_param", "MAX_CHARGE_CURRENT"),
        ("number.deye_max_discharge_current", "async_set_battery_param", "MAX_DISCHARGE_CURRENT"),
        ("number.deye_grid_charge_current", "async_set_battery_param", "GRID_CHARGE_AMPERE"),
        ("number.deye_low_battery_soc", "async_set_battery_param", "BATT_LOW"),
        ("number.deye_max_sell_power", "async_set_power_param", "MAX_SELL_POWER"),
    ],
)
async def test_set_point_is_sent_as_its_inverter_parameter(
    hass: HomeAssistant, entry, writes, entity_id, write, param
) -> None:
    await _call(hass, "number", "set_value", entity_id, value=20)

    writes[write].assert_awaited_once_with("SN1", param, 20)


async def test_refused_set_point_names_the_value(hass: HomeAssistant, entry, writes) -> None:
    writes["async_set_battery_param"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="= 55: offline"):
        await _call(hass, "number", "set_value", "number.deye_max_charge_current", value=55)
    assert hass.states.get("number.deye_max_charge_current").state == "40.0"


async def test_unreadable_set_point_shows_unknown(hass: HomeAssistant, entry) -> None:
    await _cloud_reports(hass, entry, maxChargeCurrent="n/a")

    assert hass.states.get("number.deye_max_charge_current").state == "unknown"


# --- energy pattern ----------------------------------------------------------


async def test_energy_pattern_shows_the_new_choice_before_read_back(
    hass: HomeAssistant, entry, writes
) -> None:
    await _call(
        hass, "select", "select_option", "select.deye_energy_pattern", option="Battery First"
    )

    writes["async_set_energy_pattern"].assert_awaited_once_with("SN1", "BATTERY_FIRST")
    assert hass.states.get("select.deye_energy_pattern").state == "Battery First"


async def test_refused_energy_pattern_keeps_the_current_one(
    hass: HomeAssistant, entry, writes
) -> None:
    writes["async_set_energy_pattern"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="offline"):
        await _call(
            hass, "select", "select_option", "select.deye_energy_pattern", option="Battery First"
        )
    assert hass.states.get("select.deye_energy_pattern").state == "Load First"


@pytest.mark.parametrize(
    "error,message",
    [
        (DeyeCloudBusyError("busy"), "still carrying out another command"),
        (DeyeCloudPermissionError("denied"), "no permission to control this inverter"),
        (DeyeCloudOfflineError("offline"), "inverter is offline"),
    ],
)
async def test_busy_or_forbidden_inverter_says_so(
    hass: HomeAssistant, entry, writes, error, message
) -> None:
    writes["async_set_energy_pattern"].side_effect = error

    with pytest.raises(HomeAssistantError, match=message):
        await _call(
            hass, "select", "select_option", "select.deye_energy_pattern", option="Battery First"
        )


# --- switches ----------------------------------------------------------------


async def test_solar_sell_shows_the_read_back_and_then_the_command(
    hass: HomeAssistant, entry, writes
) -> None:
    state = hass.states.get("switch.deye_solar_sell")
    assert state.state == "off"
    assert "assumed_state" not in state.attributes

    await _call(hass, "switch", "turn_on", "switch.deye_solar_sell")

    writes["async_set_solar_sell"].assert_awaited_once_with("SN1", True)
    assert hass.states.get("switch.deye_solar_sell").state == "on"
    await _cloud_reports(hass, entry, solarSellAction="on")
    assert hass.states.get("switch.deye_solar_sell").state == "on"


async def test_solar_sell_without_read_back_reflects_the_last_command(
    hass: HomeAssistant, entry, writes
) -> None:
    await _cloud_reports(hass, entry, solarSellAction=None)
    state = hass.states.get("switch.deye_solar_sell")
    assert state.state == "unknown"
    assert state.attributes["assumed_state"] is True

    await _call(hass, "switch", "turn_on", "switch.deye_solar_sell")
    assert hass.states.get("switch.deye_solar_sell").state == "on"
    await _call(hass, "switch", "turn_off", "switch.deye_solar_sell")
    assert hass.states.get("switch.deye_solar_sell").state == "off"

    assert [c.args for c in writes["async_set_solar_sell"].await_args_list] == [
        ("SN1", True),
        ("SN1", False),
    ]


async def test_refused_solar_sell_keeps_its_state(hass: HomeAssistant, entry, writes) -> None:
    writes["async_set_solar_sell"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="offline"):
        await _call(hass, "switch", "turn_on", "switch.deye_solar_sell")
    assert hass.states.get("switch.deye_solar_sell").state == "off"


async def test_time_of_use_switch_shows_the_command_before_read_back(
    hass: HomeAssistant, entry, writes
) -> None:
    await _call(hass, "switch", "turn_off", "switch.deye_maintain_battery_level")
    assert hass.states.get("switch.deye_maintain_battery_level").state == "off"
    await _call(hass, "switch", "turn_on", "switch.deye_maintain_battery_level")
    assert hass.states.get("switch.deye_maintain_battery_level").state == "on"

    assert [c.args for c in writes["async_set_tou_switch"].await_args_list] == [
        ("SN1", False),
        ("SN1", True),
    ]


async def test_time_of_use_switch_without_a_state_shows_unknown(
    hass: HomeAssistant, entry
) -> None:
    await _cloud_reports(hass, entry, touAction=None)

    assert hass.states.get("switch.deye_maintain_battery_level").state == "unknown"


async def test_slot_switches_edit_their_own_slot(hass: HomeAssistant, entry, writes) -> None:
    await _call(hass, "switch", "turn_on", "switch.deye_tou2_grid_charge")
    await _call(hass, "switch", "turn_off", "switch.deye_tou2_gen")
    await _call(hass, "switch", "turn_on", "switch.deye_tou3_gen")

    sent = writes["async_set_tou"].await_args_list[-1].args[1]
    assert [s["enableGridCharge"] for s in sent[:3]] == [False, True, False]
    assert [s["enableGeneration"] for s in sent[:3]] == [False, False, True]
    assert hass.states.get("switch.deye_tou2_grid_charge").state == "on"
    assert hass.states.get("switch.deye_tou3_gen").state == "on"


async def test_refused_slot_switch_raises(hass: HomeAssistant, entry, writes) -> None:
    writes["async_set_tou"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="offline"):
        await _call(hass, "switch", "turn_on", "switch.deye_tou1_grid_charge")
    assert hass.states.get("switch.deye_tou1_grid_charge").state == "off"


# --- slot numbers and times --------------------------------------------------


async def test_refused_slot_value_names_the_value(hass: HomeAssistant, entry, writes) -> None:
    writes["async_set_tou"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="= 3500: offline"):
        await _call(hass, "number", "set_value", "number.deye_tou1_power", value=3500)
    assert hass.states.get("number.deye_tou1_power").state == "3000.0"


async def test_refused_slot_time_raises(hass: HomeAssistant, entry, writes) -> None:
    writes["async_set_tou"].side_effect = OFFLINE

    with pytest.raises(HomeAssistantError, match="offline"):
        await _call(hass, "time", "set_value", "time.deye_tou2_time", time="06:00")
    assert hass.states.get("time.deye_tou2_time").state == "05:00:00"


async def test_slot_values_the_cloud_cannot_make_sense_of_show_unknown(
    hass: HomeAssistant, entry
) -> None:
    slots = [dict(slot) for slot in _device(entry)["config"]["timeUseSettingItems"]]
    slots[0].update(soc="n/a", time="ab:cd", enableGeneration=None)
    slots[1].update(time="5:30")
    await _cloud_reports(hass, entry, timeUseSettingItems=slots)

    assert hass.states.get("number.deye_tou1_soc").state == "unknown"
    assert hass.states.get("time.deye_tou1_time").state == "unknown"
    assert hass.states.get("switch.deye_tou1_gen").state == "unknown"
    assert hass.states.get("time.deye_tou2_time").state == "05:30:00"


async def test_first_slot_time_is_checked_only_against_the_next(
    hass: HomeAssistant, entry, writes
) -> None:
    await _call(hass, "time", "set_value", "time.deye_tou1_time", time="00:00")

    assert writes["async_set_tou"].await_args_list[-1].args[1][0]["time"] == "0000"
