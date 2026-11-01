"""Temporary-display engine: show frames over DDP, then restore the plugin.

One display runs at a time. A session starts by remembering the active plugin
(by name) and whether the plugin schedule was running, stopping the schedule,
and switching to the DDP plugin. Frames are resent while held because UDP is
lossy. Requests that follow each other reuse the session, so the lamp flashes
its plugin id only once. When nothing is left the previous plugin is restored
and the schedule restarted, unless someone changed the plugin meanwhile; that
is taken as the user taking over, and nothing is restored.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
import itertools
import logging
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .api import LampError
from .const import (
    CONF_DDP_PORT,
    CONF_RESTORE,
    DDP_PLUGIN_NAME,
    DEFAULT_DDP_PORT,
    DEFAULT_RESTORE,
    DOMAIN,
)
from .ddp import DdpSender

if TYPE_CHECKING:
    from .coordinator import LampCoordinator, ObegraensadConfigEntry

_LOGGER = logging.getLogger(__name__)

Priority = Literal["low", "normal", "high"]
RANK: dict[str, int] = {"low": 0, "normal": 1, "high": 2}

RESEND_INTERVAL = 1.5
# open-ended holds resend often at first, then rarely
RESEND_FAST_FOR = 10.0
RESEND_SLOW_INTERVAL = 30.0
SWITCH_TIMEOUT = 8.0
STOP_TIMEOUT = 15.0


@dataclass
class DisplayRequest:
    """One frame to show."""

    frame: list[int]
    duration: float | None
    restore: bool
    priority: Priority
    seq: int
    label: str = "frame"
    shown: asyncio.Future[None] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    @property
    def sort_key(self) -> tuple[int, int]:
        """Higher priority first, then first come first served."""
        return (-RANK[self.priority], self.seq)


@dataclass
class _Session:
    restore_to: str | None
    schedule_was_active: bool
    ddp_id: int
    base_brightness: int
    restore: bool = True
    taken_over: bool = False


class DisplayEngine:
    """Shows temporary frames on one lamp."""

    def __init__(
        self, hass: HomeAssistant, entry: ObegraensadConfigEntry, coordinator: LampCoordinator
    ) -> None:
        """Read options and hook into Home Assistant's shutdown."""
        self.hass = hass
        self.coordinator = coordinator
        self.default_restore = bool(entry.options.get(CONF_RESTORE, DEFAULT_RESTORE))
        port = int(entry.options.get(CONF_DDP_PORT, DEFAULT_DDP_PORT))
        self._sender = DdpSender(coordinator.client.host.rsplit(":", 1)[0], port)
        self._pending: list[DisplayRequest] = []
        self._current: DisplayRequest | None = None
        self._session: _Session | None = None
        self._task: asyncio.Task[None] | None = None
        self._interrupt = asyncio.Event()
        self._release = False
        self._switching = False
        self._stopped = False
        self._seq = itertools.count()
        self._unsub_state = coordinator.async_add_listener(self._on_state)
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_hass_stop)
        )

    # public API ---------------------------------------------------------

    @property
    def active(self) -> bool:
        """Whether a temporary display holds the lamp."""
        return self._session is not None

    @property
    def busy(self) -> bool:
        """Whether something is shown or waiting."""
        return self._current is not None or bool(self._pending)

    async def async_show(
        self,
        frame: Sequence[int],
        *,
        duration: float | None,
        restore: bool | None = None,
        priority: Priority = "normal",
        drop_if_busy: bool = False,
        label: str = "frame",
    ) -> dict[str, Any]:
        """Show ``frame`` for ``duration`` seconds (``None`` = until released).

        Waits until the frame is on the lamp when it can start right away;
        otherwise returns ``queued`` immediately. ``dropped`` is returned for a
        low-priority request with ``drop_if_busy`` while the engine is busy.
        """
        if self._stopped:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_ready")
        data = self.coordinator.data
        if len(frame) != data.rows * data.cols:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="frame_size")
        busy = self.busy
        if busy and drop_if_busy and priority == "low":
            _LOGGER.debug("Dropped low-priority %s, display busy", label)
            return {"status": "dropped"}
        request = DisplayRequest(
            frame=list(frame),
            duration=duration,
            restore=self.default_restore if restore is None else restore,
            priority=priority,
            seq=next(self._seq),
            label=label,
        )
        self._pending.append(request)
        self._pending.sort(key=lambda r: r.sort_key)
        current = self._current
        if current is not None and (
            RANK[priority] > RANK[current.priority] or current.duration is None
        ):
            # high pre-empts lower ones; open-ended holds give way to anything
            self._interrupt.set()
        self._ensure_worker()
        if busy:
            return {"status": "queued"}
        await asyncio.shield(request.shown)
        return {"status": "shown"}

    async def async_release(self) -> None:
        """End the current display and drop waiting ones, restoring the plugin."""
        if not self.busy and self._session is None:
            return
        self._drop_pending("released")
        self._release = True
        self._interrupt.set()
        self._ensure_worker()
        if self._task is not None:
            await asyncio.shield(self._task)

    async def async_stop(self) -> None:
        """Stop for good (unload or shutdown) and leave the lamp restored."""
        if self._stopped:
            return
        self._stopped = True
        self._unsub_state()
        self._drop_pending("stopped")
        self._release = True
        self._interrupt.set()
        if self._task is not None:
            try:
                async with asyncio.timeout(STOP_TIMEOUT):
                    await asyncio.shield(self._task)
            except TimeoutError:
                _LOGGER.warning("Display engine did not stop in time")
                self._task.cancel()
        if self._session is not None:
            await self._end_session()
        self._sender.close()

    # state tracking -----------------------------------------------------

    @callback
    def _on_state(self) -> None:
        session = self._session
        data = self.coordinator.data
        if session is None or self._switching or data is None or session.taken_over:
            return
        if data.plugin_id != session.ddp_id:
            plugin = data.plugin
            _LOGGER.debug(
                "Plugin changed to %s during a temporary display; not restoring",
                plugin.name if plugin else data.plugin_id,
            )
            session.taken_over = True
            self._interrupt.set()

    async def _on_hass_stop(self, _event: Event) -> None:
        await self.async_stop()

    # worker -------------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_background_task(
                self._run(), f"{DOMAIN} display {self.coordinator.client.host}"
            )

    def _drop_pending(self, reason: str) -> None:
        for request in self._pending:
            if not request.shown.done():
                request.shown.set_exception(
                    HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="display_cancelled",
                        translation_placeholders={"reason": reason},
                    )
                )
                # nobody may be awaiting a queued request
                request.shown.exception()
        self._pending.clear()

    @staticmethod
    def _fail(request: DisplayRequest, err: Exception) -> None:
        """Report a failed display to whoever waits for it."""
        if isinstance(err, HomeAssistantError):
            error = err
        elif isinstance(err, (LampError, OSError, TimeoutError)):
            _LOGGER.warning("Temporary display failed: %s", err)
            error = HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err) or type(err).__name__},
            )
        else:
            _LOGGER.exception("Unexpected error in the display engine")
            error = HomeAssistantError(str(err))
        if not request.shown.done():
            request.shown.set_exception(error)
            request.shown.exception()  # mark retrieved; the caller may be gone

    async def _run(self) -> None:
        while True:
            await self._run_session()
            # a request may have arrived while the session was being restored
            if not self._pending or self._stopped:
                return

    async def _run_session(self) -> None:
        try:
            while self._pending and not self._release:
                request = self._pending.pop(0)
                self._current = request
                self._interrupt.clear()
                try:
                    await self._show(request)
                except Exception as err:  # the caller must never wait forever
                    self._fail(request, err)
                    self._drop_pending("previous display failed")
                    break
                finally:
                    self._current = None
                if self._session is not None and self._session.taken_over:
                    self._drop_pending("plugin changed")
        finally:
            self._release = False
            if self._session is not None:
                await self._end_session()

    async def _show(self, request: DisplayRequest) -> None:
        if self._session is None:
            await self._begin_session()
        session = self._session
        assert session is not None
        session.restore = request.restore
        loop = asyncio.get_running_loop()
        await self._sender.send_frame(request.frame)
        if not request.shown.done():
            request.shown.set_result(None)
        _LOGGER.debug("Showing %s (%s s, %s)", request.label, request.duration, request.priority)

        start = loop.time()
        deadline = None if request.duration is None else start + request.duration
        while True:
            now = loop.time()
            if deadline is not None:
                wait = min(RESEND_INTERVAL, deadline - now)
            elif now - start < RESEND_FAST_FOR:
                wait = RESEND_INTERVAL
            else:
                wait = RESEND_SLOW_INTERVAL
            if wait <= 0:
                return
            try:
                async with asyncio.timeout(wait):
                    await self._interrupt.wait()
            except TimeoutError:
                pass
            if self._interrupt.is_set() or session.taken_over or self._release:
                return
            if deadline is not None and loop.time() >= deadline:
                return
            await self._sender.send_frame(request.frame)

    async def _begin_session(self) -> None:
        coordinator = self.coordinator
        data = coordinator.data
        ddp = data.plugin_by_name(DDP_PLUGIN_NAME)
        if ddp is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_ddp_plugin")
        current = data.plugin
        session = _Session(
            restore_to=current.name if current and current.id != ddp.id else None,
            schedule_was_active=data.schedule_active,
            ddp_id=ddp.id,
            base_brightness=data.base_brightness,
        )
        self._switching = True
        try:
            if data.schedule_active:
                # the scheduler would switch away from DDP in the middle
                await coordinator.client.stop_schedule()
            self._session = session
            if data.plugin_id != ddp.id:
                await coordinator.client.set_plugin(ddp.id)
            await coordinator.async_wait_for(lambda s: s.plugin_id == ddp.id, SWITCH_TIMEOUT)
        except BaseException:
            if self._session is session:
                # put things back as far as they got
                await self._end_session()
            raise
        finally:
            self._switching = False
        _LOGGER.debug("Display session started, will restore %s", session.restore_to)

    async def _end_session(self) -> None:
        session = self._session
        self._session = None
        if session is None:
            return
        if session.taken_over:
            return
        if not session.restore:
            _LOGGER.debug("Leaving the lamp on DDP (restore disabled)")
            return
        coordinator = self.coordinator
        self._switching = True
        try:
            if session.restore_to is not None and coordinator.data is not None:
                plugin = coordinator.data.plugin_by_name(session.restore_to)
                if plugin is not None and coordinator.data.plugin_id == session.ddp_id:
                    await coordinator.client.set_plugin(plugin.id)
            if session.schedule_was_active:
                await coordinator.client.start_schedule()
            await coordinator.async_poll_now()
            _LOGGER.debug("Restored %s", session.restore_to)
        except LampError as err:
            _LOGGER.warning("Could not restore the lamp after a temporary display: %s", err)
        finally:
            self._switching = False
