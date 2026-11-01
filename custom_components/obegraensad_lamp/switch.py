"""Switches for the plugin schedule and the night brightness schedule."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Add the switches."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([PluginScheduleSwitch(coordinator), NightScheduleSwitch(coordinator)])


class PluginScheduleSwitch(LampEntity, SwitchEntity):
    """Runs the stored plugin schedule."""

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the switch."""
        super().__init__(coordinator, "plugin_schedule")

    @property
    def is_on(self) -> bool:
        """Whether the schedule is running."""
        return self.coordinator.data.schedule_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The stored schedule with plugin names."""
        data = self.coordinator.data
        return {
            "schedule": [
                {
                    "plugin": (p.name if (p := data.plugin_by_id(item.plugin_id)) else None),
                    "duration": item.duration,
                }
                for item in data.schedule
            ]
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the schedule (fails when none is stored)."""
        await self.coordinator.async_plugin_schedule("start")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the schedule."""
        await self.coordinator.async_plugin_schedule("stop")


class NightScheduleSwitch(LampEntity, SwitchEntity):
    """Enables the lamp's own night brightness schedule."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the switch."""
        super().__init__(coordinator, "night_schedule")

    @property
    def is_on(self) -> bool:
        """Whether the night schedule is enabled."""
        return self.coordinator.data.brightness_schedule.enabled

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Whether the night brightness is in effect right now."""
        return {"active": self.coordinator.data.brightness_schedule.active}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        await self.coordinator.async_update_brightness_schedule(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        await self.coordinator.async_update_brightness_schedule(enabled=False)
