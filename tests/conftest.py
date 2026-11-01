"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aiohttp.test_utils import TestServer
import pytest

from .fake_lamp import FakeLamp


@pytest.fixture
def lamp() -> FakeLamp:
    """A fresh fake lamp."""
    return FakeLamp()


@pytest.fixture
async def lamp_server(lamp: FakeLamp) -> AsyncIterator[TestServer]:
    """Serve the fake lamp on 127.0.0.1."""
    server = TestServer(lamp.app(), host="127.0.0.1")
    await server.start_server()
    yield server
    await lamp.drop_ws_clients()
    await server.close()


@pytest.fixture
def lamp_host(lamp_server: TestServer) -> str:
    """host:port of the fake lamp."""
    return f"127.0.0.1:{lamp_server.port}"
