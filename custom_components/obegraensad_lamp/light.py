"""Light entity: on/off and brightness.

The firmware cannot switch the matrix off, so "off" is brightness 0.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
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
    """Add the light."""
    async_add_entities([LampLight(entry.runtime_data.coordinator)])


class LampLight(LampEntity, LightEntity):
    """The lamp's base brightness as a dimmable light."""

    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the light."""
        super().__init__(coordinator, "lamp")

    @property
    def is_on(self) -> bool:
        """On while the base brightness is above 0."""
        return self.coordinator.data.base_brightness > 0

    @property
    def brightness(self) -> int:
        """Base brightness (the night schedule may show less)."""
        return self.coordinator.data.base_brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Active plugin, rotation and the brightness actually shown."""
        data = self.coordinator.data
        return {
            "plugin": data.plugin.name if data.plugin else None,
            "rotation": data.rotation,
            "displayed_brightness": data.brightness,
            "night_brightness_active": data.brightness_schedule.active,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, at the given or the last brightness."""
        value = kwargs.get(ATTR_BRIGHTNESS, self.coordinator.last_on_brightness)
        await self.coordinator.async_set_brightness(max(1, int(value)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set brightness 0."""
        await self.coordinator.async_set_brightness(0)
