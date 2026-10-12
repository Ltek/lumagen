"""Base entity for the Lumagen integration."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import LumagenConnectionError
from .const import DOMAIN
from .coordinator import LumagenCoordinator


async def call_client(awaitable: Awaitable[None]) -> None:
    """Await a client call, translating errors into HA exceptions."""
    try:
        await awaitable
    except LumagenConnectionError as err:
        raise HomeAssistantError(str(err)) from err
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err


class LumagenEntity(CoordinatorEntity[LumagenCoordinator]):
    """Base class for Lumagen entities — shared device_info and availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LumagenCoordinator) -> None:
        super().__init__(coordinator)
        # device_info must be set before HA registers the entity, so seed it
        # here rather than waiting for the first coordinator update.
        data = coordinator.data
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": f"Lumagen {data.model_name or 'RadiancePro'}",
            "manufacturer": "Lumagen",
            "model": data.model_name or "RadiancePro",
            "model_id": data.model_number,
            "sw_version": data.software_revision,
            "serial_number": data.serial_number,
        }

    @property
    def available(self) -> bool:
        """Override CoordinatorEntity which ignores _attr_available."""
        return self._attr_available

    async def async_added_to_hass(self) -> None:
        """Populate state from coordinator data when entity is registered."""
        await super().async_added_to_hass()
        # The first coordinator refresh ran before platforms were set up, so
        # this entity missed that data push.  Compute initial state now.
        self._update_attrs()

    def _update_attrs(self) -> None:
        """Recompute _attr_ values from coordinator data. Override in subclasses.

        Availability tiers (subclasses override for their needs):
        - Base (sensor, select): requires connected AND power
        - Control (switch, button, remote): requires connected only
        - Diagnostic (link health): always available
        """
        data = self.coordinator.data
        self._attr_available = bool(
            self.coordinator.last_update_success and data.connected and data.power
        )

    def _handle_coordinator_update(self) -> None:
        self._update_attrs()
        super()._handle_coordinator_update()
