"""The IKEA OBEGRÄNSAD Lamp integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import LampClient
from .const import DOMAIN
from .coordinator import LampCoordinator, ObegraensadConfigEntry, ObegraensadData
from .display import DisplayEngine
from .messages import MessageQueue
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ObegraensadConfigEntry) -> bool:
    """Set up one lamp."""
    client = LampClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = LampCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    display = DisplayEngine(hass, entry, coordinator)
    messages = MessageQueue(hass, entry, coordinator)
    entry.runtime_data = ObegraensadData(client, coordinator, display, messages)

    coordinator.ws.start()
    # safety net for a failed setup; a normal unload stops these explicitly
    # first (unload callbacks run as concurrent tasks, not in order).
    # The coordinator registers its own shutdown, which closes the WebSocket.
    entry.async_on_unload(messages.async_stop)
    entry.async_on_unload(display.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ObegraensadConfigEntry) -> bool:
    """Unload a lamp, restoring its display first."""
    await entry.runtime_data.messages.async_stop()
    await entry.runtime_data.display.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ObegraensadConfigEntry) -> None:
    """Reload so new options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
