"""Remote platform for Lumagen integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import REMOTE_COMMANDS
from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import LumagenEntity, call_client

_LOGGER = logging.getLogger(__name__)

# Gap between consecutive key presses when delay_secs is not given.
DEFAULT_KEY_DELAY = 0.1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumagenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumagen remote."""
    async_add_entities([LumagenRemoteEntity(entry.runtime_data)])


class LumagenRemoteEntity(LumagenEntity, RemoteEntity):
    """Remote entity for Lumagen menu navigation."""

    _attr_name = None
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: LumagenCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_remote"

    def _update_attrs(self) -> None:
        super()._update_attrs()
        data = self.coordinator.data
        # Available in standby so power-on works via the remote entity
        self._attr_available = self.coordinator.last_update_success and data.connected
        self._attr_is_on = bool(data.power)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await call_client(self.coordinator.client.power_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await call_client(self.coordinator.client.power_off())

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send key presses; honors num_repeats and delay_secs."""
        data = self.coordinator.data
        if not data or not data.power:
            raise HomeAssistantError("Lumagen is in standby; turn it on first")

        commands = list(command)
        unknown = [c for c in commands if c.lower() not in REMOTE_COMMANDS]
        if unknown:
            raise ServiceValidationError(
                f"Unknown Lumagen remote command(s): {', '.join(unknown)}"
            )

        repeats = max(1, int(kwargs.get(ATTR_NUM_REPEATS) or 1))
        delay = kwargs.get(ATTR_DELAY_SECS)
        delay = DEFAULT_KEY_DELAY if delay is None else max(0.0, float(delay))

        first = True
        for _ in range(repeats):
            for cmd in commands:
                if not first:
                    await asyncio.sleep(delay)
                first = False
                await call_client(self.coordinator.client.send_remote_command(cmd))
