"""Message queue in front of the lamp's message pool.

The firmware keeps up to 10 messages and silently drops more, never reports
when one has finished, replaces a message that reuses an id, and shows repeats
once per minute. So the integration keeps at most a few messages on the lamp,
gives each a distinct id, estimates when each has finished (an upper bound),
removes it explicitly at that point and then feeds the next queued message.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import itertools
import logging
import time
from typing import TYPE_CHECKING, Any, Literal
import zlib

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later

from .api import MESSAGE_POOL_SIZE, LampError
from .const import (
    CONF_MAX_LAMP_MESSAGES,
    CONF_MESSAGE_DELAY,
    CONF_MESSAGE_REPEAT,
    CONF_NIGHT_SUPPRESS_LOW,
    DEFAULT_MAX_LAMP_MESSAGES,
    DEFAULT_MESSAGE_DELAY,
    DEFAULT_MESSAGE_REPEAT,
    DEFAULT_NIGHT_SUPPRESS_LOW,
    DOMAIN,
)
from .text import sanitize, scroll_width

if TYPE_CHECKING:
    from .coordinator import LampCoordinator, ObegraensadConfigEntry

_LOGGER = logging.getLogger(__name__)

Priority = Literal["low", "normal", "high"]
Status = Literal["sent", "queued", "suppressed"]

# messages waiting in Home Assistant, on top of those on the lamp
MAX_QUEUED = 20
# extra time before a message is considered finished
SLACK_SECONDS = 10.0
# the firmware shows repeats at each minute change
REPEAT_INTERVAL = 60.0
# id ranges: automatic ids, then numeric user ids, then hashed string ids
AUTO_ID_MAX = 999
USER_INT_OFFSET = 1000
USER_INT_MAX = 999_999
HASHED_OFFSET = 1_000_000


def lamp_id_for_key(key: str | int) -> int:
    """Map a user ``message_id`` to the integer id used on the lamp.

    Numbers 0-999999 map to 1000 + n; anything else is hashed into a range of
    its own, so the same key always gives the same lamp id.
    """
    if isinstance(key, int) or (isinstance(key, str) and key.strip().isdigit()):
        number = int(key)
        if 0 <= number <= USER_INT_MAX:
            return USER_INT_OFFSET + number
    return HASHED_OFFSET + zlib.crc32(str(key).encode("utf-8")) % 1_000_000_000


@dataclass
class Message:
    """A message for the lamp."""

    text: str
    repeat: int
    delay: int
    graph: list[int] = field(default_factory=list)
    miny: int = 0
    maxy: int = 15
    priority: Priority = "normal"
    key: str | int | None = None
    lamp_id: int = 0

    def showing_seconds(self) -> float:
        """How long one showing scrolls, as the firmware computes it."""
        steps = 0
        if self.text:
            steps += 16 + scroll_width(self.text)
        if self.graph:
            steps += 16 + len(self.graph)
        return steps * self.delay / 1000

    def lifetime_seconds(self) -> float | None:
        """Upper bound until the lamp is done with it; ``None`` = forever."""
        if self.repeat < 0:
            return None
        # repeats come at minute changes, the last one may start up to
        # ``repeat`` minutes later; earlier showings of other messages delay it
        return self.showing_seconds() + self.repeat * REPEAT_INTERVAL + SLACK_SECONDS


@dataclass
class _Slot:
    message: Message
    sent_at: float
    expire: CALLBACK_TYPE | None = None


class MessageQueue:
    """Feeds messages to one lamp, a few at a time."""

    def __init__(
        self, hass: HomeAssistant, entry: ObegraensadConfigEntry, coordinator: LampCoordinator
    ) -> None:
        """Read limits from the options."""
        self.hass = hass
        self.coordinator = coordinator
        options = entry.options
        self.default_delay = int(options.get(CONF_MESSAGE_DELAY, DEFAULT_MESSAGE_DELAY))
        self.default_repeat = int(options.get(CONF_MESSAGE_REPEAT, DEFAULT_MESSAGE_REPEAT))
        self.max_on_lamp = min(
            int(options.get(CONF_MAX_LAMP_MESSAGES, DEFAULT_MAX_LAMP_MESSAGES)),
            MESSAGE_POOL_SIZE - 2,
        )
        self.night_suppress_low = bool(
            options.get(CONF_NIGHT_SUPPRESS_LOW, DEFAULT_NIGHT_SUPPRESS_LOW)
        )
        self._on_lamp: dict[int, _Slot] = {}
        self._queue: list[Message] = []
        self._auto_ids = itertools.cycle(range(1, AUTO_ID_MAX + 1))
        self._lock = asyncio.Lock()
        self._stopped = False

    # public API ---------------------------------------------------------

    @property
    def on_lamp(self) -> list[Message]:
        """Messages currently placed on the lamp."""
        return [slot.message for slot in self._on_lamp.values()]

    @property
    def queued(self) -> list[Message]:
        """Messages waiting for a free slot."""
        return list(self._queue)

    def build(
        self,
        text: str,
        *,
        repeat: int | None = None,
        delay: int | None = None,
        graph: Sequence[int] | None = None,
        miny: int = 0,
        maxy: int = 15,
        priority: Priority = "normal",
        key: str | int | None = None,
    ) -> Message:
        """Validate and sanitise a message, applying the option defaults."""
        clean = sanitize(text)
        if clean.changed:
            _LOGGER.debug(
                "Message text changed for the lamp font: %r -> %r (replaced %s, dropped %s%s)",
                text,
                clean.text,
                clean.replaced,
                sorted(clean.dropped),
                ", truncated" if clean.truncated else "",
            )
        if not clean.text and not graph:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="message_empty")
        if maxy < miny:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="graph_range")
        return Message(
            text=clean.text,
            repeat=self.default_repeat if repeat is None else repeat,
            delay=self.default_delay if delay is None else delay,
            graph=list(graph or []),
            miny=miny,
            maxy=maxy,
            priority=priority,
            key=key,
        )

    async def async_send(self, message: Message) -> dict[str, Any]:
        """Send now or queue. Returns the status and the lamp id."""
        if self._stopped:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_ready")
        data = self.coordinator.data
        if (
            message.priority == "low"
            and self.night_suppress_low
            and data is not None
            and data.brightness_schedule.active
        ):
            _LOGGER.debug("Suppressed low-priority message at night: %r", message.text)
            return {"status": "suppressed", "message_id": message.key}

        async with self._lock:
            message.lamp_id = (
                lamp_id_for_key(message.key) if message.key is not None else self._next_auto_id()
            )
            # a message with the same id replaces the old one, on the lamp and in the queue
            self._queue = [m for m in self._queue if m.lamp_id != message.lamp_id]
            replacing = message.lamp_id in self._on_lamp
            if replacing or len(self._on_lamp) < self.max_on_lamp:
                await self._place(message)
                status: Status = "sent"
            elif message.priority == "high" and (victim := self._lowest_finite()):
                await self._remove_from_lamp(victim)
                await self._place(message)
                status = "sent"
            else:
                if len(self._queue) >= MAX_QUEUED:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="queue_full",
                        translation_placeholders={"count": str(MAX_QUEUED)},
                    )
                if message.priority == "high":
                    self._queue.insert(0, message)
                else:
                    self._queue.append(message)
                status = "queued"
        return {"status": status, "message_id": message.key, "lamp_id": message.lamp_id}

    async def async_remove(self, key: str | int | None) -> int:
        """Remove one message by its ``message_id``, or all when ``None``.

        Returns how many messages were removed from the lamp or the queue.
        """
        async with self._lock:
            if key is None:
                count = len(self._queue) + len(self._on_lamp)
                self._queue.clear()
                for lamp_id in list(self._on_lamp):
                    await self._remove_from_lamp(lamp_id)
                return count
            lamp_id = lamp_id_for_key(key)
            before = len(self._queue)
            self._queue = [m for m in self._queue if m.lamp_id != lamp_id]
            count = before - len(self._queue)
            if lamp_id in self._on_lamp:
                count += 1
            # also when unknown: it may be left over from before a restart
            await self._remove_from_lamp(lamp_id)
        await self._async_pump()
        return count

    async def async_stop(self) -> None:
        """Cancel timers and drop the queue; messages on the lamp stay."""
        self._stopped = True
        self._queue.clear()
        for slot in self._on_lamp.values():
            if slot.expire:
                slot.expire()
        self._on_lamp.clear()

    # internals ----------------------------------------------------------

    def _next_auto_id(self) -> int:
        for _ in range(AUTO_ID_MAX):
            candidate = next(self._auto_ids)
            if candidate not in self._on_lamp:
                return candidate
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="queue_full")

    def _lowest_finite(self) -> int | None:
        """Pick the oldest non-high message that ends by itself, to make room."""
        candidates = [
            (slot.sent_at, lamp_id)
            for lamp_id, slot in self._on_lamp.items()
            if slot.message.priority != "high" and slot.message.repeat >= 0
        ]
        return min(candidates)[1] if candidates else None

    async def _place(self, message: Message) -> None:
        """Send to the lamp (lock held)."""
        try:
            await self.coordinator.client.send_message(
                message.text,
                message_id=message.lamp_id,
                repeat=message.repeat,
                delay=message.delay,
                graph=message.graph,
                miny=message.miny,
                maxy=message.maxy,
            )
        except LampError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        old = self._on_lamp.pop(message.lamp_id, None)
        if old and old.expire:
            old.expire()
        slot = _Slot(message, time.monotonic())
        lifetime = message.lifetime_seconds()
        if lifetime is not None:
            slot.expire = async_call_later(self.hass, lifetime, self._expired(message.lamp_id))
        self._on_lamp[message.lamp_id] = slot
        _LOGGER.debug(
            "Message %d on lamp (%s, repeat %d, ~%s s): %r",
            message.lamp_id,
            message.priority,
            message.repeat,
            f"{lifetime:.0f}" if lifetime is not None else "inf",
            message.text,
        )

    async def _remove_from_lamp(self, lamp_id: int) -> None:
        """Remove from the lamp and forget the slot (lock held)."""
        slot = self._on_lamp.pop(lamp_id, None)
        if slot and slot.expire:
            slot.expire()
        try:
            await self.coordinator.client.remove_message(lamp_id)
        except LampError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err

    def _expired(self, lamp_id: int) -> Callable[[Any], None]:
        @callback
        def _done(_now: Any) -> None:
            slot = self._on_lamp.get(lamp_id)
            if slot is None or self._stopped:
                return
            slot.expire = None
            self.hass.async_create_background_task(
                self._async_finish(lamp_id), f"{DOMAIN} message {lamp_id} done"
            )

        return _done

    async def _async_finish(self, lamp_id: int) -> None:
        async with self._lock:
            if lamp_id in self._on_lamp:
                try:
                    # normally gone already; makes sure even if the clock never synced
                    await self._remove_from_lamp(lamp_id)
                except HomeAssistantError as err:
                    _LOGGER.debug("Could not remove finished message %d: %s", lamp_id, err)
                    self._on_lamp.pop(lamp_id, None)
        await self._async_pump()

    async def _async_pump(self) -> None:
        """Move queued messages onto free slots."""
        async with self._lock:
            while self._queue and len(self._on_lamp) < self.max_on_lamp and not self._stopped:
                message = self._queue.pop(0)
                try:
                    await self._place(message)
                except HomeAssistantError as err:
                    _LOGGER.warning("Dropping queued message %r: %s", message.text, err)
