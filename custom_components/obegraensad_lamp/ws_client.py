"""Single WebSocket connection to the lamp with reconnect and backoff.

This module has no Home Assistant dependency so it can be used from scripts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import json
import logging
import random
from typing import Any

import aiohttp

from .api import LampConnectionError, normalise_host

_LOGGER = logging.getLogger(__name__)

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
HEARTBEAT = 30.0
CONNECT_TIMEOUT = 10.0


class LampWebSocket:
    """Keeps exactly one WebSocket open to the lamp.

    ``on_info`` gets every ``info`` push as a dict. ``on_connection`` gets
    ``True`` after a connection is ready and ``False`` when it is lost. Both
    callbacks run in the event loop and must not block.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        on_info: Callable[[dict[str, Any]], None],
        on_connection: Callable[[bool], None] | None = None,
        *,
        max_backoff: float = MAX_BACKOFF,
        initial_backoff: float = INITIAL_BACKOFF,
    ) -> None:
        """Prepare the client; call :meth:`start` to connect."""
        self._session = session
        self._host = normalise_host(host)
        self._on_info = on_info
        self._on_connection = on_connection
        self._max_backoff = max_backoff
        self._initial_backoff = initial_backoff
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._closing = False

    @property
    def connected(self) -> bool:
        """Whether the socket is open and ready."""
        return self._ws is not None and not self._ws.closed

    @property
    def url(self) -> str:
        """WebSocket URL of the lamp."""
        return f"http://{self._host}/ws"

    def start(self) -> None:
        """Start the background connection task (idempotent)."""
        if self._task is None or self._task.done():
            self._closing = False
            self._task = asyncio.get_running_loop().create_task(
                self._run(), name=f"obegraensad_ws_{self._host}"
            )

    async def stop(self) -> None:
        """Close the socket and stop reconnecting."""
        self._closing = True
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def send(self, payload: dict[str, Any]) -> None:
        """Send one event frame; raises when not connected."""
        ws = self._ws
        if ws is None or ws.closed:
            raise LampConnectionError("WebSocket is not connected")
        try:
            await ws.send_str(json.dumps(payload))
        except (ConnectionError, aiohttp.ClientError) as err:
            raise LampConnectionError(f"WebSocket send failed: {err!r}") from err

    async def _run(self) -> None:
        backoff = self._initial_backoff
        while not self._closing:
            try:
                await self._connect_and_listen()
                # a session that worked resets the backoff
                backoff = self._initial_backoff
            except (TimeoutError, aiohttp.ClientError, ConnectionError, OSError) as err:
                _LOGGER.debug("WebSocket to %s failed: %r", self._host, err)
            if self._closing:
                break
            delay = backoff * random.uniform(0.8, 1.2)
            _LOGGER.debug("Reconnecting WebSocket to %s in %.1f s", self._host, delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, self._max_backoff)

    async def _connect_and_listen(self) -> None:
        ws = await self._session.ws_connect(
            self.url,
            heartbeat=HEARTBEAT,
            timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=CONNECT_TIMEOUT),
            autoping=True,
        )
        self._ws = ws
        try:
            # the firmware subscribes every new client to the binary live preview
            await ws.send_str(json.dumps({"event": "live-preview", "enabled": False}))
            _LOGGER.debug("WebSocket connected to %s", self._host)
            self._notify_connection(True)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.debug("WebSocket error from %s: %r", self._host, ws.exception())
                    break
                # binary live-preview frames are ignored
        finally:
            self._ws = None
            # notify before awaiting, a cancel during close() must not skip it
            self._notify_connection(False)
            if not ws.closed:
                await ws.close()

    def _handle_text(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON WebSocket frame: %.80s", raw)
            return
        if isinstance(data, dict) and data.get("event") == "info":
            self._on_info(data)

    def _notify_connection(self, connected: bool) -> None:
        if self._on_connection is not None:
            self._on_connection(connected)
