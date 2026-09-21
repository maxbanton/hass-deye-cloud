"""Data update coordinator for Deye Cloud.

Fetching is tiered (see :mod:`.poller`); this coordinator adapts that to Home
Assistant and slows polling down when the API reports a rate limit.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DeyeCloudApiError,
    DeyeCloudAuthError,
    DeyeCloudClient,
    DeyeCloudRateLimitError,
)
from .const import DEFAULT_CONFIG_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .poller import DeyePoller, next_backoff

_LOGGER = logging.getLogger(__name__)


class DeyeCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls stations and devices and exposes their latest measure points."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DeyeCloudClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        config_interval: int = DEFAULT_CONFIG_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.poller = DeyePoller(client, config_interval=config_interval)
        self._scan_interval = scan_interval
        self._backoff = 0.0

    @property
    def station_ids(self) -> list[str]:
        return self.poller.station_ids

    @property
    def device_sns(self) -> list[str]:
        return self.poller.device_sns

    async def async_request_config_refresh(self) -> None:
        """Refresh now and re-read inverter config on the next few polls."""
        self.poller.request_config_catchup()
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.poller.async_poll()
        except DeyeCloudAuthError as err:
            # Credentials were revoked or changed; ask the user to sign in again.
            raise ConfigEntryAuthFailed(str(err)) from err
        except DeyeCloudRateLimitError as err:
            self._apply_backoff(err.retry_after)
            raise UpdateFailed(
                f"Rate limited by Deye Cloud; polling every "
                f"{int(self._backoff)}s until it clears: {err}"
            ) from err
        except DeyeCloudApiError as err:
            raise UpdateFailed(str(err)) from err
        self._clear_backoff()
        return data

    def _apply_backoff(self, retry_after: float | None) -> None:
        self._backoff = next_backoff(self._backoff, self._scan_interval, retry_after)
        self.update_interval = timedelta(seconds=self._backoff)
        _LOGGER.warning(
            "Deye Cloud rate limit hit; backing off to a %ds poll interval",
            int(self._backoff),
        )

    def _clear_backoff(self) -> None:
        if not self._backoff:
            return
        self._backoff = 0.0
        self.update_interval = timedelta(seconds=self._scan_interval)
        _LOGGER.info("Deye Cloud rate limit cleared; resuming normal polling")
