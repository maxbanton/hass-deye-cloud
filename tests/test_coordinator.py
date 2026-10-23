"""Polling failures as Home Assistant sees them, including rate-limit backoff."""
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.deye_cloud.api import DeyeCloudRateLimitError

from .test_init import _setup, patched_client


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def _poll(hass: HomeAssistant, entry, **overrides) -> None:
    with patched_client(**overrides):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_rate_limit_slows_polling_until_it_clears(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    limited = AsyncMock(side_effect=DeyeCloudRateLimitError("quota exceeded"))

    await _poll(hass, entry, async_get_device_latest=limited)
    assert not coordinator.last_update_success
    assert coordinator.update_interval.total_seconds() == 360
    await _poll(hass, entry, async_get_device_latest=limited)
    assert coordinator.update_interval.total_seconds() == 720

    await _poll(hass, entry)
    assert coordinator.last_update_success
    assert coordinator.update_interval.total_seconds() == 180


async def test_rate_limit_honours_retry_after(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    await _poll(
        hass,
        entry,
        async_get_station_latest=AsyncMock(
            side_effect=DeyeCloudRateLimitError("HTTP 429", retry_after=1200)
        ),
    )

    assert entry.runtime_data.update_interval.total_seconds() == 1200

