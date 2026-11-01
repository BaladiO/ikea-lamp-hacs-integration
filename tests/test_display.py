"""Temporary-display engine and display services."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp import display as display_module, icons
from custom_components.obegraensad_lamp.const import DOMAIN
from custom_components.obegraensad_lamp.ddp import to_wire_value

from .conftest import wait_until
from .fake_lamp import FakeLamp


@pytest.fixture(autouse=True)
def fast_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resend often so tests can observe it quickly."""
    monkeypatch.setattr(display_module, "RESEND_INTERVAL", 0.2)


async def service(hass: HomeAssistant, name: str, **data: Any) -> dict[str, Any]:
    """Call a display service and return this lamp's response."""
    response = await hass.services.async_call(
        DOMAIN, name, data, blocking=True, return_response=True
    )
    assert response is not None
    lamps = response["lamps"]
    assert isinstance(lamps, dict)
    return next(iter(lamps.values()))


def wire(frame: list[int]) -> list[int]:
    """The frame as the lamp stores it."""
    return [to_wire_value(v) for v in frame]


def plugin_switches(lamp: FakeLamp, plugin_id: int) -> int:
    """How often the integration selected ``plugin_id`` over HTTP."""
    return lamp.requests.count(("PATCH", "/api/plugin", {"id": str(plugin_id)}))


async def test_show_icon_and_restore(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """The icon is drawn over DDP, then Weather comes back."""
    result = await service(hass, "show_icon", icon="door", duration=0.6)
    assert result == {"status": "shown"}
    assert lamp.info["plugin"] == 39
    await wait_until(hass, lambda: lamp.frame == wire(icons.icon_frame("door")))
    assert loaded_entry.runtime_data.display.active
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)
    assert not loaded_entry.runtime_data.display.active


async def test_resends_while_held(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Frames are resent during the hold (UDP is lossy)."""
    await service(hass, "show_icon", icon="bell", duration=1.2)
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)
    assert lamp.ddp_packets >= 4


async def test_schedule_is_paused_and_restarted(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """A running plugin schedule is stopped for the display and started again."""
    lamp.info["schedule"] = [{"pluginId": 34, "duration": 60}]
    lamp.info["scheduleActive"] = True
    await loaded_entry.runtime_data.coordinator.async_poll_now()
    await service(hass, "show_icon", icon="check", duration=0.5)
    assert lamp.info["scheduleActive"] is False
    await wait_until(hass, lambda: lamp.info["scheduleActive"] is True)
    assert ("GET", "/api/schedule/start", {}) in lamp.requests


async def test_manual_change_cancels_restore(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """If the plugin is changed during the hold, it is left alone."""
    await service(hass, "show_icon", icon="warning", duration=5)
    await lamp.set_plugin(12)
    display = loaded_entry.runtime_data.display
    await wait_until(hass, lambda: not display.busy and not display.active)
    await asyncio.sleep(0.3)
    assert lamp.info["plugin"] == 12
    assert plugin_switches(lamp, 37) == 0


async def test_high_priority_preempts(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """High priority interrupts at once; one DDP session, one restore."""
    await service(hass, "show_icon", icon="clock", duration=30)
    result = await service(hass, "show_icon", icon="door", duration=0.5, priority="high")
    assert result == {"status": "queued"}
    await wait_until(hass, lambda: lamp.frame == wire(icons.icon_frame("door")))
    await wait_until(hass, lambda: lamp.info["plugin"] == 37, timeout=3)
    assert plugin_switches(lamp, 39) == 1


async def test_queue_in_one_session(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Displays in a row share one DDP session; low with drop_if_busy is skipped."""
    await service(hass, "show_icon", icon="heart", duration=0.5)
    assert (await service(hass, "show_icon", icon="smiley", duration=0.5))["status"] == "queued"
    dropped = await service(hass, "show_icon", icon="fan", priority="low", drop_if_busy=True)
    assert dropped == {"status": "dropped"}
    await wait_until(hass, lambda: lamp.frame == wire(icons.icon_frame("smiley")))
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)
    assert plugin_switches(lamp, 39) == 1
    assert plugin_switches(lamp, 37) == 1


async def test_draw_frame_and_restore_display(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """An open-ended frame stays until restore_display."""
    rows = ["F" * 16] + ["0" * 16] * 14 + ["8" * 16]
    await service(hass, "draw_frame", rows=rows)
    await wait_until(hass, lambda: lamp.frame[:16] == [255] * 16)
    assert lamp.frame[-1] == 136
    await asyncio.sleep(0.5)
    assert lamp.info["plugin"] == 39
    await hass.services.async_call(DOMAIN, "restore_display", {}, blocking=True)
    assert lamp.info["plugin"] == 37

    await service(hass, "draw_frame", pixels=[200] * 256, duration=0.5)
    await wait_until(hass, lambda: lamp.frame == [200] * 256)

    with pytest.raises(ServiceValidationError):
        await service(hass, "draw_frame", rows=["0" * 16] * 3)
    with pytest.raises(ServiceValidationError):
        await service(hass, "draw_frame", pixels=[1, 2, 3])
    with pytest.raises(ServiceValidationError):
        await service(hass, "draw_frame")


async def test_clear_and_message_restore(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Clear blanks the lamp; a message with restore ends the hold first."""
    lamp.frame = [9] * 256
    await service(hass, "clear")
    await wait_until(hass, lambda: lamp.frame == [0] * 256)
    await hass.services.async_call(DOMAIN, "send_message", {"text": "HI"}, blocking=True)
    assert lamp.info["plugin"] == 37
    assert [m["text"] for m in lamp.messages.values()] == ["HI"]


async def test_restore_false_stays_on_ddp(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """restore: false leaves the frame up after the duration."""
    await service(hass, "show_icon", icon="home", duration=0.5, restore=False)
    display = loaded_entry.runtime_data.display
    await wait_until(hass, lambda: not display.busy and not display.active)
    assert lamp.info["plugin"] == 39


async def test_unload_restores(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Unloading the integration never leaves a stale DDP frame."""
    await service(hass, "draw_frame", pixels=[50] * 256)
    assert lamp.info["plugin"] == 39
    await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert lamp.info["plugin"] == 37


async def test_shutdown_restores(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Home Assistant stopping restores the lamp too."""
    await service(hass, "clear")
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)


async def test_number_and_errors(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Numbers render; bad input and a lamp without DDP raise."""
    await service(hass, "show_icon", number=42, duration=0.5)
    await wait_until(hass, lambda: lamp.frame == wire(icons.number_frame(42)))
    with pytest.raises(ServiceValidationError):
        await service(hass, "show_icon", number=123456)
    with pytest.raises(ServiceValidationError):
        await service(hass, "show_icon")
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)

    lamp.info["plugins"] = [p for p in lamp.info["plugins"] if p["name"] != "DDP"]
    await loaded_entry.runtime_data.coordinator.async_poll_now()
    with pytest.raises(HomeAssistantError, match="DDP"):
        await service(hass, "show_icon", icon="door")


async def test_graph_values(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """With a duration a bar frame; without, a scrolled graph message."""
    values = [1, 2, 3, 4, 5, 6, 7, 8]
    await service(hass, "show_graph", values=values, duration=0.5)
    await wait_until(hass, lambda: lamp.frame == wire(icons.bar_graph(values)))
    await wait_until(hass, lambda: lamp.info["plugin"] == 37)

    result = await service(hass, "show_graph", values=[0, 50, 100], text="CPU", max=100)
    assert result["status"] == "sent"
    (msg,) = lamp.messages.values()
    assert msg["text"] == "CPU"
    assert msg["graph"] == [0, 8, 15]
    assert (msg["miny"], msg["maxy"]) == (0, 15)

    with pytest.raises(ServiceValidationError):
        await service(hass, "show_graph")
