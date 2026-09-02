"""Data update coordinator for Deye Cloud."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudApiError, DeyeCloudClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class DeyeCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls stations and devices and exposes their latest measure points."""

    def __init__(self, hass: HomeAssistant, client: DeyeCloudClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.station_ids: list[str] = []
        self.device_sns: list[str] = []

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except DeyeCloudApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> dict[str, Any]:
        data: dict[str, Any] = {"stations": {}, "devices": {}}
        stations = await self.client.async_get_stations_with_devices()

        device_sns: list[str] = []
        for station in stations:
            station_id = str(station.get("id") or station.get("stationId") or "")
            if not station_id:
                continue
            try:
                latest = await self.client.async_get_station_latest(station_id)
            except DeyeCloudApiError as err:
                _LOGGER.debug("Station %s latest failed: %s", station_id, err)
                latest = {}
            data["stations"][station_id] = {"info": station, "data": latest}
            for dev in station.get("deviceListItems", []):
                sn = dev.get("deviceSn")
                if sn:
                    device_sns.append(sn)
                    data["devices"][sn] = {"info": dev, "data": {}, "units": {}, "config": {}}

        # Device latest data, batched (API allows up to 10 SNs per call).
        for i in range(0, len(device_sns), 10):
            batch = device_sns[i : i + 10]
            try:
                latest = await self.client.async_get_device_latest(batch)
            except DeyeCloudApiError as err:
                _LOGGER.warning("Device latest failed for %s: %s", batch, err)
                continue
            for sn, payload in latest.items():
                if sn in data["devices"]:
                    data["devices"][sn]["data"] = payload.get("data", {})
                    data["devices"][sn]["units"] = payload.get("units", {})

        # Config reads (feed the switch/select current state); best effort.
        for sn, entry in data["devices"].items():
            if not entry["data"]:
                continue
            config: dict[str, Any] = {}
            for fetch in (self.client.async_get_system_config, self.client.async_get_battery_config):
                try:
                    config.update(await fetch(sn))
                except DeyeCloudApiError as err:
                    _LOGGER.debug("Config read failed for %s: %s", sn, err)
            entry["config"] = config

        self.station_ids = list(data["stations"])
        self.device_sns = [sn for sn, e in data["devices"].items() if e["data"]]
        _LOGGER.debug(
            "Update complete: %d stations, %d devices with data",
            len(self.station_ids),
            len(self.device_sns),
        )
        return data
