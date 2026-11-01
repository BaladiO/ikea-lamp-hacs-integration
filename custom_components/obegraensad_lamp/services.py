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

from . import icons
from .api import ScheduleItem
from .const import DOMAIN
from .coordinator import ObegraensadConfigEntry
from .history import async_sample_history

SERVICE_SELECT_PLUGIN = "select_plugin"
SERVICE_SET_BRIGHTNESS_SCHEDULE = "set_brightness_schedule"
SERVICE_SET_PLUGIN_SCHEDULE = "set_plugin_schedule"
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_REMOVE_MESSAGE = "remove_message"
SERVICE_SHOW_ICON = "show_icon"
SERVICE_DRAW_FRAME = "draw_frame"
SERVICE_CLEAR = "clear"
SERVICE_SHOW_GRAPH = "show_graph"
SERVICE_RESTORE_DISPLAY = "restore_display"

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
ATTR_ICON = "icon"
ATTR_ROWS = "rows"
ATTR_PIXELS = "pixels"
ATTR_DROP_IF_BUSY = "drop_if_busy"
ATTR_VALUES = "values"
ATTR_SENSOR = "sensor"
ATTR_HOURS = "hours"
ATTR_MIN = "min"
ATTR_MAX = "max"
ATTR_NUMBER = "number"

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

DISPLAY_FIELDS = {
    **TARGET_FIELDS,
    vol.Optional(ATTR_RESTORE): cv.boolean,
    vol.Optional(ATTR_PRIORITY, default="normal"): vol.In(PRIORITIES),
    vol.Optional(ATTR_DROP_IF_BUSY, default=False): cv.boolean,
}
DURATION = vol.All(vol.Coerce(float), vol.Range(min=0.5, max=86400))

SHOW_ICON_SCHEMA = vol.Schema(
    {
        **DISPLAY_FIELDS,
        vol.Exclusive(ATTR_ICON, "what"): vol.In(sorted(icons.ICONS)),
        vol.Exclusive(ATTR_NUMBER, "what"): vol.Any(vol.Coerce(float), cv.string),
        vol.Optional(ATTR_DURATION, default=5): DURATION,
        vol.Optional(ATTR_BRIGHTNESS, default=255): vol.All(vol.Coerce(int), vol.Range(5, 255)),
    }
)

DRAW_FRAME_SCHEMA = vol.Schema(
    {
        **DISPLAY_FIELDS,
        vol.Exclusive(ATTR_ROWS, "frame"): vol.All(cv.ensure_list, [cv.string]),
        vol.Exclusive(ATTR_PIXELS, "frame"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(0, 255))]
        ),
        vol.Optional(ATTR_DURATION): DURATION,
    }
)

CLEAR_SCHEMA = vol.Schema({**DISPLAY_FIELDS, vol.Optional(ATTR_DURATION): DURATION})

SHOW_GRAPH_SCHEMA = vol.Schema(
    {
        **DISPLAY_FIELDS,
        vol.Exclusive(ATTR_VALUES, "source"): vol.All(
            cv.ensure_list, [vol.Coerce(float)], vol.Length(min=1, max=512)
        ),
        vol.Exclusive(ATTR_SENSOR, "source"): cv.entity_id,
        vol.Optional(ATTR_HOURS, default=24): vol.All(vol.Coerce(float), vol.Range(0.1, 24 * 30)),
        vol.Optional(ATTR_MIN): vol.Coerce(float),
        vol.Optional(ATTR_MAX): vol.Coerce(float),
        vol.Optional(ATTR_TEXT, default=""): cv.string,
        vol.Optional(ATTR_DELAY): vol.All(vol.Coerce(int), vol.Range(10, 1000)),
        vol.Optional(ATTR_DURATION): DURATION,
    }
)

RESTORE_DISPLAY_SCHEMA = vol.Schema(TARGET_FIELDS)

# graph points scrolled through the message route
SCROLL_POINTS = 48


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


def _invalid(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


async def _show(
    entry: ObegraensadConfigEntry,
    call: ServiceCall,
    frame: list[int],
    duration: float | None,
    label: str,
) -> ServiceResponse:
    return await entry.runtime_data.display.async_show(
        frame,
        duration=duration,
        restore=call.data.get(ATTR_RESTORE),
        priority=call.data[ATTR_PRIORITY],
        drop_if_busy=call.data[ATTR_DROP_IF_BUSY],
        label=label,
    )


async def _show_icon(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    brightness = call.data[ATTR_BRIGHTNESS]
    if ATTR_ICON in call.data:
        frame = icons.icon_frame(call.data[ATTR_ICON], brightness)
        label = call.data[ATTR_ICON]
    elif ATTR_NUMBER in call.data:
        try:
            frame = icons.number_frame(call.data[ATTR_NUMBER], brightness)
        except ValueError as err:
            raise _invalid("number_too_long", value=str(call.data[ATTR_NUMBER])) from err
        label = f"number {call.data[ATTR_NUMBER]}"
    else:
        raise _invalid("icon_missing")
    return await _show(entry, call, frame, call.data[ATTR_DURATION], label)


async def _draw_frame(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    if ATTR_ROWS in call.data:
        try:
            frame = icons.hex_rows_to_frame(call.data[ATTR_ROWS])
        except ValueError as err:
            raise _invalid("bad_frame", error=str(err)) from err
    elif ATTR_PIXELS in call.data:
        frame = list(call.data[ATTR_PIXELS])
        if len(frame) != icons.PIXELS:
            raise _invalid("bad_frame", error=f"need 256 pixels, got {len(frame)}")
    else:
        raise _invalid("bad_frame", error="give rows or pixels")
    return await _show(entry, call, frame, call.data.get(ATTR_DURATION), "frame")


async def _clear(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    return await _show(entry, call, icons.blank_frame(), call.data.get(ATTR_DURATION), "clear")


async def _show_graph(entry: ObegraensadConfigEntry, call: ServiceCall) -> ServiceResponse:
    data = entry.runtime_data
    duration = call.data.get(ATTR_DURATION)
    points = icons.SIZE if duration is not None else SCROLL_POINTS
    if ATTR_VALUES in call.data:
        values: list[float] = list(call.data[ATTR_VALUES])
    elif ATTR_SENSOR in call.data:
        values = await async_sample_history(
            data.coordinator.hass, call.data[ATTR_SENSOR], call.data[ATTR_HOURS], points
        )
    else:
        raise _invalid("graph_source_missing")
    low, high = call.data.get(ATTR_MIN), call.data.get(ATTR_MAX)
    if duration is not None:
        return await _show(entry, call, icons.bar_graph(values, low, high), duration, "graph")
    # without a duration the graph scrolls through the firmware's message route
    graph = icons.scale(icons.resample(values, min(len(values), SCROLL_POINTS)), low, high)
    message = data.messages.build(
        call.data[ATTR_TEXT],
        repeat=0,
        delay=call.data.get(ATTR_DELAY),
        graph=graph,
        miny=0,
        maxy=15,
        priority=call.data[ATTR_PRIORITY],
    )
    if call.data.get(ATTR_RESTORE, True):
        await data.display.async_release()
    return await data.messages.async_send(message)


async def _restore_display(entry: ObegraensadConfigEntry, call: ServiceCall) -> None:
    await entry.runtime_data.display.async_release()


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
    for name, schema, handler in (
        (SERVICE_SHOW_ICON, SHOW_ICON_SCHEMA, _show_icon),
        (SERVICE_DRAW_FRAME, DRAW_FRAME_SCHEMA, _draw_frame),
        (SERVICE_CLEAR, CLEAR_SCHEMA, _clear),
        (SERVICE_SHOW_GRAPH, SHOW_GRAPH_SCHEMA, _show_graph),
    ):
        _register(hass, name, schema, handler, SupportsResponse.OPTIONAL)
    _register(hass, SERVICE_RESTORE_DISPLAY, RESTORE_DISPLAY_SCHEMA, _restore_display)
    _register(
        hass,
        SERVICE_REMOVE_MESSAGE,
        REMOVE_MESSAGE_SCHEMA,
        _remove_message,
        SupportsResponse.OPTIONAL,
    )
