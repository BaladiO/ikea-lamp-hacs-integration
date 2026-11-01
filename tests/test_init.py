"""Setup, unload, state handling and repairs."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.obegraensad_lamp import coordinator as coordinator_module
from custom_components.obegraensad_lamp.const import DOMAIN

from .conftest import MAC_ID, entity_id, wait_until
from .fake_lamp import FakeLamp


async def test_setup_and_unload(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """One device, one WebSocket, cleaned up on unload."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MAC_ID)})
    assert device is not None
    assert device.name == "IKEA OBEGRÄNSAD Lamp"
    assert (dr.CONNECTION_NETWORK_MAC, MAC_ID) in device.connections
    assert len(lamp.ws_clients) == 1

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    await wait_until(hass, lambda: not lamp.ws_clients)


async def test_setup_retries_when_unreachable(hass: HomeAssistant, socket_enabled: None) -> None:
    """An unreachable lamp makes setup retry later."""
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "127.0.0.1:9"}, unique_id=MAC_ID)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_ws_push_updates_entities(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """A plugin change on the lamp shows up without a poll."""
    select = entity_id(hass, "select", "plugin")
    assert hass.states.get(select).state == "Weather"
    polls = sum(1 for r in lamp.requests if r[1] == "/api/info")
    await lamp.set_plugin(12)
    await wait_until(hass, lambda: hass.states.get(select).state == "Spiral")
    assert sum(1 for r in lamp.requests if r[1] == "/api/info") == polls


async def test_unavailable_and_recovery(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Entities go unavailable when the lamp is gone and come back after."""
    light = entity_id(hass, "light", "lamp")
    reachable = entity_id(hass, "binary_sensor", "reachable")
    coordinator = loaded_entry.runtime_data.coordinator

    lamp.fail_with = 503
    await coordinator.ws.stop()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(light).state == STATE_UNAVAILABLE
    assert hass.states.get(reachable).state == "off"

    lamp.fail_with = None
    coordinator.ws.start()
    await wait_until(hass, lambda: hass.states.get(light).state == "on")
    assert hass.states.get(reachable).state == "on"


async def test_unreachable_issue(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    lamp: FakeLamp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long outage raises a repair issue that clears on recovery."""
    monkeypatch.setattr(coordinator_module, "UNREACHABLE_ISSUE_AFTER", 0)
    coordinator = loaded_entry.runtime_data.coordinator
    issue_id = f"unreachable_{loaded_entry.entry_id}"
    registry = ir.async_get(hass)

    lamp.fail_with = 503
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    lamp.fail_with = None
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_firmware_issue(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """A missing /api/info raises the firmware repair issue."""
    coordinator = loaded_entry.runtime_data.coordinator
    lamp.missing_routes.add("/api/info")
    await coordinator.async_refresh()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"firmware_unsupported_{loaded_entry.entry_id}"
    )
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR


async def test_poll_refreshes_diagnostics(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """The poll updates diagnostics that the WebSocket does not carry."""
    heap = entity_id(hass, "sensor", "free_heap")
    assert hass.states.get(heap).state == "104104"
    lamp.info["freeHeap"] = 90000
    # pushes in between must not postpone the poll
    await lamp.push_info()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await wait_until(hass, lambda: hass.states.get(heap).state == "90000")
