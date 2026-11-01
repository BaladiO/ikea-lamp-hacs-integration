"""Night schedule start and end times."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LampCoordinator, ObegraensadConfigEntry
from .entity import LampEntity

PARALLEL_UPDATES = 1


def parse_hhmm(value: str) -> time | None:
    """Parse the firmware's ``HH:MM``."""
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add start and end time entities."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            NightTime(coordinator, "night_start", "start_time"),
            NightTime(coordinator, "night_end", "end_time"),
        ]
    )


class NightTime(LampEntity, TimeEntity):
    """One end of the night brightness window."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LampCoordinator, key: str, field: str) -> None:
        """Bind to ``start_time`` or ``end_time``."""
        super().__init__(coordinator, key)
        self._field = field

    @property
    def native_value(self) -> time | None:
        """Configured time."""
        return parse_hhmm(getattr(self.coordinator.data.brightness_schedule, self._field))

    async def async_set_value(self, value: time) -> None:
        """Store a new time (seconds are dropped)."""
        await self.coordinator.async_update_brightness_schedule(
            **{self._field: f"{value.hour:02d}:{value.minute:02d}"}
        )
