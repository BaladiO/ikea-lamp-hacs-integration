"""Diagnostics download for the lamp."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .api import LampError
from .coordinator import ObegraensadConfigEntry

TO_REDACT = {CONF_HOST, "ipAddress", "macAddress", "ip_address", "mac_address", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ObegraensadConfigEntry
) -> dict[str, Any]:
    """Return the raw /api/info payload and the integration's internal state."""
    data = entry.runtime_data
    coordinator = data.coordinator
    try:
        raw: dict[str, Any] | str = await data.client.get_info_raw()
    except LampError as err:
        raw = f"unavailable: {err}"
    state = asdict(coordinator.data) if coordinator.data is not None else None
    if state is not None:
        state.pop("frame", None)
    return {
        "entry": async_redact_data(
            {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            TO_REDACT,
        ),
        "api_info": async_redact_data(raw, TO_REDACT) if isinstance(raw, dict) else raw,
        "state": async_redact_data(state, TO_REDACT) if state else None,
        "connection": {
            "websocket": coordinator.ws.connected,
            "last_poll_success": coordinator.last_update_success,
        },
        "messages": {
            "on_lamp": [
                {
                    "lamp_id": m.lamp_id,
                    "repeat": m.repeat,
                    "priority": m.priority,
                    "chars": len(m.text),
                }
                for m in data.messages.on_lamp
            ],
            "queued": len(data.messages.queued),
        },
        "display": {"active": data.display.active, "busy": data.display.busy},
    }
