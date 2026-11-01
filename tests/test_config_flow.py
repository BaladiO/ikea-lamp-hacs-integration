"""Config, reconfigure and options flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.obegraensad_lamp.const import (
    CONF_MAX_LAMP_MESSAGES,
    CONF_MESSAGE_DELAY,
    CONF_POLL_INTERVAL,
    DOMAIN,
)

from .conftest import MAC_ID
from .fake_lamp import FakeLamp


async def test_user_flow_success(hass: HomeAssistant, lamp_host: str) -> None:
    """A reachable lamp is added with its MAC as unique id."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"http://{lamp_host}/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: lamp_host}
    assert result["result"].unique_id == MAC_ID
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ("down", "cannot_connect"),
        ("http500", "invalid_response"),
        ("no_info", "firmware_unsupported"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, lamp: FakeLamp, lamp_host: str, setup: str, error: str
) -> None:
    """Errors are shown and the flow recovers when fixed."""
    host = lamp_host
    if setup == "down":
        host = "127.0.0.1:9"
    elif setup == "http500":
        lamp.fail_with = 500
    else:
        lamp.missing_routes.add("/api/info")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: host})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    lamp.fail_with = None
    lamp.missing_routes.clear()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: lamp_host}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_unexpected(hass: HomeAssistant, lamp_host: str) -> None:
    """Unexpected exceptions map to unknown."""
    from unittest.mock import patch

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(
        "custom_components.obegraensad_lamp.config_flow.LampClient.get_info",
        side_effect=RuntimeError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: lamp_host}
        )
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_updates_host(
    hass: HomeAssistant, lamp_host: str, socket_enabled: None
) -> None:
    """The same lamp cannot be added twice; its host is updated instead."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "10.0.0.1"}, unique_id=MAC_ID)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: lamp_host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == lamp_host


async def test_reconfigure(hass: HomeAssistant, lamp: FakeLamp, lamp_host: str) -> None:
    """The host can be changed, but only to the same lamp."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "10.0.0.1"}, unique_id=MAC_ID)
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1:9"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    lamp.info["macAddress"] = "AA:BB:CC:DD:EE:FF"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: lamp_host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"

    lamp.info["macAddress"] = "E8:6B:EA:C4:41:F0"
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: lamp_host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == lamp_host
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    """Options are stored as integers and the entry reloads."""
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_POLL_INTERVAL: 45.0,
            CONF_MESSAGE_DELAY: 60.0,
            "message_repeat": 0.0,
            CONF_MAX_LAMP_MESSAGES: 3.0,
            "restore": True,
            "night_suppress_low": True,
            "ddp_port": 4048.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert loaded_entry.options[CONF_POLL_INTERVAL] == 45
    assert isinstance(loaded_entry.options[CONF_MESSAGE_DELAY], int)
    coordinator = loaded_entry.runtime_data.coordinator
    assert coordinator.update_interval is not None
    assert coordinator.update_interval.total_seconds() == 45
