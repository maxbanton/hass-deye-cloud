"""Time platform for Deye Cloud: per-slot Time Of Use start times."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .const import DOMAIN
from .entity import async_add_discovered, rejected
from .tou import DeyeTouSlotEntity, effective_tou_slots, tou_slot_indices

_LOGGER = logging.getLogger(__name__)

# Writes go to a rate-limited cloud API, so they are serialized.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def discover() -> Iterator[TimeEntity]:
        for sn in coordinator.device_sns:
            for i in tou_slot_indices(coordinator.data["devices"][sn]):
                yield DeyeTouSlotTime(coordinator, sn, i)

    async_add_discovered(entry, async_add_entities, discover)


def _parse(raw: object) -> dt_time | None:
    """Parse a slot time; accepts ``HHMM`` (e.g. ``0100``) or ``HH:mm``."""
    s = str(raw or "").strip()
    if ":" in s:
        hh, _, mm = s.partition(":")
    else:
        s = s.zfill(4)
        hh, mm = s[:2], s[2:4]
    try:
        return dt_time(int(hh) % 24, int(mm) % 60)
    except (TypeError, ValueError):
        return None


def _minutes(raw: object) -> int | None:
    """Minutes-since-midnight for a slot time, or None if unparseable."""
    parsed = _parse(raw)
    return None if parsed is None else parsed.hour * 60 + parsed.minute


class DeyeTouSlotTime(DeyeTouSlotEntity, TimeEntity):
    """Editable start time of one Time Of Use slot.

    Slot times are contiguous on the inverter (each slot begins where the
    previous ends); the inverter validates writes, so an out-of-order time may
    be clamped or rejected.
    """

    _domain = "time"
    _field = "time"
    _slug = "time"

    @property
    def native_value(self) -> dt_time | None:
        return _parse(self._raw())

    async def async_set_value(self, value: dt_time) -> None:
        if value.minute % 5:
            # The TOU update endpoint only takes times in 5-minute steps.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tou_time_step",
                translation_placeholders=self._time_placeholders(value),
            )
        self._validate_order(value)
        hhmm = value.strftime("%H%M")
        try:
            await self._commit(hhmm)
        except DeyeCloudApiError as err:
            raise rejected(self.name, err) from err

    def _time_placeholders(self, value: dt_time, other: int | None = None) -> dict[str, str]:
        placeholders = {"slot": str(self._index + 1), "time": value.strftime("%H:%M")}
        if other is not None:
            placeholders["other"] = f"{other // 60:02d}:{other % 60:02d}"
        return placeholders

    def _validate_order(self, value: dt_time) -> None:
        """Reject a time that would break the strictly-ascending slot order.

        The six slot start times form one 24h cycle and must stay strictly
        increasing (e.g. 01:00 < 05:00 < ... < 21:00). Only the immediate
        neighbours need checking; other slots are unaffected by this edit.
        """
        slots = effective_tou_slots(self.coordinator, self._device_sn)
        new = value.hour * 60 + value.minute
        prev = _minutes(slots[self._index - 1]["time"]) if self._index > 0 else None
        nxt = (
            _minutes(slots[self._index + 1]["time"])
            if self._index + 1 < len(slots)
            else None
        )
        if prev is not None and new <= prev:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tou_time_after",
                translation_placeholders=self._time_placeholders(value, prev),
            )
        if nxt is not None and new >= nxt:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tou_time_before",
                translation_placeholders=self._time_placeholders(value, nxt),
            )
