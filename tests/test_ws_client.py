"""Tests for the WebSocket client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

from custom_components.obegraensad_lamp.api import LampConnectionError
from custom_components.obegraensad_lamp.ws_client import LampWebSocket

from .fake_lamp import FakeLamp

pytestmark = pytest.mark.usefixtures("socket_enabled")


async def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    """Poll until ``predicate`` is true."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """A plain aiohttp session."""
    async with aiohttp.ClientSession() as s:
        yield s


async def test_connect_opt_out_and_receive(
    session: aiohttp.ClientSession, lamp: FakeLamp, lamp_host: str
) -> None:
    """The client opts out of live preview and forwards info pushes."""
    infos: list[dict[str, Any]] = []
    states: list[bool] = []
    ws = LampWebSocket(session, lamp_host, infos.append, states.append)
    ws.start()
    try:
        await wait_for(lambda: len(infos) == 1 and states == [True])
        await wait_for(lambda: lamp.live_preview and not any(lamp.live_preview.values()))
        assert ws.connected
        assert lamp.ws_events[0] == {"event": "live-preview", "enabled": False}

        await ws.send({"event": "rotate", "direction": "right"})
        await wait_for(lambda: len(infos) == 2)
        assert infos[-1]["rotation"] == 1
        assert len(lamp.ws_clients) == 1
    finally:
        await ws.stop()
    assert states[-1] is False
    assert not ws.connected


async def test_reconnects_after_drop(
    session: aiohttp.ClientSession, lamp: FakeLamp, lamp_host: str
) -> None:
    """A server-side close leads to exactly one new connection."""
    infos: list[dict[str, Any]] = []
    states: list[bool] = []
    ws = LampWebSocket(session, lamp_host, infos.append, states.append, initial_backoff=0.05)
    ws.start()
    try:
        await wait_for(lambda: states == [True])
        await lamp.drop_ws_clients()
        await wait_for(lambda: states == [True, False, True])
        assert len(lamp.ws_clients) == 1
    finally:
        await ws.stop()


async def test_backoff_while_unreachable(lamp: FakeLamp) -> None:
    """While the lamp is down, attempts back off, then connect once it is up."""
    server = TestServer(lamp.app(), host="127.0.0.1")
    await server.start_server()
    port = server.port
    await server.close()

    states: list[bool] = []
    async with aiohttp.ClientSession() as session:
        ws = LampWebSocket(
            session, f"127.0.0.1:{port}", lambda _: None, states.append,
            initial_backoff=0.05, max_backoff=0.2,
        )  # fmt: skip
        ws.start()
        await asyncio.sleep(0.3)
        assert states == []
        with pytest.raises(LampConnectionError):
            await ws.send({"event": "info"})

        server = TestServer(lamp.app(), host="127.0.0.1", port=port)
        await server.start_server()
        try:
            await wait_for(lambda: states == [True])
        finally:
            await ws.stop()
            await server.close()


async def test_ignores_bad_frames(
    session: aiohttp.ClientSession, lamp: FakeLamp, lamp_host: str
) -> None:
    """Non-JSON and non-info text frames are ignored."""
    infos: list[dict[str, Any]] = []
    ws = LampWebSocket(session, lamp_host, infos.append)
    ws.start()
    try:
        await wait_for(lambda: len(infos) == 1)
        for client in lamp.ws_clients:
            await client.send_str("not json")
            await client.send_str('{"event":"other"}')
        await lamp.push_info()
        await wait_for(lambda: len(infos) == 2)
    finally:
        await ws.stop()
