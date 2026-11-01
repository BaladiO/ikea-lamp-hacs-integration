"""Temporary-display engine (DDP frames with restore). Implemented in phase 5."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import LampCoordinator, ObegraensadConfigEntry


class DisplayEngine:
    """Shows temporary frames and restores the previous plugin."""

    def __init__(
        self, hass: HomeAssistant, entry: ObegraensadConfigEntry, coordinator: LampCoordinator
    ) -> None:
        """Store references."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator

    async def async_release(self) -> None:
        """End a held temporary display so the plugin shows again."""

    async def async_stop(self) -> None:
        """Cancel any display and restore the lamp."""
