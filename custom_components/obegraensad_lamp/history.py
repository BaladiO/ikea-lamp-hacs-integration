"""Read a sensor's numeric history from the recorder for ``show_graph``."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN


def _as_float(state: State) -> float | None:
    try:
        return float(state.state)
    except ValueError:
        return None


async def async_sample_history(
    hass: HomeAssistant, entity_id: str, hours: float, points: int
) -> list[float]:
    """Return ``points`` samples of ``entity_id`` over the last ``hours``.

    Each sample is the last numeric value at the end of its time slice, so
    slices without a change repeat the previous value.
    """
    if "recorder" not in hass.config.components:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_recorder")
    # imported late: the recorder is an optional (after-)dependency
    from homeassistant.components.recorder import get_instance, history  # noqa: PLC0415

    end = dt_util.utcnow()
    start = end - timedelta(hours=hours)
    changes = await get_instance(hass).async_add_executor_job(
        lambda: history.state_changes_during_period(
            hass, start, end, entity_id, no_attributes=True, include_start_time_state=True
        )
    )
    timeline: list[tuple[datetime, float]] = [
        (state.last_changed, value)
        for state in changes.get(entity_id, [])
        if (value := _as_float(state)) is not None
    ]
    current = hass.states.get(entity_id)
    if not timeline and current is not None and (value := _as_float(current)) is not None:
        timeline = [(start, value)]
    if not timeline:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_history",
            translation_placeholders={"entity_id": entity_id},
        )

    samples: list[float] = []
    index = 0
    last = timeline[0][1]
    step = (end - start) / points
    for i in range(1, points + 1):
        slice_end = start + step * i
        while index < len(timeline) and timeline[index][0] <= slice_end:
            last = timeline[index][1]
            index += 1
        samples.append(last)
    return samples
