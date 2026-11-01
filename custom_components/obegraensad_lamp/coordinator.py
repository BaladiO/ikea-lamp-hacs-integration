"""State coordinator: WebSocket push with an HTTP poll as heartbeat."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BrightnessSchedule,
    LampClient,
    LampCommandError,
    LampError,
    LampNotSupportedError,
    LampResponseError,
    LampState,
    Plugin,
    ScheduleItem,
)
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    ISSUE_FIRMWARE,
    ISSUE_UNREACHABLE,
    UNREACHABLE_ISSUE_AFTER,
)
from .ws_client import LampWebSocket

if TYPE_CHECKING:
    from .display import DisplayEngine
    from .messages import MessageQueue

_LOGGER = logging.getLogger(__name__)

# WebSocket pushes come in bursts; entities are updated once per burst
DEBOUNCE_SECONDS = 0.2


@dataclass
class ObegraensadData:
    """Runtime data stored on the config entry."""

    client: LampClient
    coordinator: LampCoordinator
    display: DisplayEngine
    messages: MessageQueue


type ObegraensadConfigEntry = ConfigEntry[ObegraensadData]


class LampCoordinator(DataUpdateCoordinator[LampState]):
    """Keeps the lamp state.

    The WebSocket is the primary source. Its pushes update ``data`` straight
    away (so waiters see them) and notify entities debounced. Pushes do not reset
    the poll timer, because only the HTTP poll carries the diagnostic values.
    """

    config_entry: ObegraensadConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ObegraensadConfigEntry, client: LampClient
    ) -> None:
        """Set up the coordinator and its (not yet started) WebSocket."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.client = client
        self.ws = LampWebSocket(
            async_get_clientsession(hass),
            client.host,
            self._handle_ws_info,
            self._handle_ws_connection,
        )
        self.last_on_brightness = 255
        self._changed = asyncio.Event()
        self._debounce: asyncio.TimerHandle | None = None
        self._unreachable_since: float | None = None

    # state intake -------------------------------------------------------

    async def _async_update_data(self) -> LampState:
        try:
            state = await self.client.get_info()
        except LampNotSupportedError as err:
            self._raise_issue(ISSUE_FIRMWARE, ir.IssueSeverity.ERROR)
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="firmware_unsupported"
            ) from err
        except LampError as err:
            self._note_unreachable()
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self._note_reachable()
        return self._accept(state)

    def _accept(self, state: LampState) -> LampState:
        """Merge a new state into the old one and wake waiters."""
        if self.data is not None:
            state = self.data.merge(state)
        if state.base_brightness > 0:
            self.last_on_brightness = state.base_brightness
        self.data = state
        self._changed.set()
        self._changed = asyncio.Event()
        return state

    @callback
    def _handle_ws_info(self, payload: dict[str, Any]) -> None:
        try:
            state = LampState.from_info(payload)
        except LampResponseError as err:
            _LOGGER.debug("Ignoring bad info push: %s", err)
            return
        self._accept(state)
        if self._debounce is None:
            self._debounce = self.hass.loop.call_later(DEBOUNCE_SECONDS, self._flush)

    @callback
    def _flush(self) -> None:
        self._debounce = None
        self.async_update_listeners()

    @callback
    def _handle_ws_connection(self, connected: bool) -> None:
        _LOGGER.debug("WebSocket %s", "connected" if connected else "disconnected")
        if connected and not self.last_update_success:
            self.hass.async_create_task(self.async_request_refresh())
        self.async_update_listeners()

    async def async_poll_now(self) -> LampState:
        """Fetch ``/api/info`` outside the schedule and publish it."""
        state = self._accept(await self.client.get_info())
        self.async_update_listeners()
        return state

    async def async_wait_for(
        self, predicate: Callable[[LampState], bool], timeout: float
    ) -> LampState:
        """Wait until the state satisfies ``predicate``.

        Uses WebSocket pushes when connected, otherwise polls over HTTP.
        Raises ``TimeoutError``.
        """
        async with asyncio.timeout(timeout):
            while True:
                changed = self._changed
                if self.data is not None and predicate(self.data):
                    return self.data
                if self.ws.connected:
                    try:
                        async with asyncio.timeout(1.0):
                            await changed.wait()
                    except TimeoutError:
                        # pushes are not sent for HTTP commands, look ourselves
                        await self.async_poll_now()
                else:
                    await self.async_poll_now()
                    await asyncio.sleep(0.3)

    async def async_shutdown(self) -> None:
        """Stop the WebSocket and the debounce timer."""
        if self._debounce is not None:
            self._debounce.cancel()
            self._debounce = None
        await self.ws.stop()
        await super().async_shutdown()

    # availability and repairs -------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the lamp is reachable over the WebSocket or the last poll."""
        return self.ws.connected or self.last_update_success

    def _note_unreachable(self) -> None:
        now = time.monotonic()
        if self._unreachable_since is None:
            self._unreachable_since = now
        elif now - self._unreachable_since >= UNREACHABLE_ISSUE_AFTER:
            self._raise_issue(ISSUE_UNREACHABLE, ir.IssueSeverity.WARNING)

    def _note_reachable(self) -> None:
        self._unreachable_since = None
        for issue in (ISSUE_UNREACHABLE, ISSUE_FIRMWARE):
            ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{self.config_entry.entry_id}")

    def _raise_issue(self, issue: str, severity: ir.IssueSeverity) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{issue}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=severity,
            translation_key=issue,
            translation_placeholders={
                "title": self.config_entry.title,
                "host": self.client.host,
            },
        )

    # commands -----------------------------------------------------------

    def resolve_plugin(self, name: str) -> Plugin:
        """Find a plugin by name or raise a validation error."""
        plugin = self.data.plugin_by_name(name) if self.data else None
        if plugin is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_plugin",
                translation_placeholders={"name": name},
            )
        return plugin

    async def async_select_plugin(self, plugin: Plugin) -> None:
        """Select a plugin like the lamp's web UI does (stops the schedule)."""
        async with lamp_errors():
            if self.ws.connected:
                await self.ws.send({"event": "plugin", "plugin": plugin.id})
                return
            await self.client.set_plugin(plugin.id)
            if self.data is not None and self.data.schedule_active:
                await self.client.stop_schedule()
            await self.async_poll_now()

    async def async_set_brightness(self, value: int) -> None:
        """Set the base brightness."""
        async with lamp_errors():
            if self.ws.connected:
                await self.ws.send({"event": "brightness", "brightness": value})
            else:
                await self.client.set_brightness(value)
                await self.async_poll_now()

    async def async_ws_command(self, payload: dict[str, Any]) -> None:
        """Send a command that only exists on the WebSocket (rotate, persist)."""
        if not self.ws.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="websocket_required"
            )
        async with lamp_errors():
            await self.ws.send(payload)

    async def async_update_brightness_schedule(self, **changes: Any) -> None:
        """Change some fields of the night brightness schedule."""
        if self.data is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_ready")
        new = replace(self.data.brightness_schedule, **changes)
        if new.start_time == new.end_time:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="schedule_times_equal"
            )
        async with lamp_errors():
            saved = await self.client.set_brightness_schedule(new)
        self.data.brightness_schedule = BrightnessSchedule(
            saved.enabled, saved.start_time, saved.end_time, saved.brightness, saved.active
        )
        self.async_update_listeners()

    async def async_plugin_schedule(
        self, action: str, items: list[ScheduleItem] | None = None
    ) -> None:
        """Set, start, stop or clear the plugin schedule."""
        async with lamp_errors():
            if action == "set":
                if not items:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN, translation_key="schedule_empty"
                    )
                await self.client.set_schedule(items)
            elif action == "start":
                await self._schedule_call(self.client.start_schedule)
            elif action == "stop":
                await self._schedule_call(self.client.stop_schedule)
            elif action == "clear":
                await self.client.clear_schedule()
            if not self.ws.connected:
                await self.async_poll_now()

    @staticmethod
    async def _schedule_call(call: Callable[[], Any]) -> None:
        try:
            await call()
        except LampCommandError as err:
            if err.status == 404:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="schedule_empty"
                ) from err
            raise


class lamp_errors:  # used like a function, hence the lower-case name
    """Context manager turning lamp errors into Home Assistant errors."""

    async def __aenter__(self) -> None:
        """Enter."""

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any
    ) -> bool:
        """Translate ``LampError`` subclasses."""
        if isinstance(exc, LampCommandError):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={"error": str(exc)},
            ) from exc
        if isinstance(exc, LampError):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(exc)},
            ) from exc
        return False
