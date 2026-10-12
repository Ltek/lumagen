"""Sensor platform for Lumagen integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.typing import StateType

from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import LinkHealth, LumagenState
from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import LumagenEntity

NITS = "nits"


@dataclass(frozen=True, kw_only=True)
class LumagenSensorEntityDescription(SensorEntityDescription):
    """Describes Lumagen sensor entity."""

    value_fn: Callable[[LumagenState], StateType]


@dataclass(frozen=True, kw_only=True)
class LumagenHealthSensorEntityDescription(SensorEntityDescription):
    """Describes a link-health diagnostic sensor (always available)."""

    value_fn: Callable[[LinkHealth], StateType | datetime]


def _timestamp(value: float | None) -> datetime | None:
    return None if value is None else datetime.fromtimestamp(value, UTC)


STATUS_SENSORS: tuple[LumagenSensorEntityDescription, ...] = (
    LumagenSensorEntityDescription(
        key="logical_input",
        translation_key="logical_input",
        icon="mdi:video-input-hdmi",
        value_fn=lambda data: data.logical_input,
    ),
    LumagenSensorEntityDescription(
        key="physical_input",
        translation_key="physical_input",
        icon="mdi:video-input-component",
        value_fn=lambda data: data.physical_input,
    ),
    LumagenSensorEntityDescription(
        key="input_configuration",
        translation_key="input_configuration",
        icon="mdi:cog",
        value_fn=lambda data: data.input_config_number,
    ),
    # Source
    LumagenSensorEntityDescription(
        key="source_vertical_resolution",
        translation_key="source_vertical_resolution",
        icon="mdi:video",
        value_fn=lambda data: data.source_vertical_resolution,
    ),
    LumagenSensorEntityDescription(
        key="source_vertical_rate",
        translation_key="source_vertical_rate",
        icon="mdi:timer-outline",
        value_fn=lambda data: data.source_vertical_rate,
    ),
    LumagenSensorEntityDescription(
        key="source_content_aspect",
        translation_key="source_content_aspect",
        icon="mdi:aspect-ratio",
        value_fn=lambda data: data.source_content_aspect,
    ),
    LumagenSensorEntityDescription(
        key="source_raster_aspect",
        translation_key="source_raster_aspect",
        icon="mdi:aspect-ratio",
        value_fn=lambda data: data.source_raster_aspect,
    ),
    LumagenSensorEntityDescription(
        key="source_dynamic_range",
        translation_key="source_dynamic_range",
        icon="mdi:brightness-7",
        value_fn=lambda data: data.source_dynamic_range,
    ),
    LumagenSensorEntityDescription(
        key="source_mode",
        translation_key="source_mode",
        icon="mdi:scan-helper",
        value_fn=lambda data: data.source_mode,
    ),
    LumagenSensorEntityDescription(
        key="input_video_status",
        translation_key="input_video_status",
        icon="mdi:video-check",
        value_fn=lambda data: data.input_video_status,
    ),
    LumagenSensorEntityDescription(
        key="source_3d_mode",
        translation_key="source_3d_mode",
        icon="mdi:video-3d",
        value_fn=lambda data: data.source_3d_mode,
    ),
    LumagenSensorEntityDescription(
        key="nls",
        translation_key="nls",
        icon="mdi:arrow-expand-horizontal",
        value_fn=lambda data: data.nls,
    ),
    LumagenSensorEntityDescription(
        key="detected_content_aspect",
        translation_key="detected_content_aspect",
        icon="mdi:aspect-ratio",
        value_fn=lambda data: data.detected_content_aspect,
    ),
    LumagenSensorEntityDescription(
        key="detected_raster_aspect",
        translation_key="detected_raster_aspect",
        icon="mdi:aspect-ratio",
        value_fn=lambda data: data.detected_raster_aspect,
    ),
    # Output
    LumagenSensorEntityDescription(
        key="output_vertical_resolution",
        translation_key="output_vertical_resolution",
        icon="mdi:monitor",
        value_fn=lambda data: data.output_vertical_resolution,
    ),
    LumagenSensorEntityDescription(
        key="output_vertical_rate",
        translation_key="output_vertical_rate",
        icon="mdi:timer-outline",
        value_fn=lambda data: data.output_vertical_rate,
    ),
    LumagenSensorEntityDescription(
        key="output_aspect",
        translation_key="output_aspect",
        icon="mdi:aspect-ratio",
        value_fn=lambda data: data.output_aspect,
    ),
    LumagenSensorEntityDescription(
        key="output_3d_mode",
        translation_key="output_3d_mode",
        icon="mdi:video-3d",
        value_fn=lambda data: data.output_3d_mode,
    ),
    LumagenSensorEntityDescription(
        key="outputs_on",
        translation_key="outputs_on",
        icon="mdi:video-output",
        value_fn=lambda data: (
            ", ".join(
                str(i + 1)
                for i in range(4)
                if data.outputs_on is not None and data.outputs_on & (1 << i)
            )
            or None
        ),
    ),
    LumagenSensorEntityDescription(
        key="output_mode",
        translation_key="output_mode",
        icon="mdi:scan-helper",
        value_fn=lambda data: data.output_mode,
    ),
    LumagenSensorEntityDescription(
        key="output_colorspace",
        translation_key="output_colorspace",
        icon="mdi:palette",
        value_fn=lambda data: data.output_colorspace,
    ),
    LumagenSensorEntityDescription(
        key="output_cms",
        translation_key="output_cms",
        icon="mdi:palette",
        value_fn=lambda data: data.output_cms,
    ),
    LumagenSensorEntityDescription(
        key="output_cms_label",
        translation_key="output_cms_label",
        icon="mdi:palette",
        value_fn=lambda data: data.cms_label,
    ),
    LumagenSensorEntityDescription(
        key="output_style",
        translation_key="output_style",
        icon="mdi:image-filter-hdr",
        value_fn=lambda data: data.output_style,
    ),
    LumagenSensorEntityDescription(
        key="output_style_label",
        translation_key="output_style_label",
        icon="mdi:image-filter-hdr",
        value_fn=lambda data: data.style_label,
    ),
    LumagenSensorEntityDescription(
        key="input_label",
        translation_key="input_label",
        icon="mdi:label-outline",
        value_fn=lambda data: data.input_label,
    ),
    # HDR metadata (I52) — unknown while the source is SDR
    LumagenSensorEntityDescription(
        key="hdr_max_luminance",
        translation_key="hdr_max_luminance",
        icon="mdi:brightness-7",
        native_unit_of_measurement=NITS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.hdr_max_luminance,
    ),
    LumagenSensorEntityDescription(
        key="hdr_min_luminance",
        translation_key="hdr_min_luminance",
        icon="mdi:brightness-4",
        native_unit_of_measurement=NITS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.hdr_min_luminance,
    ),
    LumagenSensorEntityDescription(
        key="hdr_max_cll",
        translation_key="hdr_max_cll",
        icon="mdi:white-balance-sunny",
        native_unit_of_measurement=NITS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.hdr_max_cll,
    ),
)

HEALTH_SENSORS: tuple[LumagenHealthSensorEntityDescription, ...] = (
    LumagenHealthSensorEntityDescription(
        key="last_data_received",
        translation_key="last_data_received",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: _timestamp(h.last_data_received),
    ),
    LumagenHealthSensorEntityDescription(
        key="reconnects",
        translation_key="reconnects",
        icon="mdi:connection",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: h.reconnects,
    ),
    LumagenHealthSensorEntityDescription(
        key="last_disconnect_reason",
        translation_key="last_disconnect_reason",
        icon="mdi:lan-disconnect",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: (h.last_disconnect_reason or "")[:255] or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumagenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumagen sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        LumagenSensorEntity(coordinator, desc) for desc in STATUS_SENSORS
    ]
    entities.extend(LumagenHealthSensor(coordinator, desc) for desc in HEALTH_SENSORS)
    async_add_entities(entities)


class LumagenSensorEntity(LumagenEntity, SensorEntity):
    """A Lumagen sensor entity."""

    entity_description: LumagenSensorEntityDescription

    def __init__(
        self,
        coordinator: LumagenCoordinator,
        description: LumagenSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    def _update_attrs(self) -> None:
        super()._update_attrs()
        data = self.coordinator.data
        self._attr_native_value = self.entity_description.value_fn(data)


class LumagenHealthSensor(LumagenEntity, SensorEntity):
    """Link-health diagnostic sensor — available even when disconnected."""

    entity_description: LumagenHealthSensorEntityDescription

    def __init__(
        self,
        coordinator: LumagenCoordinator,
        description: LumagenHealthSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    def _update_attrs(self) -> None:
        self._attr_available = True
        self._attr_native_value = self.entity_description.value_fn(
            self.coordinator.client.health
        )
