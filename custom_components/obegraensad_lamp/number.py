"""Night schedule brightness."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LampCoordinator, ObegraensadConfigEntry
from .entity import LampEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the number."""
    async_add_entities([NightBrightness(entry.runtime_data.coordinator)])


class NightBrightness(LampEntity, NumberEntity):
    """Brightness used while the night schedule is active."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the number."""
        super().__init__(coordinator, "night_brightness")

    @property
    def native_value(self) -> int:
        """Configured night brightness."""
        return self.coordinator.data.brightness_schedule.brightness

    async def async_set_native_value(self, value: float) -> None:
        """Store a new night brightness."""
        await self.coordinator.async_update_brightness_schedule(brightness=int(value))
