"""Tests for the HTTP client."""

from __future__ import annotations

from collections.abc import AsyncIterator
import time

import aiohttp
import pytest

from custom_components.obegraensad_lamp.api import (
    BrightnessSchedule,
    LampClient,
    LampCommandError,
    LampConnectionError,
    LampNotSupportedError,
    LampResponseError,
    LampState,
    ScheduleItem,
    normalise_host,
)

from .fake_lamp import MAC, FakeLamp, default_info

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """A plain aiohttp session."""
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
def client(session: aiohttp.ClientSession, lamp_host: str) -> LampClient:
    """Client pointed at the fake lamp, without the request gap."""
    return LampClient(session, lamp_host, min_interval=0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.100.45", "192.168.100.45"),
        (" http://192.168.100.45/ ", "192.168.100.45"),
        ("https://ikea-led.local/api", "ikea-led.local"),
        ("10.0.0.2:8080", "10.0.0.2:8080"),
    ],
)
def test_normalise_host(raw: str, expected: str) -> None:
    """User input is reduced to host[:port]."""
    assert normalise_host(raw) == expected


async def test_get_info(client: LampClient) -> None:
    """The real lamp's payload parses into a state."""
    state = await client.get_info()
    assert state.plugin_id == 37
    assert state.plugin is not None and state.plugin.name == "Weather"
    assert state.mac_address == MAC
    assert state.free_heap == 104104
    assert state.brightness_schedule == BrightnessSchedule(False, "22:00", "07:00", 20, False)
    assert state.plugin_by_name("ddp") is not None
    assert state.plugin_by_name("ddp").id == 39  # type: ignore[union-attr]
    assert state.plugin_by_name("nope") is None


def test_state_merge_keeps_diagnostics() -> None:
    """A WS push (no diagnostics) keeps values from the last HTTP poll."""
    old = LampState.from_info(default_info())
    ws = {k: v for k, v in default_info().items() if k not in ("rssi", "uptime", "freeHeap")}
    ws["plugin"] = 39
    ws["persist-plugin"] = 12
    merged = old.merge(LampState.from_info(ws))
    assert merged.plugin_id == 39
    assert merged.rssi == -65
    assert merged.persist_plugin_id == 12


def test_state_rejects_garbage() -> None:
    """Missing keys raise a response error, not KeyError."""
    with pytest.raises(LampResponseError):
        LampState.from_info({"plugin": 1})


async def test_commands(client: LampClient, lamp: FakeLamp) -> None:
    """Plugin, brightness and schedule commands reach the lamp."""
    await client.set_plugin(39)
    assert lamp.info["plugin"] == 39
    await client.set_brightness(42)
    assert lamp.info["baseBrightness"] == 42
    with pytest.raises(ValueError):
        await client.set_brightness(256)

    saved = await client.set_brightness_schedule(BrightnessSchedule(True, "23:00", "06:30", 10))
    assert saved.enabled and saved.start_time == "23:00" and saved.brightness == 10

    await client.set_schedule([ScheduleItem(37, 60), ScheduleItem(34, 30)])
    assert lamp.info["schedule"] == [
        {"pluginId": 37, "duration": 60},
        {"pluginId": 34, "duration": 30},
    ]
    assert lamp.info["scheduleActive"]
    await client.stop_schedule()
    assert not lamp.info["scheduleActive"]
    await client.start_schedule()
    assert lamp.info["scheduleActive"]
    await client.clear_schedule()
    assert lamp.info["schedule"] == []


async def test_command_errors(client: LampClient) -> None:
    """Firmware JSON errors become LampCommandError with the message."""
    with pytest.raises(LampCommandError, match="Could not set plugin to id 99") as err:
        await client.set_plugin(99)
    assert err.value.status == 422
    with pytest.raises(LampCommandError, match="Start and end times must differ"):
        await client.set_brightness_schedule(BrightnessSchedule(True, "22:00", "22:00", 1))
    # JSON 404 from the firmware is a command error, not a missing route
    with pytest.raises(LampCommandError, match="No schedule found"):
        await client.stop_schedule()


async def test_missing_route(client: LampClient, lamp: FakeLamp) -> None:
    """A plain-text 404 means the firmware lacks the route."""
    lamp.missing_routes.add("/api/info")
    with pytest.raises(LampNotSupportedError):
        await client.get_info()


async def test_server_error_without_json(client: LampClient, lamp: FakeLamp) -> None:
    """Non-JSON error bodies are response errors."""
    lamp.fail_with = 500
    with pytest.raises(LampResponseError):
        await client.get_info()


async def test_messages(client: LampClient, lamp: FakeLamp) -> None:
    """Messages are sent with all parameters, including UTF-8 text and graphs."""
    await client.send_message("Tür offen", message_id=5, repeat=2, delay=40)
    assert lamp.messages[5]["text"] == "Tür offen"
    assert lamp.messages[5]["repeat"] == 2
    assert lamp.messages[5]["delay"] == 40
    await client.send_message("", message_id=6, graph=[0, 5, 15], miny=0, maxy=15)
    assert lamp.messages[6]["graph"] == [0, 5, 15]
    await client.remove_message(5)
    assert 5 not in lamp.messages
    with pytest.raises(LampCommandError):
        await client.send_message("x", message_id=7, miny=10, maxy=5)


async def test_frame_and_config(client: LampClient, lamp: FakeLamp) -> None:
    """Raw frame bytes and config are returned."""
    lamp.frame[3] = 255
    frame = await client.get_frame()
    assert len(frame) == 256 and frame[3] == 255
    assert (await client.get_config())["weatherLocation"] == "Casablanca"


async def test_connection_error_after_retries(session: aiohttp.ClientSession) -> None:
    """An unreachable host raises after the retries."""
    client = LampClient(session, "127.0.0.1:9", timeout=0.5, min_interval=0, retries=1)
    with pytest.raises(LampConnectionError):
        await client.get_info()


async def test_requests_are_spaced(session: aiohttp.ClientSession, lamp_host: str) -> None:
    """Consecutive requests keep the minimum gap."""
    client = LampClient(session, lamp_host, min_interval=0.05)
    start = time.monotonic()
    for _ in range(4):
        await client.get_info()
    assert time.monotonic() - start >= 0.15
