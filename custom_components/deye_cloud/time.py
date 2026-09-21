"""Time platform for Deye Cloud: per-slot Time Of Use start times."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeyeCloudConfigEntry
from .api import DeyeCloudApiError
from .tou import TOU_SLOT_COUNT, DeyeTouSlotEntity, tou_slots

_LOGGER = logging.getLogger(__name__)

# Writes go to a rate-limited cloud API, so they are serialized.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeyeCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[TimeEntity] = []
    for sn in coordinator.device_sns:
        for i in range(TOU_SLOT_COUNT):
            entities.append(DeyeTouSlotTime(coordinator, sn, i))
    async_add_entities(entities)


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
    _label = "Time Start"
    _attr_icon = "mdi:clock-outline"

    @property
    def native_value(self) -> dt_time | None:
        return _parse(self._raw())

    async def async_set_value(self, value: dt_time) -> None:
        self._validate_order(value)
        hhmm = value.strftime("%H%M")
        try:
            await self._commit(hhmm, hhmm)
        except DeyeCloudApiError as err:
            raise HomeAssistantError(f"Inverter rejected {self._attr_name}: {err}") from err

    def _validate_order(self, value: dt_time) -> None:
        """Reject a time that would break the strictly-ascending slot order.

        The six slot start times form one 24h cycle and must stay strictly
        increasing (e.g. 01:00 < 05:00 < ... < 21:00). Only the immediate
        neighbours need checking; other slots are unaffected by this edit.
        """
        slots = tou_slots(self._device)
        new = value.hour * 60 + value.minute
        prev = _minutes(slots[self._index - 1]["time"]) if self._index > 0 else None
        nxt = (
            _minutes(slots[self._index + 1]["time"])
            if self._index + 1 < len(slots)
            else None
        )
        if prev is not None and new <= prev:
            raise HomeAssistantError(
                f"TOU Slot {self._index + 1} time {value.strftime('%H:%M')} must be "
                f"later than the previous slot ({prev // 60:02d}:{prev % 60:02d})"
            )
        if nxt is not None and new >= nxt:
            raise HomeAssistantError(
                f"TOU Slot {self._index + 1} time {value.strftime('%H:%M')} must be "
                f"earlier than the next slot ({nxt // 60:02d}:{nxt % 60:02d})"
            )
