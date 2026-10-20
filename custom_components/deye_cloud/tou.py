"""Shared helpers and base entity for Time Of Use slot entities.

The inverter exposes a fixed 6-slot Time Of Use table. Each slot is one dict in
``config['timeUseSettingItems']`` with keys ``time`` (``HHMM``), ``power`` (W),
``soc`` (%), ``voltage`` (V), ``enableGridCharge`` and ``enableGeneration``.

Writes are whole-table: to change one field of one slot we take the current six,
apply the change and send all six back, so the other slots are preserved. The
cached table lags a write by a minute or two, so edits that have not read back
yet are layered over it; otherwise a second edit would revert the first.
"""
from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory

from .const import ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity

TOU_SLOT_COUNT = 6
TOU_FIELDS = ("time", "power", "soc", "voltage", "enableGridCharge", "enableGeneration")
TOU_PENDING_PREFIX = "tou_slot"


def tou_slots(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the slot list from a device's cached config (may be empty)."""
    return device.get("config", {}).get("timeUseSettingItems") or []


def tou_slot_indices(device: dict[str, Any]) -> range:
    """Indices of the slots the inverter reported."""
    return range(min(len(tou_slots(device)), TOU_SLOT_COUNT))


def tou_pending_key(index: int, field: str) -> str:
    return f"{TOU_PENDING_PREFIX}{index}.{field}"


def effective_tou_slots(
    coordinator: DeyeCloudCoordinator, device_sn: str
) -> list[dict[str, Any]]:
    """Cached slots with writes that have not read back yet applied."""
    device = coordinator.data.get("devices", {}).get(device_sn, {})
    slots = []
    for index, cached in enumerate(tou_slots(device)):
        slot = dict(cached)
        for field in TOU_FIELDS:
            value = coordinator.pending_value(
                device_sn, tou_pending_key(index, field), slot.get(field)
            )
            if value is not None:
                slot[field] = value
        slots.append(slot)
    return slots


def set_pending_tou(
    coordinator: DeyeCloudCoordinator, device_sn: str, slots: list[dict[str, Any]]
) -> None:
    """Record a just-written table so later edits build on it."""
    coordinator.clear_pending(device_sn, TOU_PENDING_PREFIX)
    for index, slot in enumerate(slots):
        for field in TOU_FIELDS:
            if field in slot:
                coordinator.set_pending(device_sn, tou_pending_key(index, field), slot[field])


async def async_write_tou_slot(
    coordinator: DeyeCloudCoordinator,
    device_sn: str,
    index: int,
    changes: dict[str, Any],
) -> None:
    """Apply ``changes`` to one slot and write the full six-slot table back."""
    async with coordinator.tou_lock:
        slots = effective_tou_slots(coordinator, device_sn)
        if index >= len(slots):
            raise ValueError(f"TOU slot {index + 1} is not available yet")
        slots[index] = {**slots[index], **changes}
        await coordinator.client.async_set_tou(device_sn, slots)
        for field, value in changes.items():
            coordinator.set_pending(device_sn, tou_pending_key(index, field), value)
    await coordinator.async_request_config_refresh()


class DeyeTouSlotEntity(DeyeDeviceEntity):
    """Base for one field of one TOU slot; grouped under Configuration.

    Cloud writes take a minute or two to read back, so each entity shows the
    coordinator's pending value for its field until the read-back catches up.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _domain: str = ""       # entity_id domain (number/switch/time)
    _field: str = ""        # slot dict key this entity edits
    _slug: str = ""         # entity_id suffix
    _label: str = ""        # friendly-name suffix

    def __init__(
        self, coordinator: DeyeCloudCoordinator, device_sn: str, index: int
    ) -> None:
        super().__init__(coordinator, device_sn)
        self._index = index
        self._attr_unique_id = f"{device_sn}_tou{index + 1}_{self._slug}"
        self.entity_id = f"{self._domain}.{ID_PREFIX}_tou{index + 1}_{self._slug}"
        self._attr_name = f"TOU Slot {index + 1} {self._label}"

    @property
    def _slot(self) -> dict[str, Any] | None:
        slots = tou_slots(self._device)
        return slots[self._index] if self._index < len(slots) else None

    @property
    def available(self) -> bool:
        return super().available and self._slot is not None

    def _raw(self) -> Any:
        """Field value, honouring a write that has not read back yet."""
        slot = self._slot
        return self.coordinator.pending_value(
            self._device_sn,
            tou_pending_key(self._index, self._field),
            slot.get(self._field) if slot else None,
        )

    async def _commit(self, value: Any) -> None:
        await async_write_tou_slot(
            self.coordinator, self._device_sn, self._index, {self._field: value}
        )
        self.async_write_ha_state()
