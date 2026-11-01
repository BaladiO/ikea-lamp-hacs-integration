"""Connectivity binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LampCoordinator, ObegraensadConfigEntry
from .entity import LampEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the connectivity sensor."""
    async_add_entities([LampConnectivity(entry.runtime_data.coordinator)])


class LampConnectivity(LampEntity, BinarySensorEntity):
    """On while the lamp is reachable."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LampCoordinator) -> None:
        """Create the sensor."""
        super().__init__(coordinator, "reachable")

    @property
    def available(self) -> bool:
        """Always available, it reports reachability itself."""
        return True

    @property
    def is_on(self) -> bool:
        """Whether the lamp answers."""
        return self.coordinator.connected

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Which channel is up."""
        return {"websocket": self.coordinator.ws.connected}
