"""Diagnostics tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .fake_lamp import FakeLamp


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    loaded_entry: MockConfigEntry,
    lamp: FakeLamp,
) -> None:
    """The info payload is included with addresses redacted."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    assert result["api_info"]["plugin"] == 37
    assert result["api_info"]["macAddress"] == "**REDACTED**"
    assert result["api_info"]["ipAddress"] == "**REDACTED**"
    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["state"]["mac_address"] == "**REDACTED**"
    assert result["connection"]["websocket"] is True
    assert result["messages"] == {"on_lamp": [], "queued": 0}
    assert "E8:6B" not in str(result)

    lamp.fail_with = 500
    result = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    assert result["api_info"].startswith("unavailable")
