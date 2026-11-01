"""Entity platform tests against the fake lamp."""

from __future__ import annotations

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp.const import DOMAIN

from .conftest import entity_id, wait_until
from .fake_lamp import FakeLamp


async def call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    """Call a service and wait for it."""
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()


async def test_light(hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp) -> None:
    """Off is brightness 0; on restores the last brightness."""
    light = entity_id(hass, "light", "lamp")
    state = hass.states.get(light)
    assert state.state == "on"
    assert state.attributes["brightness"] == 255
    assert state.attributes["plugin"] == "Weather"
    assert state.attributes["rotation"] == 0

    await call(hass, "light", "turn_on", entity_id=light, brightness=100)
    await wait_until(hass, lambda: hass.states.get(light).attributes.get("brightness") == 100)
    await call(hass, "light", "turn_off", entity_id=light)
    await wait_until(hass, lambda: hass.states.get(light).state == "off")
    assert lamp.info["baseBrightness"] == 0
    await call(hass, "light", "turn_on", entity_id=light)
    await wait_until(hass, lambda: hass.states.get(light).state == "on")
    assert lamp.info["baseBrightness"] == 100


async def test_light_over_http(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Without the WebSocket, commands fall back to HTTP and a poll."""
    await loaded_entry.runtime_data.coordinator.ws.stop()
    light = entity_id(hass, "light", "lamp")
    await call(hass, "light", "turn_on", entity_id=light, brightness=30)
    assert lamp.info["baseBrightness"] == 30
    assert hass.states.get(light).attributes["brightness"] == 30
    assert ("PATCH", "/api/brightness", {"value": "30"}) in lamp.requests


async def test_select(hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp) -> None:
    """Selecting a plugin switches it and lists all plugins."""
    select = entity_id(hass, "select", "plugin")
    state = hass.states.get(select)
    assert "Big Clock" in state.attributes["options"]
    assert len(state.attributes["options"]) == 40
    await call(hass, "select", "select_option", entity_id=select, option="Big Clock")
    await wait_until(hass, lambda: hass.states.get(select).state == "Big Clock")
    assert lamp.info["plugin"] == 33

    with pytest.raises(ServiceValidationError):
        await call(hass, "select", "select_option", entity_id=select, option="Nope")


async def test_select_over_http_stops_schedule(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """The HTTP fallback also stops a running schedule, like the web UI."""
    lamp.info["schedule"] = [{"pluginId": 5, "duration": 10}]
    lamp.info["scheduleActive"] = True
    coordinator = loaded_entry.runtime_data.coordinator
    await coordinator.async_poll_now()
    await coordinator.ws.stop()
    select = entity_id(hass, "select", "plugin")
    await call(hass, "select", "select_option", entity_id=select, option="Clock")
    assert lamp.info["plugin"] == 34
    assert lamp.info["scheduleActive"] is False


async def test_buttons(hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp) -> None:
    """Rotate and persist use the WebSocket."""
    light = entity_id(hass, "light", "lamp")
    await call(hass, "button", "press", entity_id=entity_id(hass, "button", "rotate_right"))
    await wait_until(hass, lambda: hass.states.get(light).attributes["rotation"] == 1)
    await call(hass, "button", "press", entity_id=entity_id(hass, "button", "rotate_left"))
    await call(hass, "button", "press", entity_id=entity_id(hass, "button", "rotate_left"))
    await wait_until(hass, lambda: hass.states.get(light).attributes["rotation"] == 3)

    await lamp.set_plugin(10)
    await call(hass, "button", "press", entity_id=entity_id(hass, "button", "persist_plugin"))
    await wait_until(hass, lambda: lamp.persist_plugin == 10)

    await loaded_entry.runtime_data.coordinator.ws.stop()
    with pytest.raises(HomeAssistantError, match="WebSocket"):
        await call(hass, "button", "press", entity_id=entity_id(hass, "button", "rotate_left"))


async def test_plugin_schedule(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Schedule switch and service."""
    switch = entity_id(hass, "switch", "plugin_schedule")
    assert hass.states.get(switch).state == "off"
    with pytest.raises(ServiceValidationError):
        await call(hass, "switch", "turn_on", entity_id=switch)

    await call(
        hass,
        DOMAIN,
        "set_plugin_schedule",
        schedule=[{"plugin": "Weather", "duration": 60}, {"plugin": "big clock", "duration": 30}],
    )
    assert lamp.info["schedule"] == [
        {"pluginId": 37, "duration": 60},
        {"pluginId": 33, "duration": 30},
    ]
    await wait_until(hass, lambda: hass.states.get(switch).state == "on")
    assert hass.states.get(switch).attributes["schedule"][1] == {
        "plugin": "Big Clock",
        "duration": 30,
    }
    await call(hass, "switch", "turn_off", entity_id=switch)
    await wait_until(hass, lambda: hass.states.get(switch).state == "off")
    await call(hass, "switch", "turn_on", entity_id=switch)
    await wait_until(hass, lambda: hass.states.get(switch).state == "on")
    await call(hass, DOMAIN, "set_plugin_schedule", action="clear")
    assert lamp.info["schedule"] == []

    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "set_plugin_schedule", schedule=[])
    with pytest.raises(ServiceValidationError):
        await call(
            hass, DOMAIN, "set_plugin_schedule", schedule=[{"plugin": "Nope", "duration": 5}]
        )


async def test_night_schedule_entities(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Switch, number and time entities edit the brightness schedule."""
    switch = entity_id(hass, "switch", "night_schedule")
    number = entity_id(hass, "number", "night_brightness")
    start = entity_id(hass, "time", "night_start")
    end = entity_id(hass, "time", "night_end")
    assert hass.states.get(switch).state == "off"
    assert hass.states.get(number).state == "20"
    assert hass.states.get(start).state == "22:00:00"
    assert hass.states.get(end).state == "07:00:00"

    await call(hass, "switch", "turn_on", entity_id=switch)
    await call(hass, "number", "set_value", entity_id=number, value=12)
    await call(hass, "time", "set_value", entity_id=start, time="23:30:00")
    await call(hass, "time", "set_value", entity_id=end, time="06:15:00")
    assert lamp.info["brightnessSchedule"] == {
        "enabled": True,
        "startTime": "23:30",
        "endTime": "06:15",
        "brightness": 12,
        "active": False,
    }
    assert hass.states.get(switch).state == "on"
    assert hass.states.get(number).state == "12"
    assert hass.states.get(start).state == "23:30:00"

    with pytest.raises(ServiceValidationError):
        await call(hass, "time", "set_value", entity_id=end, time="23:30:00")


async def test_brightness_schedule_service(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """The service changes only the given fields, targeting the device."""
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "e8:6b:ea:c4:41:f0")})
    assert device is not None
    await call(
        hass, DOMAIN, "set_brightness_schedule", device_id=device.id, enabled=True, brightness=5
    )
    assert lamp.info["brightnessSchedule"]["enabled"] is True
    assert lamp.info["brightnessSchedule"]["brightness"] == 5
    assert lamp.info["brightnessSchedule"]["startTime"] == "22:00"


async def test_select_plugin_service(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """select_plugin works by entity target and rejects unknown names."""
    light = entity_id(hass, "light", "lamp")
    await call(hass, DOMAIN, "select_plugin", plugin="ddp", **{ATTR_ENTITY_ID: light})
    await wait_until(hass, lambda: lamp.info["plugin"] == 39)
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "select_plugin", plugin="Nope")
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "select_plugin", plugin="Clock", entity_id="light.other")


async def test_sensors(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    """Diagnostic sensors show /api/info values."""
    assert hass.states.get(entity_id(hass, "sensor", "rssi")).state == "-65"
    assert hass.states.get(entity_id(hass, "sensor", "reset_reason")).state == "poweron"
    assert hass.states.get(entity_id(hass, "sensor", "ip_address")).state == "192.168.100.45"
    uptime = hass.states.get(entity_id(hass, "sensor", "uptime"))
    assert float(uptime.state) == pytest.approx(730 / 3600, abs=0.01)
    reachable = hass.states.get(entity_id(hass, "binary_sensor", "reachable"))
    assert reachable.state == "on"
    assert reachable.attributes["websocket"] is True
