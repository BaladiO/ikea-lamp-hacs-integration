"""Async HTTP client for the OBEGRÄNSAD lamp firmware (ph1p/ikea-led-obegraensad).

This module has no Home Assistant dependency so it can be used from scripts.
See ``docs/lamp-api.md`` for the verified API it talks to.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0
DEFAULT_MIN_INTERVAL = 0.1
DEFAULT_RETRIES = 2
MESSAGE_POOL_SIZE = 10


class LampError(Exception):
    """Base error for all lamp communication problems."""


class LampConnectionError(LampError):
    """The lamp could not be reached or did not answer in time."""


class LampResponseError(LampError):
    """The lamp answered with something that is not what the API promises."""


class LampNotSupportedError(LampResponseError):
    """A required route is missing (HTTP 404), so the firmware is too old."""


class LampCommandError(LampError):
    """The lamp rejected a command (HTTP 4xx with an error message)."""

    def __init__(self, message: str, status: int) -> None:
        """Store the firmware's error message and HTTP status."""
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Plugin:
    """A display plugin as reported by the lamp."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class BrightnessSchedule:
    """The firmware's night brightness schedule."""

    enabled: bool
    start_time: str
    end_time: str
    brightness: int
    active: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BrightnessSchedule:
        """Build from the ``brightnessSchedule`` object of the lamp."""
        return cls(
            enabled=bool(data["enabled"]),
            start_time=str(data["startTime"]),
            end_time=str(data["endTime"]),
            brightness=int(data["brightness"]),
            active=bool(data.get("active", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the body expected by ``PUT /api/brightness-schedule``."""
        return {
            "enabled": self.enabled,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "brightness": self.brightness,
        }


@dataclass(frozen=True, slots=True)
class ScheduleItem:
    """One entry of the plugin schedule."""

    plugin_id: int
    duration: int


@dataclass(slots=True)
class LampState:
    """Lamp state merged from ``/api/info`` and WebSocket ``info`` pushes.

    The WebSocket push lacks the diagnostic fields, so those stay ``None`` until
    the first HTTP poll and keep their last value afterwards.
    """

    plugin_id: int
    rotation: int
    base_brightness: int
    brightness: int
    brightness_schedule: BrightnessSchedule
    schedule_active: bool
    schedule: list[ScheduleItem]
    plugins: list[Plugin]
    status: int = 0
    rows: int = 16
    cols: int = 16
    persist_plugin_id: int | None = None
    rssi: int | None = None
    uptime: int | None = None
    free_heap: int | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    reset_reason: str | None = None
    frame: list[int] | None = field(default=None, repr=False)

    @classmethod
    def from_info(cls, data: Mapping[str, Any]) -> LampState:
        """Parse an ``/api/info`` response or a WebSocket ``info`` frame."""
        try:
            state = cls(
                plugin_id=int(data["plugin"]),
                rotation=int(data["rotation"]),
                base_brightness=int(data["baseBrightness"]),
                brightness=int(data["brightness"]),
                brightness_schedule=BrightnessSchedule.from_dict(data["brightnessSchedule"]),
                schedule_active=bool(data["scheduleActive"]),
                schedule=[
                    ScheduleItem(int(item["pluginId"]), int(item["duration"]))
                    for item in data.get("schedule", [])
                ],
                plugins=[Plugin(int(p["id"]), str(p["name"])) for p in data["plugins"]],
                status=int(data.get("status", 0)),
                rows=int(data.get("rows", 16)),
                cols=int(data.get("cols", 16)),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise LampResponseError(f"Unexpected info payload: {err!r}") from err
        state.update_extras(data)
        return state

    def update_extras(self, data: Mapping[str, Any]) -> None:
        """Copy the optional fields present in ``data``."""
        if "persist-plugin" in data:
            self.persist_plugin_id = int(data["persist-plugin"])
        if "rssi" in data:
            self.rssi = int(data["rssi"])
        if "uptime" in data:
            self.uptime = int(data["uptime"])
        if "freeHeap" in data:
            self.free_heap = int(data["freeHeap"])
        if "ipAddress" in data:
            self.ip_address = str(data["ipAddress"])
        if "macAddress" in data:
            self.mac_address = str(data["macAddress"])
        if "resetReason" in data:
            self.reset_reason = str(data["resetReason"])
        if isinstance(data.get("data"), list):
            self.frame = [int(v) for v in data["data"]]

    def merge(self, newer: LampState) -> LampState:
        """Return ``newer`` with diagnostic fields filled in from ``self``."""
        for name in (
            "persist_plugin_id",
            "rssi",
            "uptime",
            "free_heap",
            "ip_address",
            "mac_address",
            "reset_reason",
            "frame",
        ):
            if getattr(newer, name) is None:
                setattr(newer, name, getattr(self, name))
        return newer

    @property
    def plugin(self) -> Plugin | None:
        """The active plugin, if it is in the plugin list."""
        return self.plugin_by_id(self.plugin_id)

    def plugin_by_id(self, plugin_id: int) -> Plugin | None:
        """Look up a plugin by id."""
        return next((p for p in self.plugins if p.id == plugin_id), None)

    def plugin_by_name(self, name: str) -> Plugin | None:
        """Look up a plugin by name, case-insensitive."""
        wanted = name.casefold()
        return next((p for p in self.plugins if p.name.casefold() == wanted), None)


def normalise_host(host: str) -> str:
    """Turn user input like ``http://1.2.3.4/`` into ``1.2.3.4``."""
    host = host.strip()
    for prefix in ("http://", "https://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.split("/", 1)[0]


class LampClient:
    """HTTP client for one lamp.

    Requests are serialised with a short gap between them because the ESP32
    handles only a few connections at a time. Connection errors and timeouts are
    retried; every command of this API is idempotent, so a retry is safe.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        """Create a client; ``session`` is owned by the caller."""
        self._session = session
        self.host = normalise_host(host)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._min_interval = min_interval
        self._retries = retries
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    @property
    def base_url(self) -> str:
        """Base URL of the lamp."""
        return f"http://{self.host}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        """Send one request and return parsed JSON (or bytes when ``raw``)."""
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                async with self._lock:
                    wait = self._last_request + self._min_interval - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    try:
                        async with self._session.request(
                            method,
                            url,
                            params=params,
                            json=json_body,
                            data=form,
                            timeout=self._timeout,
                        ) as resp:
                            body = await resp.read()
                            status = resp.status
                    finally:
                        self._last_request = time.monotonic()
            except (TimeoutError, aiohttp.ClientConnectionError) as err:
                if attempt >= self._retries:
                    raise LampConnectionError(f"Cannot reach lamp at {self.host}: {err!r}") from err
                attempt += 1
                _LOGGER.debug("Retrying %s %s after %r (%d)", method, path, err, attempt)
                continue
            except aiohttp.ClientError as err:
                raise LampResponseError(f"{method} {path} failed: {err!r}") from err
            break

        if status == 404 and not body.startswith(b"{"):
            raise LampNotSupportedError(f"{method} {path} is not supported by this firmware")
        if raw and status == 200:
            return body
        try:
            data = json.loads(body) if body else None
        except ValueError as err:
            raise LampResponseError(f"{method} {path}: invalid JSON") from err
        if status >= 400:
            message = data.get("message") if isinstance(data, dict) else None
            raise LampCommandError(message or f"HTTP {status}", status)
        return data

    async def get_info(self) -> LampState:
        """Fetch the full state."""
        data = await self._request("GET", "/api/info")
        if not isinstance(data, dict):
            raise LampResponseError("/api/info did not return an object")
        return LampState.from_info(data)

    async def get_frame(self) -> bytes:
        """Return the current frame, one brightness byte per pixel."""
        data: bytes = await self._request("GET", "/api/data", raw=True)
        return data

    async def get_config(self) -> dict[str, Any]:
        """Return the lamp's config (weather location, NTP, time zone)."""
        data = await self._request("GET", "/api/config")
        if not isinstance(data, dict):
            raise LampResponseError("/api/config did not return an object")
        return data

    async def set_plugin(self, plugin_id: int) -> None:
        """Select a plugin. Blocks for ~800 ms while the lamp shows the id."""
        await self._request("PATCH", "/api/plugin", params={"id": plugin_id})

    async def set_brightness(self, value: int) -> None:
        """Set the base brightness (0-255)."""
        if not 0 <= value <= 255:
            raise ValueError("brightness must be 0-255")
        await self._request("PATCH", "/api/brightness", params={"value": value})

    async def set_brightness_schedule(self, schedule: BrightnessSchedule) -> BrightnessSchedule:
        """Store the night brightness schedule and return what the lamp saved."""
        data = await self._request(
            "PUT", "/api/brightness-schedule", json_body=schedule.to_payload()
        )
        try:
            return BrightnessSchedule.from_dict(data["brightnessSchedule"])
        except (KeyError, TypeError, ValueError) as err:
            raise LampResponseError("Unexpected brightness schedule response") from err

    async def send_message(
        self,
        text: str,
        *,
        message_id: int,
        repeat: int = 0,
        delay: int = 50,
        graph: Sequence[int] | None = None,
        miny: int = 0,
        maxy: int = 15,
    ) -> None:
        """Queue a message on the lamp.

        A message with the same id is replaced. The firmware drops messages
        silently when its pool of 10 is full; the caller must track that.
        """
        params: dict[str, str | int] = {
            "text": text,
            "repeat": repeat,
            "id": message_id,
            "delay": delay,
            "miny": miny,
            "maxy": maxy,
        }
        if graph:
            params["graph"] = ",".join(str(int(v)) for v in graph)
        await self._request("GET", "/api/message", params=params)

    async def remove_message(self, message_id: int) -> None:
        """Remove a message; unknown ids are not an error."""
        await self._request("GET", "/api/removemessage", params={"id": message_id})

    async def set_schedule(self, items: Sequence[ScheduleItem]) -> None:
        """Replace the plugin schedule. The firmware starts it immediately."""
        payload = json.dumps(
            [{"pluginId": item.plugin_id, "duration": item.duration} for item in items]
        )
        await self._request("POST", "/api/schedule", form={"schedule": payload})

    async def start_schedule(self) -> None:
        """Start the stored plugin schedule (fails when it is empty)."""
        await self._request("GET", "/api/schedule/start")

    async def stop_schedule(self) -> None:
        """Stop the plugin schedule (fails when it is empty)."""
        await self._request("GET", "/api/schedule/stop")

    async def clear_schedule(self) -> None:
        """Delete the plugin schedule."""
        await self._request("GET", "/api/schedule/clear")
