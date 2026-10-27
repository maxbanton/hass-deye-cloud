"""Diagnostics tests."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.deye_cloud.api import DeyeCloudApiError

from .test_discovery import HYBRID
from .test_init import _setup, patched_client

diagnostics_helper = pytest.importorskip(
    "pytest_homeassistant_custom_component.components.diagnostics",
    reason="diagnostics test helper not available in this test framework release",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def test_diagnostics_probe_every_config_endpoint(hass, hass_client) -> None:
    entry = await _setup(hass, **HYBRID)
    with patched_client(**HYBRID):
        diagnostics = await diagnostics_helper.get_diagnostics_for_config_entry(
            hass, hass_client, entry
        )

    (device,) = diagnostics["devices"]
    assert device["has_battery"] is True
    assert device["measure_points"] == ["SOC", "BatteryPower"]
    assert device["probe"]["config_battery"]["maxChargeCurrent"] == 40
    assert len(device["probe"]["config_tou"]["timeUseSettingItems"]) == 6
    assert device["probe"]["config_dynamic"]["gridChargeAmpere"] == 30


async def test_diagnostics_redact_credentials_and_serials(hass, hass_client) -> None:
    entry = await _setup(hass, **HYBRID)
    with patched_client(**HYBRID):
        diagnostics = await diagnostics_helper.get_diagnostics_for_config_entry(
            hass, hass_client, entry
        )

    text = str(diagnostics)
    for secret in ("app-secret", "hunter2", "user@example.com", "SN1", "Home"):
        assert secret not in text


async def test_diagnostics_report_an_endpoint_that_fails(hass, hass_client) -> None:
    entry = await _setup(hass, **HYBRID)
    failing = {**HYBRID, "async_get_tou": AsyncMock(side_effect=DeyeCloudApiError("offline"))}
    with patched_client(**failing):
        diagnostics = await diagnostics_helper.get_diagnostics_for_config_entry(
            hass, hass_client, entry
        )

    (device,) = diagnostics["devices"]
    assert device["probe"]["config_tou"] == {"error": "offline"}
    assert device["probe"]["config_battery"]["maxChargeCurrent"] == 40
