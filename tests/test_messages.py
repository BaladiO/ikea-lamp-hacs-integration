"""Notify entity, message services and the message queue."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp import messages as messages_module
from custom_components.obegraensad_lamp.const import (
    CONF_DDP_PORT,
    CONF_MAX_LAMP_MESSAGES,
    CONF_MESSAGE_DELAY,
    CONF_MESSAGE_REPEAT,
    CONF_NIGHT_SUPPRESS_LOW,
    DOMAIN,
)
from custom_components.obegraensad_lamp.messages import (
    HASHED_OFFSET,
    MAX_QUEUED,
    USER_INT_OFFSET,
    Message,
    lamp_id_for_key,
)

from .conftest import MAC_ID, entity_id, wait_until
from .fake_lamp import FakeLamp


async def send(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    """Call send_message and return this lamp's response."""
    response = await hass.services.async_call(
        DOMAIN, "send_message", data, blocking=True, return_response=True
    )
    assert response is not None
    lamps = response["lamps"]
    assert isinstance(lamps, dict)
    return next(iter(lamps.values()))


def texts(lamp: FakeLamp) -> list[str]:
    """Texts currently on the fake lamp."""
    return [m["text"] for m in lamp.messages.values()]


@pytest.fixture
def mock_entry(lamp_host: str, lamp: FakeLamp) -> MockConfigEntry:
    """Entry with a small lamp limit so queueing is easy to hit."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"host": lamp_host},
        unique_id=MAC_ID,
        options={
            CONF_MAX_LAMP_MESSAGES: 2,
            CONF_MESSAGE_DELAY: 40,
            CONF_MESSAGE_REPEAT: 0,
            CONF_NIGHT_SUPPRESS_LOW: True,
            CONF_DDP_PORT: lamp.ddp_port,
        },
    )


def test_lamp_ids() -> None:
    """User ids map to stable, separate ranges."""
    assert lamp_id_for_key(7) == USER_INT_OFFSET + 7
    assert lamp_id_for_key("7") == USER_INT_OFFSET + 7
    assert lamp_id_for_key("bathroom") == lamp_id_for_key("bathroom")
    assert lamp_id_for_key("bathroom") >= HASHED_OFFSET
    assert lamp_id_for_key("bathroom") != lamp_id_for_key("door")
    assert lamp_id_for_key(-1) >= HASHED_OFFSET
    assert lamp_id_for_key("bathroom") < 2**31


def test_lifetime_estimate() -> None:
    """Showing time follows the firmware's scroll steps."""
    msg = Message(text="DONE", repeat=0, delay=50)
    assert msg.showing_seconds() == pytest.approx((16 + 24) * 0.05)
    assert Message(text="", repeat=0, delay=50, graph=[1] * 8).showing_seconds() == 1.2
    assert Message(text="X", repeat=2, delay=50).lifetime_seconds() == pytest.approx(
        (16 + 6) * 0.05 + 120 + 10
    )
    assert Message(text="X", repeat=-1, delay=50).lifetime_seconds() is None


async def test_notify_entity(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """notify.send_message uses option defaults and prefixes the title."""
    notify = entity_id(hass, "notify", "notify")
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": notify, "message": "Wäsche fertig 🎉", "title": "Laundry"},
        blocking=True,
    )
    (msg,) = lamp.messages.values()
    assert msg["text"] == "Laundry: Wäsche fertig"
    assert msg["delay"] == 40
    assert msg["repeat"] == 0


async def test_send_message_service(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """All parameters reach the lamp; the same message_id replaces."""
    result = await send(
        hass, text="BATH", repeat=-1, delay=60, message_id="bathroom", graph=[1, 2, 3], maxy=10
    )
    assert result["status"] == "sent"
    lamp_id = lamp_id_for_key("bathroom")
    assert lamp.messages[lamp_id] == {
        "text": "BATH",
        "repeat": -1,
        "delay": 60,
        "graph": [1, 2, 3],
        "miny": 0,
        "maxy": 10,
    }
    await send(hass, text="BATH!", repeat=-1, message_id="bathroom")
    assert texts(lamp) == ["BATH!"]

    with pytest.raises(ServiceValidationError):
        await send(hass, text="🎉")
    with pytest.raises(ServiceValidationError):
        await send(hass, text="x", graph=[1], miny=5, maxy=1)


async def test_queue_and_expiry(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    lamp: FakeLamp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only two messages are on the lamp; the next follows when one ends."""
    # shrink the firmware timings so the test runs in real time
    monkeypatch.setattr(messages_module, "SLACK_SECONDS", 0.2)
    monkeypatch.setattr(messages_module, "REPEAT_INTERVAL", 1.0)
    assert (await send(hass, text="ONE", delay=10))["status"] == "sent"
    assert (await send(hass, text="TWO", delay=10, repeat=1))["status"] == "sent"
    assert (await send(hass, text="THREE", delay=10))["status"] == "queued"
    assert sorted(texts(lamp)) == ["ONE", "TWO"]

    queue = loaded_entry.runtime_data.messages
    assert [m.text for m in queue.queued] == ["THREE"]

    # ONE ends after (16 + 18) * 10 ms + 0.2 s; TWO a repeat interval later
    await wait_until(hass, lambda: sorted(texts(lamp)) == ["THREE", "TWO"])
    assert ("GET", "/api/removemessage", {"id": "1"}) in lamp.requests
    await wait_until(hass, lambda: texts(lamp) == [])
    assert queue.on_lamp == []
    assert queue.queued == []


async def test_high_priority_preempts(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """A high-priority message pushes out the oldest normal one."""
    await send(hass, text="FOREVER", repeat=-1, message_id=1)
    await send(hass, text="NORMAL")
    assert (await send(hass, text="LOW", priority="low"))["status"] == "queued"
    result = await send(hass, text="DOOR", priority="high")
    assert result["status"] == "sent"
    assert sorted(texts(lamp)) == ["DOOR", "FOREVER"]
    # with only high and infinite messages left, the next high one waits first in line
    assert (await send(hass, text="FIRE", priority="high"))["status"] == "queued"
    queue = loaded_entry.runtime_data.messages
    assert [m.text for m in queue.queued] == ["FIRE", "LOW"]


async def test_remove_message(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Remove by id frees a slot for the queue; all clears everything."""
    await send(hass, text="BATH", repeat=-1, message_id="bathroom")
    await send(hass, text="FAN", repeat=-1, message_id=5)
    await send(hass, text="WAITING")
    response = await hass.services.async_call(
        DOMAIN, "remove_message", {"message_id": "bathroom"}, blocking=True, return_response=True
    )
    assert response is not None
    assert next(iter(response["lamps"].values())) == {"removed": 1}  # type: ignore[union-attr]
    assert sorted(texts(lamp)) == ["FAN", "WAITING"]

    # unknown ids are still removed from the lamp (left over from a restart)
    lamp.messages[lamp_id_for_key("old")] = {"text": "OLD"}
    await hass.services.async_call(DOMAIN, "remove_message", {"message_id": "old"}, blocking=True)
    assert "OLD" not in texts(lamp)

    await hass.services.async_call(DOMAIN, "remove_message", {"all": True}, blocking=True)
    assert texts(lamp) == []

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "remove_message", {"all": False}, blocking=True)


async def test_night_suppresses_low(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """Low-priority messages are dropped while the night brightness is active."""
    lamp.info["brightnessSchedule"]["active"] = True
    await loaded_entry.runtime_data.coordinator.async_poll_now()
    assert (await send(hass, text="LOW", priority="low"))["status"] == "suppressed"
    assert (await send(hass, text="NORMAL"))["status"] == "sent"
    assert texts(lamp) == ["NORMAL"]


async def test_queue_full(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    """Beyond the queue limit a clear error is raised."""
    for i in range(2 + MAX_QUEUED):
        await send(hass, text=f"M{i}", repeat=-1, message_id=i)
    with pytest.raises(HomeAssistantError, match="Too many messages"):
        await send(hass, text="ONE MORE")


async def test_lamp_error_is_reported(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, lamp: FakeLamp
) -> None:
    """HTTP failures become Home Assistant errors."""
    lamp.fail_with = 500
    with pytest.raises(HomeAssistantError):
        await send(hass, text="X")
