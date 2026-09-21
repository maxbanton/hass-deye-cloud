"""Shared helpers and base entity for Time Of Use slot entities.

The inverter exposes a fixed 6-slot Time Of Use table. Each slot is one dict in
``config['timeUseSettingItems']`` with keys ``time`` (``HHMM``), ``power`` (W),
``soc`` (%), ``voltage`` (V), ``enableGridCharge`` and ``enableGeneration``.

Writes are whole-table: to change one field of one slot we read the current six,
apply the change and send all six back, so the other slots are preserved.
"""
from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory

from .const import ID_PREFIX
from .coordinator import DeyeCloudCoordinator
from .entity import DeyeDeviceEntity

TOU_SLOT_COUNT = 6


def tou_slots(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the slot list from a device's cached config (may be empty)."""
    return device.get("config", {}).get("timeUseSettingItems") or []


async def async_write_tou_slot(
    coordinator: DeyeCloudCoordinator,
    device_sn: str,
    index: int,
    changes: dict[str, Any],
) -> None:
    """Apply ``changes`` to one slot and write the full six-slot table back."""
    device = coordinator.data.get("devices", {}).get(device_sn, {})
    slots = tou_slots(device)
    if index >= len(slots):
        raise ValueError(f"TOU slot {index + 1} is not available yet")
    new = [dict(s) for s in slots]
    new[index] = {**new[index], **changes}
    await coordinator.client.async_set_tou(device_sn, new)
    await coordinator.async_request_config_refresh()


class DeyeTouSlotEntity(DeyeDeviceEntity):
    """Base for one field of one TOU slot; grouped under Configuration.

    Cloud writes take a minute or two to read back, so each entity holds an
    optimistic value for its field until the coordinator catches up.
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
        self._optimistic: Any = None
        self._has_optimistic = False
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
        """Field value, honouring a pending optimistic write."""
        slot = self._slot
        actual = slot.get(self._field) if slot else None
        if self._has_optimistic:
            if actual == self._optimistic:
                self._has_optimistic = False
            else:
                return self._optimistic
        return actual

    async def _commit(self, api_value: Any, optimistic: Any) -> None:
        """Write one field; adopt the optimistic value until read-back agrees."""
        await async_write_tou_slot(
            self.coordinator, self._device_sn, self._index, {self._field: api_value}
        )
        self._optimistic = optimistic
        self._has_optimistic = True
        self.async_write_ha_state()
