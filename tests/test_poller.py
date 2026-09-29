"""Tests for the tiered polling and rate-limit backoff."""
from __future__ import annotations

import pytest

from custom_components.deye_cloud.api import (
    DeyeCloudApiError,
    DeyeCloudRateLimitError,
    _is_rate_limit,
    _retry_after,
)
from custom_components.deye_cloud.const import INVENTORY_INTERVAL, STALE_DATA_TIMEOUT
from custom_components.deye_cloud.poller import DeyePoller, next_backoff


class FakeClient:
    """Counts calls so a test can assert what a poll actually costs."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.fail_inventory = False
        self.rate_limit_latest = False
        self.fail_latest = False

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    async def async_get_stations_with_devices(self):
        self._count("inventory")
        if self.fail_inventory:
            raise DeyeCloudApiError("boom")
        return [
            {
                "id": "1",
                "name": "Home",
                "deviceListItems": [{"deviceSn": "SN1", "deviceType": "INVERTER"}],
            }
        ]

    async def async_get_station_latest(self, station_id):
        self._count("station_latest")
        return {"generationPower": 1200}

    async def async_get_device_latest(self, device_sns):
        self._count("device_latest")
        if self.rate_limit_latest:
            raise DeyeCloudRateLimitError("slow down", 90)
        if self.fail_latest:
            raise DeyeCloudApiError("Connection error: 500")
        return {sn: {"data": {"Power": 1}, "units": {"Power": "W"}} for sn in device_sns}

    async def async_get_system_config(self, device_sn):
        self._count("config")
        return {"energyPattern": "LOAD_FIRST"}

    async def async_get_battery_config(self, device_sn):
        self._count("config")
        return {"maxChargeCurrent": 40}

    async def async_get_tou(self, device_sn):
        self._count("config")
        return {"touAction": "on", "timeUseSettingItems": []}


@pytest.fixture
def poller():
    return DeyePoller(FakeClient(), config_interval=15)


async def test_first_poll_reads_every_tier(poller):
    data = await poller.async_poll()
    calls = poller.client.calls
    assert calls == {
        "inventory": 1,
        "station_latest": 1,
        "device_latest": 1,
        "config": 3,
    }
    assert data["devices"]["SN1"]["config"]["maxChargeCurrent"] == 40
    assert poller.device_sns == ["SN1"]


async def test_second_poll_skips_inventory_and_config(poller):
    await poller.async_poll()
    await poller.async_poll()
    calls = poller.client.calls
    assert calls["inventory"] == 1          # hourly tier
    assert calls["config"] == 3             # slow tier
    assert calls["station_latest"] == 2     # fast tier
    assert calls["device_latest"] == 2      # fast tier


async def test_cached_config_still_served_when_tier_is_skipped(poller):
    await poller.async_poll()
    data = await poller.async_poll()
    assert data["devices"]["SN1"]["config"]["energyPattern"] == "LOAD_FIRST"


async def test_config_tier_fires_when_interval_elapsed(poller):
    await poller.async_poll()
    poller._configs_read -= 15 * 60
    await poller.async_poll()
    assert poller.client.calls["config"] == 6


async def test_inventory_tier_fires_when_interval_elapsed(poller):
    await poller.async_poll()
    poller._stations_read -= INVENTORY_INTERVAL
    await poller.async_poll()
    assert poller.client.calls["inventory"] == 2


async def test_write_triggers_config_catchup(poller):
    await poller.async_poll()
    poller._config_catchup = 3
    for _ in range(3):
        await poller.async_poll()
    assert poller.client.calls["config"] == 12  # 3 extra reads of 3 calls
    await poller.async_poll()
    assert poller.client.calls["config"] == 12  # burst over, back to slow tier


async def test_cached_inventory_survives_a_failed_refresh(poller):
    await poller.async_poll()
    poller._stations_read -= INVENTORY_INTERVAL
    poller.client.fail_inventory = True
    data = await poller.async_poll()
    assert data["devices"]["SN1"]["data"] == {"Power": 1}


async def test_last_device_data_survives_a_failed_read(poller):
    await poller.async_poll()
    poller.client.fail_latest = True
    data = await poller.async_poll()
    assert data["devices"]["SN1"]["data"] == {"Power": 1}
    assert data["devices"]["SN1"]["units"] == {"Power": "W"}
    assert poller.device_sns == ["SN1"]


async def test_device_data_expires_after_the_stale_timeout(poller):
    await poller.async_poll()
    sn_read, payload = poller._latest["SN1"]
    poller._latest["SN1"] = (sn_read - STALE_DATA_TIMEOUT, payload)
    poller.client.fail_latest = True
    data = await poller.async_poll()
    assert data["devices"]["SN1"]["data"] == {}
    assert poller.device_sns == []


async def test_first_read_failure_leaves_devices_without_data(poller):
    poller.client.fail_latest = True
    data = await poller.async_poll()
    assert data["devices"]["SN1"]["data"] == {}
    assert poller.device_sns == []


def test_backoff_doubles_from_the_scan_interval():
    first = next_backoff(0, 180, None)
    assert first == 360
    assert next_backoff(first, 180, None) == 720


def test_retry_after_raises_the_backoff_floor():
    assert next_backoff(0, 180, 900) == 900


def test_backoff_is_capped():
    backoff = 0.0
    for _ in range(12):
        backoff = next_backoff(backoff, 180, None)
    assert backoff == 1800


# --- rate-limit detection ----------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Rate limit exceeded",
        "API rate limit, retry later",
        "Too many requests",
        "request too frequent",
        "daily quota used up",
    ],
)
def test_rate_limit_messages_are_detected(message):
    assert _is_rate_limit(message)


@pytest.mark.parametrize(
    "message",
    [
        "value exceeds the allowed range",
        "device offline",
        "Control order failed with status 102",
        "Invalid parameter",
    ],
)
def test_ordinary_errors_are_not_treated_as_rate_limits(message):
    assert not _is_rate_limit(message)


@pytest.mark.parametrize(
    "headers,expected",
    [({"Retry-After": "120"}, 120.0), ({"Retry-After": "soon"}, None), ({}, None)],
)
def test_retry_after_parsing(headers, expected):
    assert _retry_after(headers) == expected
