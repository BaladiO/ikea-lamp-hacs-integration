"""In-process fake of the lamp firmware's HTTP and WebSocket API.

It mirrors the behaviour documented in docs/lamp-api.md closely enough for the
client and integration tests, including the quirks (silent message drop when
the pool is full, live preview on connect, schedule rules).
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from aiohttp import WSMsgType, web

PLUGIN_NAMES = [
    "Draw", "Breakout", "Snake", "GameOfLife", "Stars", "Lines", "Circle", "Rain",
    "Matrix Rain", "Firework", "Blobs", "Spiral", "Wave", "Checkerboard", "Radar",
    "Bubbles", "Comet", "Fireflies", "Meteor Shower", "Scanlines", "Sparkle Field",
    "Wave Bars", "BigPong", "Auto Walker", "Bouncing Ball", "Face", "Falling Sand",
    "Flappy Bird", "Space Invaders", "Spotlight", "Tetris", "Tron", "Big Clock",
    "Clock", "PongClock", "Ticking Clock", "Weather", "Animation", "DDP", "ArtNet",
]  # fmt: skip

MAC = "E8:6B:EA:C4:41:F0"


def default_info() -> dict[str, Any]:
    """The /api/info payload observed on the real lamp."""
    return {
        "rows": 16,
        "cols": 16,
        "status": 0,
        "plugin": 37,
        "rotation": 0,
        "baseBrightness": 255,
        "brightness": 255,
        "brightnessSchedule": {
            "enabled": False,
            "startTime": "22:00",
            "endTime": "07:00",
            "brightness": 20,
            "active": False,
        },
        "scheduleActive": False,
        "rssi": -65,
        "uptime": 730,
        "freeHeap": 104104,
        "ipAddress": "192.168.100.45",
        "macAddress": MAC,
        "resetReason": "poweron",
        "schedule": [],
        "plugins": [{"id": i + 1, "name": n} for i, n in enumerate(PLUGIN_NAMES)],
    }


class FakeLamp:
    """State plus an aiohttp app that behaves like the firmware."""

    POOL_SIZE = 10

    def __init__(self) -> None:
        """Start with the real lamp's observed state."""
        self.info = default_info()
        self.persist_plugin = 12
        self.messages: dict[int, dict[str, Any]] = {}
        self.dropped_messages = 0
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.ws_events: list[dict[str, Any]] = []
        self.ws_clients: list[web.WebSocketResponse] = []
        self.live_preview: dict[int, bool] = {}
        self.fail_with: int | None = None  # force an HTTP status on every route
        self.missing_routes: set[str] = set()
        self.frame = [0] * 256
        self.ddp_packets = 0
        self.ddp_port = 0
        self._udp: asyncio.DatagramTransport | None = None

    async def start_udp(self) -> int:
        """Listen for DDP on a free UDP port of 127.0.0.1 and return it."""
        lamp = self

        class _Protocol(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                lamp.ddp_received(data)

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(_Protocol, local_addr=("127.0.0.1", 0))
        self._udp = transport
        self.ddp_port = transport.get_extra_info("sockname")[1]
        return self.ddp_port

    def stop_udp(self) -> None:
        """Close the UDP endpoint."""
        if self._udp is not None:
            self._udp.close()
            self._udp = None

    def ddp_received(self, packet: bytes) -> None:
        """What DDPPlugin.cpp does, but only while the DDP plugin is active."""
        if self.info["plugin"] != 39 or len(packet) < 10:
            return
        data = packet[10:]
        count = min(len(data) // 3, 256)
        values = [sum(data[i * 3 : i * 3 + 3]) // 3 for i in range(count)]
        values = [v if v > 4 else 0 for v in values]
        if count == 1:
            self.frame = values * 256
        else:
            self.frame[:count] = values
        self.ddp_packets += 1

    def app(self) -> web.Application:
        """Build the aiohttp application."""
        app = web.Application(middlewares=[self._middleware])
        r = app.router
        r.add_get("/api/info", self._info)
        r.add_patch("/api/plugin", self._plugin)
        r.add_patch("/api/brightness", self._brightness)
        r.add_put("/api/brightness-schedule", self._brightness_schedule)
        r.add_get("/api/data", self._data)
        r.add_get("/api/message", self._message)
        r.add_get("/api/removemessage", self._remove_message)
        r.add_post("/api/schedule", self._schedule)
        r.add_get("/api/schedule/start", self._schedule_start)
        r.add_get("/api/schedule/stop", self._schedule_stop)
        r.add_get("/api/schedule/clear", self._schedule_clear)
        r.add_get("/api/config", self._config)
        r.add_get("/ws", self._ws)
        return app

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        self.requests.append((request.method, request.path, dict(request.query)))
        if request.path in self.missing_routes:
            return web.Response(status=404, text="Page not found!")
        if self.fail_with is not None and request.path != "/ws":
            return web.Response(status=self.fail_with, text="boom")
        try:
            return await handler(request)
        except web.HTTPNotFound:
            return web.Response(status=404, text="Page not found!")

    # helpers ------------------------------------------------------------

    @staticmethod
    def _int(request: web.Request, name: str) -> int:
        """Arduino toInt(): missing or junk becomes 0."""
        try:
            return int(request.query.get(name, "0"))
        except ValueError:
            return 0

    @staticmethod
    def _ok(message: str) -> web.Response:
        return web.json_response({"status": "success", "message": message})

    @staticmethod
    def _err(status: int, message: str) -> web.Response:
        return web.json_response({"error": True, "message": message}, status=status)

    def ws_payload(self) -> dict[str, Any]:
        """The info frame the firmware pushes over the WebSocket."""
        keys = (
            "status", "plugin", "rotation", "baseBrightness", "brightness",
            "brightnessSchedule", "scheduleActive", "schedule", "plugins",
        )  # fmt: skip
        payload = {k: copy.deepcopy(self.info[k]) for k in keys}
        payload.update({"event": "info", "persist-plugin": self.persist_plugin, "data": self.frame})
        return payload

    async def push_info(self) -> None:
        """Send an info frame to all WebSocket clients."""
        text = json.dumps(self.ws_payload())
        for ws in list(self.ws_clients):
            if not ws.closed:
                await ws.send_str(text)

    async def set_plugin(self, plugin_id: int, *, push: bool = True) -> None:
        """Simulate a plugin change made on the lamp (button, web UI)."""
        self.info["plugin"] = plugin_id
        if push:
            await self.push_info()

    async def drop_ws_clients(self) -> None:
        """Close every WebSocket from the server side."""
        for ws in list(self.ws_clients):
            await ws.close()

    def _set_plugin(self, plugin_id: int) -> bool:
        if not any(p["id"] == plugin_id for p in self.info["plugins"]):
            return False
        self.info["plugin"] = plugin_id
        return True

    # routes -------------------------------------------------------------

    async def _info(self, request: web.Request) -> web.Response:
        return web.json_response(self.info)

    async def _plugin(self, request: web.Request) -> web.Response:
        plugin_id = self._int(request, "id")
        if self._set_plugin(plugin_id):
            return self._ok("Plugin set successfully")
        return self._err(422, f"Could not set plugin to id {plugin_id}")

    async def _brightness(self, request: web.Request) -> web.Response:
        value = self._int(request, "value")
        if not 0 <= value <= 255:
            return self._err(422, f"Invalid brightness value: {value} - must be between 0 and 255.")
        self.info["baseBrightness"] = value
        self.info["brightness"] = value
        return self._ok("Brightness set successfully")

    async def _brightness_schedule(self, request: web.Request) -> web.Response:
        try:
            body = json.loads(await request.text())
        except ValueError:
            return self._err(400, "Invalid JSON payload")
        if (
            not isinstance(body.get("enabled"), bool)
            or not isinstance(body.get("startTime"), str)
            or not isinstance(body.get("endTime"), str)
            or not isinstance(body.get("brightness"), int)
            or not 0 <= body["brightness"] <= 255
        ):
            return self._err(422, "Invalid scheduled brightness configuration")
        if body["startTime"] == body["endTime"]:
            return self._err(422, "Start and end times must differ")
        self.info["brightnessSchedule"].update(
            {k: body[k] for k in ("enabled", "startTime", "endTime", "brightness")}
        )
        await self.push_info()
        return web.json_response(
            {
                "baseBrightness": self.info["baseBrightness"],
                "brightness": self.info["brightness"],
                "brightnessSchedule": self.info["brightnessSchedule"],
            }
        )

    async def _data(self, request: web.Request) -> web.Response:
        return web.Response(body=bytes(self.frame), content_type="application/octet-stream")

    async def _message(self, request: web.Request) -> web.Response:
        miny = self._int(request, "miny")
        maxy = self._int(request, "maxy") or 15
        if maxy < miny:
            return self._err(422, "maxy must be >= miny and the range must fit an int")
        graph_raw = request.query.get("graph", "")
        try:
            graph = [int(v) for v in graph_raw.split(",") if v]
        except ValueError:
            return self._err(422, "graph must be a comma-separated list of integers")
        message_id = self._int(request, "id")
        self.messages.pop(message_id, None)
        if len(self.messages) >= self.POOL_SIZE:
            self.dropped_messages += 1
        else:
            self.messages[message_id] = {
                "text": request.query.get("text", ""),
                "repeat": self._int(request, "repeat"),
                "delay": self._int(request, "delay") or 50,
                "graph": graph,
                "miny": miny,
                "maxy": maxy,
            }
        return self._ok("Message received")

    async def _remove_message(self, request: web.Request) -> web.Response:
        self.messages.pop(self._int(request, "id"), None)
        return self._ok("Message removed")

    async def _schedule(self, request: web.Request) -> web.Response:
        form = await request.post()
        raw = form.get("schedule", "")
        try:
            items = json.loads(str(raw)) if raw else None
        except ValueError:
            items = None
        if items is None:
            return self._err(400, "Schedule cannot be set")
        self.info["schedule"] = [
            {"pluginId": i["pluginId"], "duration": i["duration"]} for i in items
        ]
        self.info["scheduleActive"] = bool(items)
        await self.push_info()
        return self._ok("Schedule updated")

    async def _schedule_start(self, request: web.Request) -> web.Response:
        if not self.info["schedule"]:
            return self._err(404, "No schedule found")
        self.info["scheduleActive"] = True
        await self.push_info()
        return self._ok("Schedule started")

    async def _schedule_stop(self, request: web.Request) -> web.Response:
        if not self.info["schedule"]:
            return self._err(404, "No schedule found")
        self.info["scheduleActive"] = False
        await self.push_info()
        return self._ok("Schedule stopped")

    async def _schedule_clear(self, request: web.Request) -> web.Response:
        self.info["schedule"] = []
        self.info["scheduleActive"] = False
        await self.push_info()
        return self._ok("Schedule cleared")

    async def _config(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "weatherLocation": "Casablanca",
                "ntpServer": "de.pool.ntp.org",
                "tzInfo": "CET-1CEST,M3.5.0,M10.5.0/3",
                "autoStartSchedule": False,
            }
        )

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.append(ws)
        self.live_preview[id(ws)] = True
        await ws.send_str(json.dumps(self.ws_payload()))
        await ws.send_bytes(bytes(self.frame))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                event = json.loads(msg.data)
                self.ws_events.append(event)
                await self._ws_event(ws, event)
        finally:
            self.ws_clients.remove(ws)
        return ws

    async def _ws_event(self, ws: web.WebSocketResponse, event: dict[str, Any]) -> None:
        name = event.get("event")
        if name == "plugin":
            self.info["scheduleActive"] = False
            self._set_plugin(int(event.get("plugin", 0)))
        elif name == "persist-plugin":
            self.persist_plugin = self.info["plugin"]
        elif name == "rotate":
            step = 1 if event.get("direction") == "right" else 3
            self.info["rotation"] = (self.info["rotation"] + step) % 4
        elif name == "brightness":
            value = int(event.get("brightness", 0)) & 0xFF
            self.info["baseBrightness"] = value
            self.info["brightness"] = value
        elif name == "live-preview":
            self.live_preview[id(ws)] = bool(event.get("enabled", True))
            return
        elif name != "info":
            return
        await self.push_info()
