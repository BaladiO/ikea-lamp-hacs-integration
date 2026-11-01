"""Notify entity: ``notify.send_message`` scrolls text on the lamp."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ObegraensadConfigEntry
from .entity import LampEntity
from .messages import MessageQueue

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the notify entity."""
    async_add_entities([LampNotify(entry.runtime_data.messages)])


class LampNotify(LampEntity, NotifyEntity):
    """Sends scrolling text with the default delay and repeat from the options."""

    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, queue: MessageQueue) -> None:
        """Create the entity."""
        super().__init__(queue.coordinator, "notify")
        self._queue = queue

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Queue the message, prefixed with the title if given."""
        text = f"{title}: {message}" if title else message
        await self._queue.async_send(self._queue.build(text))
