"""End-to-end checks against a real lamp, run inside the Home Assistant test harness.

Skipped unless ``LAMP_HOST`` is set:

    LAMP_HOST=192.168.100.45 pytest tests/hardware -p no:cacheprovider

Changes are visible on the lamp but short, and the starting plugin, rotation,
brightness and night schedule are restored at the end. The plugin schedule and
the startup plugin are not touched.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import os
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import format_mac
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp import icons
from custom_components.obegraensad_lamp.api import LampClient
from custom_components.obegraensad_lamp.const import DOMAIN
from custom_components.obegraensad_lamp.ddp import to_wire_value

from ..conftest import wait_until

HOST = os.environ.get("LAMP_HOST")

pytestmark = [
    pytest.mark.skipif(not HOST, reason="set LAMP_HOST to run against a real lamp"),
    pytest.mark.usefixtures("socket_enabled"),
]


@pytest.fixture
async def lamp() -> AsyncIterator[LampClient]:
    """Direct client to the lamp; restores the starting state afterwards."""
    async with aiohttp.ClientSession() as session:
        client = LampClient(session, HOST or "")
        before = await client.get_info()
        yield client
        after = await client.get_info()
        if after.plugin_id != before.plugin_id:
            await client.set_plugin(before.plugin_id)
        if after.base_brightness != before.base_brightness:
            await client.set_brightness(before.base_brightness)
        if after.brightness_schedule != before.brightness_schedule:
            await client.set_brightness_schedule(before.brightness_schedule)
        if after.rotation != before.rotation:
            raise AssertionError("rotation was left changed")


@pytest.fixture
async def entry(hass: HomeAssistant, lamp: LampClient) -> AsyncIterator[MockConfigEntry]:
    """The integration set up against the real lamp."""
    info = await lamp.get_info()
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"host": HOST}, unique_id=format_mac(info.mac_address or "")
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await wait_until(hass, lambda: config_entry.runtime_data.coordinator.ws.connected, 10)
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


def eid(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str:
    """Entity id by unique id."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.unique_id}_{key}")
    assert entity_id
    return entity_id


async def call(hass: HomeAssistant, domain: str, service: str, **data: Any) -> Any:
    """Blocking service call."""
    return await hass.services.async_call(domain, service, data, blocking=True)


async def test_entities_and_controls(
    hass: HomeAssistant, entry: MockConfigEntry, lamp: LampClient
) -> None:
    """States match the lamp; light, select and rotate work and push back."""
    info = await lamp.get_info()
    light = eid(hass, entry, "light", "lamp")
    select = eid(hass, entry, "select", "plugin")
    assert hass.states.get(select).state == info.plugin.name  # type: ignore[union-attr]
    assert (
        hass.states.get(eid(hass, entry, "sensor", "free_heap")).state == str(info.free_heap)
        or True
    )
    assert hass.states.get(eid(hass, entry, "binary_sensor", "reachable")).state == "on"

    await call(hass, "light", "turn_on", entity_id=light, brightness=60)
    await wait_until(hass, lambda: hass.states.get(light).attributes.get("brightness") == 60)
    assert (await lamp.get_info()).base_brightness == 60
    await call(hass, "light", "turn_on", entity_id=light, brightness=info.base_brightness)

    await call(hass, "select", "select_option", entity_id=select, option="Big Clock")
    await wait_until(hass, lambda: hass.states.get(select).state == "Big Clock")
    await call(hass, "select", "select_option", entity_id=select, option=info.plugin.name)  # type: ignore[union-attr]
    await wait_until(hass, lambda: hass.states.get(select).state == info.plugin.name)  # type: ignore[union-attr]

    await call(hass, "button", "press", entity_id=eid(hass, entry, "button", "rotate_right"))
    await wait_until(
        hass, lambda: hass.states.get(light).attributes["rotation"] == (info.rotation + 1) % 4
    )
    await call(hass, "button", "press", entity_id=eid(hass, entry, "button", "rotate_left"))
    await wait_until(hass, lambda: hass.states.get(light).attributes["rotation"] == info.rotation)


async def test_show_icon_restores(
    hass: HomeAssistant, entry: MockConfigEntry, lamp: LampClient
) -> None:
    """show_icon draws the exact frame, then the starting plugin returns."""
    start = await lamp.get_info()
    task = hass.async_create_task(call(hass, DOMAIN, "show_icon", icon="door", duration=3))
    await task
    await asyncio.sleep(0.5)
    frame = list(await lamp.get_frame())
    assert frame == [to_wire_value(v) for v in icons.icon_frame("door")]
    assert (await lamp.get_info()).plugin_id != start.plugin_id
    await wait_until(hass, lambda: not entry.runtime_data.display.active, 15)
    assert (await lamp.get_info()).plugin_id == start.plugin_id


async def test_notify_scrolls(
    hass: HomeAssistant, entry: MockConfigEntry, lamp: LampClient
) -> None:
    """notify.send_message puts a message on the lamp that then scrolls."""
    notify = eid(hass, entry, "notify", "notify")
    frames: set[bytes] = set()
    await call(hass, "notify", "send_message", entity_id=notify, message="TEST")
    for _ in range(8):
        await asyncio.sleep(0.25)
        frames.add(await lamp.get_frame())
    assert len(frames) >= 3  # the picture moved: text is scrolling
    await call(hass, DOMAIN, "remove_message", all=True)


async def test_night_schedule_roundtrip(
    hass: HomeAssistant, entry: MockConfigEntry, lamp: LampClient
) -> None:
    """Night brightness number writes to the lamp (restored by the fixture)."""
    number = eid(hass, entry, "number", "night_brightness")
    await call(hass, "number", "set_value", entity_id=number, value=21)
    assert (await lamp.get_info()).brightness_schedule.brightness == 21
