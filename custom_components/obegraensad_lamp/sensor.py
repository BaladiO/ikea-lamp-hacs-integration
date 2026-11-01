"""Diagnostic sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LampState
from .const import RESET_REASONS
from .coordinator import LampCoordinator, ObegraensadConfigEntry
from .entity import LampEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LampSensorDescription(SensorEntityDescription):
    """Describes a lamp sensor."""

    value_fn: Callable[[LampState], str | int | None]


SENSORS: tuple[LampSensorDescription, ...] = (
    LampSensorDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.rssi,
    ),
    LampSensorDescription(
        key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.uptime,
    ),
    LampSensorDescription(
        key="free_heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.free_heap,
    ),
    LampSensorDescription(
        key="reset_reason",
        device_class=SensorDeviceClass.ENUM,
        options=RESET_REASONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.reset_reason if s.reset_reason in RESET_REASONS else "unknown",
    ),
    LampSensorDescription(
        key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.ip_address,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObegraensadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the diagnostic sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(LampSensor(coordinator, d) for d in SENSORS)


class LampSensor(LampEntity, SensorEntity):
    """A value from ``/api/info``."""

    entity_description: LampSensorDescription

    def __init__(self, coordinator: LampCoordinator, description: LampSensorDescription) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        """Current value."""
        return self.entity_description.value_fn(self.coordinator.data)
