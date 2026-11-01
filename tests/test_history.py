"""show_graph with a sensor's recorded history."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fake_lamp import FakeLamp
from .test_display import service


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock: Any, enable_custom_integrations: None) -> None:
    """The recorder must be set up before hass, so it is requested first here."""


async def test_graph_from_sensor_history(
    hass: HomeAssistant, lamp: FakeLamp, mock_entry: MockConfigEntry
) -> None:
    """A sensor's recorded history is sampled into the graph."""
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    for value in ("10", "20", "30", "unavailable", "40"):
        hass.states.async_set("sensor.power", value)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    result = await service(hass, "show_graph", sensor="sensor.power", hours=1, min=0, max=40)
    assert result["status"] == "sent"
    (msg,) = lamp.messages.values()
    assert msg["graph"]
    assert msg["graph"][-1] == 15

    with pytest.raises(ServiceValidationError):
        await service(hass, "show_graph", sensor="sensor.nothing", hours=1)
    await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
