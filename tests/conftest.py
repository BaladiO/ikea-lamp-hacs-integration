"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from aiohttp.test_utils import TestServer
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp.const import DOMAIN, NAME

from .fake_lamp import FakeLamp

MAC_ID = "e8:6b:ea:c4:41:f0"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load integrations from custom_components."""


@pytest.fixture
def lamp() -> FakeLamp:
    """A fresh fake lamp."""
    return FakeLamp()


@pytest.fixture
async def lamp_server(lamp: FakeLamp, socket_enabled: None) -> AsyncIterator[TestServer]:
    """Serve the fake lamp on 127.0.0.1 (real sockets, localhost only)."""
    server = TestServer(lamp.app(), host="127.0.0.1")
    await server.start_server()
    yield server
    await lamp.drop_ws_clients()
    await server.close()


@pytest.fixture
def lamp_host(lamp_server: TestServer) -> str:
    """host:port of the fake lamp."""
    return f"127.0.0.1:{lamp_server.port}"


@pytest.fixture
def mock_entry(lamp_host: str) -> MockConfigEntry:
    """Config entry pointing at the fake lamp."""
    return MockConfigEntry(domain=DOMAIN, title=NAME, data={CONF_HOST: lamp_host}, unique_id=MAC_ID)


async def wait_until(
    hass: HomeAssistant, predicate: Callable[[], bool], timeout: float = 5.0
) -> None:
    """Let the loop run until ``predicate`` holds."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)
            await hass.async_block_till_done()


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry, lamp: FakeLamp
) -> AsyncIterator[MockConfigEntry]:
    """Set up the integration and wait for the WebSocket."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    await wait_until(hass, lambda: mock_entry.runtime_data.coordinator.ws.connected)
    await wait_until(hass, lambda: bool(lamp.live_preview) and not any(lamp.live_preview.values()))
    yield mock_entry
    if mock_entry.state.recoverable or mock_entry.state.name == "LOADED":
        await hass.config_entries.async_unload(mock_entry.entry_id)
        await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Entity id of one of the lamp's entities, looked up by unique id."""
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC_ID}_{key}")
    assert eid is not None, f"{platform} {key} not registered"
    return eid
