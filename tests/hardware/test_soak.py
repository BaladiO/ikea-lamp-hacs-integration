"""Soak test against a real lamp.

    LAMP_HOST=192.168.100.45 SOAK_MINUTES=32 SOAK_CSV=/out/soak.csv \\
        pytest tests/hardware/test_soak.py -p no:cacheprovider -s

Every cycle sends a notification, shows an icon (with restore) and switches the
plugin over the WebSocket, and every few cycles drops the WebSocket to check the
reconnect. Brightness and rotation are left alone because the firmware writes
them to flash. ``freeHeap`` and ``uptime`` are sampled to check for leaks and
reboots. The starting plugin is restored at the end.
"""

from __future__ import annotations

import asyncio
import csv
import os
import time

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp.api import LampClient
from custom_components.obegraensad_lamp.const import DOMAIN

from ..conftest import wait_until
from .test_real_lamp import eid, entry, lamp  # noqa: F401 - fixtures

MINUTES = float(os.environ.get("SOAK_MINUTES", "0"))
CSV_PATH = os.environ.get("SOAK_CSV")
PLUGINS = ["Big Clock", "Clock", "Ticking Clock", "Stars"]

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("LAMP_HOST") or MINUTES <= 0, reason="set LAMP_HOST and SOAK_MINUTES"
    ),
    pytest.mark.usefixtures("socket_enabled"),
]


async def test_soak(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    lamp: LampClient,  # noqa: F811
) -> None:
    """Run the workload and check for reboots and a heap decline."""
    coordinator = entry.runtime_data.coordinator
    start_state = await lamp.get_info()
    start_plugin = start_state.plugin.name if start_state.plugin else PLUGINS[0]
    select = eid(hass, entry, "select", "plugin")
    notify = eid(hass, entry, "notify", "notify")

    samples: list[tuple[float, int, int, int, int]] = []
    errors: list[str] = []
    reconnects = 0
    t0 = time.monotonic()
    deadline = t0 + MINUTES * 60
    last_sample = 0.0
    cycle = 0

    async def sample() -> None:
        info = await lamp.get_info()
        samples.append(
            (
                round(time.monotonic() - t0, 1),
                info.uptime or 0,
                info.free_heap or 0,
                info.rssi or 0,
                cycle,
            )
        )

    await sample()
    while time.monotonic() < deadline:
        cycle += 1
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": notify, "message": f"SOAK {cycle}"},
                blocking=True,
            )
            await hass.services.async_call(
                DOMAIN,
                "show_icon",
                {"icon": ["door", "bell", "check", "heart"][cycle % 4], "duration": 3},
                blocking=True,
            )
            await wait_until(hass, lambda: not entry.runtime_data.display.busy, 20)
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": select, "option": PLUGINS[cycle % len(PLUGINS)]},
                blocking=True,
            )
            if cycle % 10 == 0:
                # WebSocket drop: close it from our side, the client must come back
                ws = coordinator.ws._ws
                if ws is not None:
                    await ws.close()
                    await wait_until(hass, lambda: coordinator.ws.connected, 90)
                    reconnects += 1
        except Exception as err:
            errors.append(f"cycle {cycle}: {err!r}")
        await asyncio.sleep(12)
        if time.monotonic() - last_sample >= 30:
            last_sample = time.monotonic()
            await sample()
    await hass.services.async_call(DOMAIN, "remove_message", {"all": True}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": select, "option": start_plugin}, blocking=True
    )
    await asyncio.sleep(2)
    await sample()

    if CSV_PATH:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as handle:  # noqa: ASYNC230
            writer = csv.writer(handle)
            writer.writerow(["t_s", "uptime_s", "free_heap", "rssi", "cycle"])
            writer.writerows(samples)

    uptimes = [s[1] for s in samples]
    heaps = [s[2] for s in samples]
    head = sum(heaps[:5]) / min(5, len(heaps))
    tail = sum(heaps[-5:]) / min(5, len(heaps))
    print(
        f"\nsoak: {cycle} cycles, {reconnects} WebSocket reconnects, {len(errors)} errors, "
        f"heap first5 {head:.0f} last5 {tail:.0f} min {min(heaps)} max {max(heaps)}, "
        f"uptime {uptimes[0]} -> {uptimes[-1]}"
    )
    for line in errors:
        print("  ", line)
    assert uptimes == sorted(uptimes), "lamp rebooted during the soak"
    assert tail >= head - 8192, "free heap declined by more than 8 kB"
    assert len(errors) <= cycle // 20, errors
