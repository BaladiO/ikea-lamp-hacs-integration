"""Plugin selector."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Add the plugin select."""
    async_add_entities([PluginSelect(entry.runtime_data.coordinator)])


class PluginSelect(LampEntity, SelectEntity):
    """Choose the active plugin; options follow the lamp's plugin list."""

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the select."""
        super().__init__(coordinator, "plugin")

    @property
    def options(self) -> list[str]:
        """Plugin names in firmware order."""
        return [p.name for p in self.coordinator.data.plugins]

    @property
    def current_option(self) -> str | None:
        """Active plugin."""
        plugin = self.coordinator.data.plugin
        return plugin.name if plugin else None

    async def async_select_option(self, option: str) -> None:
        """Switch plugin."""
        await self.coordinator.async_select_plugin(self.coordinator.resolve_plugin(option))
