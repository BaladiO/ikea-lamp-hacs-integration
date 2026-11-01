"""Message queue in front of the lamp's 10-slot message pool. Implemented in phase 4."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import LampCoordinator, ObegraensadConfigEntry


class MessageQueue:
    """Feeds messages to the lamp a few at a time."""

    def __init__(
        self, hass: HomeAssistant, entry: ObegraensadConfigEntry, coordinator: LampCoordinator
    ) -> None:
        """Store references."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator

    async def async_stop(self) -> None:
        """Stop feeding messages."""
