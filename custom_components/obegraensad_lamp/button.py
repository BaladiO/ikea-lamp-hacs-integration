"""Rotate and persist buttons (WebSocket-only commands)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LampCoordinator, ObegraensadConfigEntry
from .entity import LampEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LampButtonDescription(ButtonEntityDescription):
    """Describes a button and the WebSocket event it sends."""

    payload: dict[str, Any]


BUTTONS: tuple[LampButtonDescription, ...] = (
    LampButtonDescription(key="rotate_left", payload={"event": "rotate", "direction": "left"}),
    LampButtonDescription(key="rotate_right", payload={"event": "rotate", "direction": "right"}),
    LampButtonDescription(
        key="persist_plugin",
        entity_category=EntityCategory.CONFIG,
        payload={"event": "persist-plugin"},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(LampButton(coordinator, d) for d in BUTTONS)


class LampButton(LampEntity, ButtonEntity):
    """Sends one WebSocket event."""

    entity_description: LampButtonDescription

    def __init__(self, coordinator: LampCoordinator, description: LampButtonDescription) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the event."""
        await self.coordinator.async_ws_command(self.entity_description.payload)
