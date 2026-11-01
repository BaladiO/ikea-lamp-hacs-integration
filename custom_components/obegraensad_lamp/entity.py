"""Base entity for the lamp."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, NAME
from .coordinator import LampCoordinator


class LampEntity(CoordinatorEntity[LampCoordinator]):
    """Entity bound to one lamp device, identified by its MAC address."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LampCoordinator, key: str) -> None:
        """Set unique id and device info."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        mac = format_mac(entry.unique_id or "")
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=coordinator.client.base_url,
        )

    @property
    def available(self) -> bool:
        """Available while the lamp answers over WebSocket or HTTP."""
        return self.coordinator.data is not None and self.coordinator.connected
