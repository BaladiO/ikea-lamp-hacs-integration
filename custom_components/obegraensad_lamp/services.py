"""Integration services (actions)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import time
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.service import async_extract_referenced_entity_ids
import voluptuous as vol

from .api import ScheduleItem
from .const import DOMAIN
from .coordinator import ObegraensadConfigEntry

SERVICE_SELECT_PLUGIN = "select_plugin"
SERVICE_SET_BRIGHTNESS_SCHEDULE = "set_brightness_schedule"
SERVICE_SET_PLUGIN_SCHEDULE = "set_plugin_schedule"
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_REMOVE_MESSAGE = "remove_message"

ATTR_PLUGIN = "plugin"
ATTR_ENABLED = "enabled"
ATTR_START = "start"
ATTR_END = "end"
ATTR_BRIGHTNESS = "brightness"
ATTR_SCHEDULE = "schedule"
ATTR_ACTION = "action"
ATTR_DURATION = "duration"
ATTR_TEXT = "text"
ATTR_REPEAT = "repeat"
ATTR_DELAY = "delay"
ATTR_MESSAGE_ID = "message_id"
ATTR_GRAPH = "graph"
ATTR_MINY = "miny"
ATTR_MAXY = "maxy"
ATTR_PRIORITY = "priority"
ATTR_RESTORE = "restore"
ATTR_ALL = "all"

PRIORITIES = ["low", "normal", "high"]
MESSAGE_KEY = vol.Any(vol.All(vol.Coerce(int), vol.Range(min=0)), cv.string)

TARGET_FIELDS = cv.ENTITY_SERVICE_FIELDS

SELECT_PLUGIN_SCHEMA = vol.Schema({**TARGET_FIELDS, vol.Required(ATTR_PLUGIN): cv.string})

BRIGHTNESS_SCHEDULE_SCHEMA = vol.Schema(
    {
        **TARGET_FIELDS,
        vol.Optional(ATTR_ENABLED): cv.boolean,
        vol.Optional(ATTR_START): cv.time,
        vol.Optional(ATTR_END): cv.time,
        vol.Optional(ATTR_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(0, 255)),
    }
)

PLUGIN_SCHEDULE_SCHEMA = vol.Schema(
    {
        **TARGET_FIELDS,
        vol.Optional(ATTR_ACTION, default="set"): vol.In(["set", "start", "stop", "clear"]),
        vol.Optional(ATTR_SCHEDULE): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(ATTR_PLUGIN): cv.string,
                        vol.Required(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(1, 86400)),
                    }
                )
            ],
        ),
    }
)

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        **TARGET_FIELDS,
        vol.Optional(ATTR_TEXT, default=""): cv.string,
        vol.Optional(ATTR_REPEAT): vol.All(vol.Coerce(int), vol.Range(-1, 1000)),
        vol.Optional(ATTR_DELAY): vol.All(vol.Coerce(int), vol.Range(10, 1000)),
        vol.Optional(ATTR_MESSAGE_ID): MESSAGE_KEY,
        vol.Optional(ATTR_GRAPH): vol.All(cv.ensure_list, [vol.Coerce(int)], vol.Length(max=256)),
        vol.Optional(ATTR_MINY, default=0): vol.Coerce(int),
        vol.Optional(ATTR_MAXY, default=15): vol.Coerce(int),
        vol.Optional(ATTR_PRIORITY, default="normal"): vol.In(PRIORITIES),
        vol.Optional(ATTR_RESTORE, default=True): cv.boolean,
    }
)

REMOVE_MESSAGE_SCHEMA = vol.All(
    vol.Schema(
        {
            **TARGET_FIELDS,
            vol.Optional(ATTR_MESSAGE_ID): MESSAGE_KEY,
            vol.Optional(ATTR_ALL, default=False): cv.boolean,
        }
    ),
    cv.has_at_least_one_key(ATTR_MESSAGE_ID, ATTR_ALL),
)


def resolve_entries(hass: HomeAssistant, call: ServiceCall) -> list[ObegraensadConfigEntry]:
    """Find the loaded lamp entries a call targets.

    Devices and entities are both accepted. With no target and exactly one lamp
    configured, that lamp is used.
    """
    loaded: dict[str, ObegraensadConfigEntry] = {
        entry.entry_id: entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    }
    selected = async_extract_referenced_entity_ids(hass, call)
    entry_ids: set[str] = set()
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    for device_id in selected.referenced_devices:
        if device := dev_reg.async_get(device_id):
            entry_ids.update(e for e in device.config_entries if e in loaded)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entity = ent_reg.async_get(entity_id)
        if entity and entity.config_entry_id in loaded:
            entry_ids.add(entity.config_entry_id)

    has_target = bool(
        selected.referenced or selected.referenced_devices or selected.referenced_areas
    )
    if not has_target and len(loaded) == 1:
        return list(loaded.values())
    if not entry_ids:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_target")
    return [loaded[e] for e in sorted(entry_ids)]


def _hhmm(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


async def _select_plugin(entry: ObegraensadConfigEntry, call: ServiceCall) -> None:
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_select_plugin(coordinator.resolve_plugin(call.data[ATTR_PLUGIN]))


async def _set_brightness_schedule(entry: ObegraensadConfigEntry, call: ServiceCall) -> None:
    changes: dict[str, Any] = {}
    if ATTR_ENABLED in call.data:
        changes["enabled"] = call.data[ATTR_ENABLED]
    if ATTR_START in call.data:
        changes["start_time"] = _hhmm(call.data[ATTR_START])
    if ATTR_END in call.data:
        changes["end_time"] = _hhmm(call.data[ATTR_END])
    if ATTR_BRIGHTNESS in call.data:
        changes["brightness"] = call.data[ATTR_BRIGHTNESS]
    await entry.runtime_data.coordinator.async_update_brightness_schedule(**changes)


async def _set_plugin_schedule(entry: ObegraensadConfigEntry, call: ServiceCall) -> None:
    coordinator = entry.runtime_data.coordinator
    action = call.data[ATTR_ACTION]
    items: list[ScheduleItem] | None = None
    if action == "set":
        items = [
            ScheduleItem(coordinator.resolve_plugin(i[ATTR_PLUGIN]).id, i[ATTR_DURATION])
            for i in call.data.get(ATTR_SCHEDULE, [])
        ]
    await coordinator.async_plugin_schedule(action, items)


async def _send_message(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    data = entry.runtime_data
    message = data.messages.build(
        call.data[ATTR_TEXT],
        repeat=call.data.get(ATTR_REPEAT),
        delay=call.data.get(ATTR_DELAY),
        graph=call.data.get(ATTR_GRAPH),
        miny=call.data[ATTR_MINY],
        maxy=call.data[ATTR_MAXY],
        priority=call.data[ATTR_PRIORITY],
        key=call.data.get(ATTR_MESSAGE_ID),
    )
    if call.data[ATTR_RESTORE]:
        # text cannot be read over a held DDP frame, so end it first
        await data.display.async_release()
    return await data.messages.async_send(message)


async def _remove_message(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    key = None if call.data[ATTR_ALL] else call.data.get(ATTR_MESSAGE_ID)
    if key is None and not call.data[ATTR_ALL]:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_message_id")
    removed = await entry.runtime_data.messages.async_remove(key)
    return {"removed": removed}


EntryHandler = Callable[[ObegraensadConfigEntry, ServiceCall], Awaitable[ServiceResponse | None]]


def _register(
    hass: HomeAssistant,
    name: str,
    schema: vol.Schema | vol.All,
    handler: EntryHandler,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    """Register a service that runs ``handler`` once per targeted lamp."""

    async def _call(call: ServiceCall) -> ServiceResponse:
        responses: dict[str, Any] = {}
        for entry in resolve_entries(hass, call):
            result = await handler(entry, call)
            if result is not None:
                responses[entry.entry_id] = result
        if supports_response is SupportsResponse.NONE:
            return None
        return {"lamps": responses}

    hass.services.async_register(DOMAIN, name, _call, schema, supports_response)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register all services."""
    _register(hass, SERVICE_SELECT_PLUGIN, SELECT_PLUGIN_SCHEMA, _select_plugin)
    _register(
        hass, SERVICE_SET_BRIGHTNESS_SCHEDULE, BRIGHTNESS_SCHEDULE_SCHEMA, _set_brightness_schedule
    )
    _register(hass, SERVICE_SET_PLUGIN_SCHEDULE, PLUGIN_SCHEDULE_SCHEMA, _set_plugin_schedule)
    _register(
        hass,
        SERVICE_SEND_MESSAGE,
        SEND_MESSAGE_SCHEMA,
        _send_message,
        SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_REMOVE_MESSAGE,
        REMOVE_MESSAGE_SCHEMA,
        _remove_message,
        SupportsResponse.OPTIONAL,
    )
