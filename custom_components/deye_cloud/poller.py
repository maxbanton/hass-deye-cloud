"""Tiered polling logic for Deye Cloud, independent of Home Assistant.

The Deye Cloud OpenAPI is a shared, quota-limited resource, so a poll fetches
each kind of data only as often as it can actually change:

* device measurements  -- every poll (this is the data that moves); if a read
  fails, the last good values are served for up to ``STALE_DATA_TIMEOUT``
* station measurements -- every poll (station-level aggregate)
* station/device list  -- hourly (inventory, only needed for discovery)
* inverter config      -- every ``config_interval`` minutes, plus a short burst
  of re-reads after this integration writes a setting

Cached values are reused between reads, so entity state never goes stale-empty
just because a tier was skipped.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .api import DeyeCloudApiError, DeyeCloudClient, DeyeCloudRateLimitError
from .const import (
    CONFIG_CATCHUP_POLLS,
    DEFAULT_CONFIG_INTERVAL,
    INVENTORY_INTERVAL,
    MAX_BACKOFF_INTERVAL,
    STALE_DATA_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# The API accepts at most 10 serial numbers per /device/latest call.
DEVICE_BATCH_SIZE = 10


def next_backoff(
    current: float, scan_interval: float, retry_after: float | None
) -> float:
    """Return the poll interval to use after a rate-limit response.

    Doubles on each consecutive hit, never goes below what the API asked for in
    Retry-After, and is capped so polling still recovers on its own.
    """
    backoff = current * 2 if current else scan_interval * 2
    if retry_after:
        backoff = max(backoff, retry_after)
    return min(backoff, MAX_BACKOFF_INTERVAL)


class DeyePoller:
    """Fetches Deye Cloud data in tiers, caching what rarely changes."""

    def __init__(
        self,
        client: DeyeCloudClient,
        config_interval: int = DEFAULT_CONFIG_INTERVAL,
    ) -> None:
        self.client = client
        self.config_interval = config_interval * 60
        self.station_ids: list[str] = []
        self.device_sns: list[str] = []

        self._stations: list[dict[str, Any]] = []
        self._stations_read = 0.0
        self._configs: dict[str, dict[str, Any]] = {}
        self._latest: dict[str, tuple[float, dict[str, Any]]] = {}
        self._configs_read = 0.0
        self._config_catchup = 0

    def request_config_catchup(self) -> None:
        """Re-read inverter config on the next few polls.

        Called after this integration writes a setting: the cloud needs a minute
        or two before a write reads back, so a short burst of config reads lets
        entities converge without polling config on every cycle.
        """
        self._config_catchup = CONFIG_CATCHUP_POLLS

    async def async_poll(self) -> dict[str, Any]:
        """Run one poll and return the full data tree."""
        now = time.monotonic()
        data: dict[str, Any] = {"stations": {}, "devices": {}}
        stations = await self._async_inventory(now)

        device_sns: list[str] = []
        for station in stations:
            station_id = str(station.get("id") or station.get("stationId") or "")
            if not station_id:
                continue
            try:
                latest = await self.client.async_get_station_latest(station_id)
            except DeyeCloudRateLimitError:
                raise
            except DeyeCloudApiError as err:
                _LOGGER.debug("Station %s latest failed: %s", station_id, err)
                latest = {}
            data["stations"][station_id] = {"info": station, "data": latest}
            for dev in station.get("deviceListItems", []):
                sn = dev.get("deviceSn")
                if sn:
                    device_sns.append(sn)
                    data["devices"][sn] = {
                        "info": dev, "data": {}, "units": {}, "config": {},
                    }

        for i in range(0, len(device_sns), DEVICE_BATCH_SIZE):
            batch = device_sns[i : i + DEVICE_BATCH_SIZE]
            try:
                latest = await self.client.async_get_device_latest(batch)
            except DeyeCloudRateLimitError:
                raise
            except DeyeCloudApiError as err:
                _LOGGER.warning("Device latest failed for %s: %s", batch, err)
                latest = {}
            for sn, payload in latest.items():
                if sn in data["devices"] and payload.get("data"):
                    self._latest[sn] = (now, payload)
            for sn in batch:
                read, payload = self._latest.get(sn, (0.0, {}))
                if payload and now - read < STALE_DATA_TIMEOUT:
                    data["devices"][sn]["data"] = payload.get("data", {})
                    data["devices"][sn]["units"] = payload.get("units", {})

        online = [sn for sn, entry in data["devices"].items() if entry["data"]]
        if online and self._config_due(now):
            await self._async_configs(online, now)
        for sn, entry in data["devices"].items():
            entry["config"] = self._configs.get(sn, {})

        self.station_ids = list(data["stations"])
        self.device_sns = online
        _LOGGER.debug(
            "Poll complete: %d stations, %d devices with data",
            len(self.station_ids),
            len(self.device_sns),
        )
        return data

    # --- tiers ---------------------------------------------------------------

    async def _async_inventory(self, now: float) -> list[dict[str, Any]]:
        """Return the station/device list, re-reading it at most hourly."""
        if self._stations and now - self._stations_read < INVENTORY_INTERVAL:
            return self._stations
        try:
            self._stations = await self.client.async_get_stations_with_devices()
        except DeyeCloudRateLimitError:
            raise
        except DeyeCloudApiError:
            if not self._stations:
                raise
            _LOGGER.debug("Inventory refresh failed; reusing cached station list")
            return self._stations
        self._stations_read = now
        return self._stations

    def _config_due(self, now: float) -> bool:
        return (
            self._config_catchup > 0
            or not self._configs
            or now - self._configs_read >= self.config_interval
        )

    async def _async_configs(self, device_sns: list[str], now: float) -> None:
        """Read system/battery/TOU config for the given devices (best effort)."""
        for sn in device_sns:
            config: dict[str, Any] = {}
            for fetch in (
                self.client.async_get_system_config,
                self.client.async_get_battery_config,
                self.client.async_get_tou,
            ):
                try:
                    config.update(await fetch(sn))
                except DeyeCloudRateLimitError:
                    raise
                except DeyeCloudApiError as err:
                    _LOGGER.debug("Config read failed for %s: %s", sn, err)
            if config:
                self._configs[sn] = config
        self._configs_read = now
        if self._config_catchup:
            self._config_catchup -= 1
