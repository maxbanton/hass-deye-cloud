"""Data update coordinator for Deye Cloud.

Fetching is tiered (see :mod:`.poller`); this coordinator adapts that to Home
Assistant and slows polling down when the API reports a rate limit.
"""
from __future__ import annotations

import asyncio
import logging
import time
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
from .const import (
    DEFAULT_CONFIG_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    READBACK_WINDOW,
)
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
        # Written values the cloud has not read back yet: (sn, key) -> (value, when).
        self._pending: dict[tuple[str, str], tuple[Any, float]] = {}
        # TOU writes send the whole table, so building and sending one must not
        # interleave with another (number, switch and time each queue their own).
        self.tou_lock = asyncio.Lock()

    @property
    def station_ids(self) -> list[str]:
        return self.poller.station_ids

    @property
    def device_sns(self) -> list[str]:
        return self.poller.device_sns

    def set_pending(self, device_sn: str, key: str, value: Any) -> None:
        """Remember a written value until the cloud reads it back."""
        self._pending[(device_sn, key)] = (value, time.monotonic())

    def clear_pending(self, device_sn: str, prefix: str) -> None:
        for sn, key in list(self._pending):
            if sn == device_sn and key.startswith(prefix):
                del self._pending[(sn, key)]

    def pending_value(self, device_sn: str, key: str, actual: Any) -> Any:
        """Return the pending write for ``key``, or ``actual`` once it no longer applies.

        A pending write is dropped when the read-back matches it, or when config
        was read again well after the write and still differs (the inverter
        clamped or rejected it, or it was changed on the unit).
        """
        entry = self._pending.get((device_sn, key))
        if entry is None:
            return actual
        value, written = entry
        read_at = self.poller.config_read_at.get(device_sn, 0.0)
        if actual == value or read_at - written >= READBACK_WINDOW:
            del self._pending[(device_sn, key)]
            return actual
        return value

    async def async_request_config_refresh(self) -> None:
        """Refresh now and re-read inverter config on the next few polls."""
        self.poller.request_config_catchup()
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.poller.async_poll()
        except DeyeCloudAuthError as err:
            # Credentials were revoked or changed; ask the user to sign in again.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except DeyeCloudRateLimitError as err:
            self._apply_backoff(err.retry_after)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={"seconds": str(int(self._backoff)), "error": str(err)},
            ) from err
        except DeyeCloudApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
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
