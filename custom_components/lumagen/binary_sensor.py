"""Binary sensor platform for Lumagen integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import LumagenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumagenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumagen binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [LumagenConnectedSensor(coordinator), LumagenGameModeSensor(coordinator)]
    )


class LumagenConnectedSensor(LumagenEntity, BinarySensorEntity):
    """On only while the Lumagen itself answers (not just the TCP adapter)."""

    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LumagenCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_connected"

    def _update_attrs(self) -> None:
        self._attr_available = True
        health = self.coordinator.client.health
        self._attr_is_on = self.coordinator.data.connected
        self._attr_extra_state_attributes = {
            "host": self.coordinator.client.host,
            "port": self.coordinator.client.port,
            "echo_detected": health.echo_detected,
            "watchdog": health.watchdog_mode,
            "disconnects": health.disconnects,
            "reconnects": health.reconnects,
            "consecutive_failures": health.consecutive_failures,
            "last_disconnect_reason": health.last_disconnect_reason,
        }


class LumagenGameModeSensor(LumagenEntity, BinarySensorEntity):
    """Game mode of the current input (ZQI53)."""

    _attr_translation_key = "game_mode"
    _attr_icon = "mdi:controller"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: LumagenCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_game_mode"

    def _update_attrs(self) -> None:
        super()._update_attrs()
        self._attr_is_on = self.coordinator.data.game_mode
