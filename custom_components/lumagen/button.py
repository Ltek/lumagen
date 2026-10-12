"""Button platform for Lumagen integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import LumagenEntity, call_client


@dataclass(frozen=True, kw_only=True)
class LumagenButtonEntityDescription(ButtonEntityDescription):
    """Describes a Lumagen button."""

    press_fn: Callable[[LumagenCoordinator], Awaitable[None]]
    available_in_standby: bool = False


BUTTONS: tuple[LumagenButtonEntityDescription, ...] = (
    LumagenButtonEntityDescription(
        key="reload_config",
        translation_key="reload_config",
        icon="mdi:refresh",
        entity_category=EntityCategory.CONFIG,
        available_in_standby=True,
        press_fn=lambda c: c.reload_config(),
    ),
    LumagenButtonEntityDescription(
        key="restart_outputs",
        translation_key="restart_outputs",
        icon="mdi:restart",
        press_fn=lambda c: c.client.restart_outputs(),
    ),
    LumagenButtonEntityDescription(
        key="nls",
        translation_key="nls",
        icon="mdi:stretch-to-page-outline",
        press_fn=lambda c: c.client.send_nls_command(),
    ),
    LumagenButtonEntityDescription(
        key="reset_auto_aspect",
        translation_key="reset_auto_aspect",
        icon="mdi:aspect-ratio",
        entity_registry_enabled_default=False,
        press_fn=lambda c: c.client.reset_auto_aspect(),
    ),
    LumagenButtonEntityDescription(
        key="hotplug_all",
        translation_key="hotplug_all",
        icon="mdi:video-input-hdmi",
        entity_registry_enabled_default=False,
        press_fn=lambda c: c.client.hotplug(None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumagenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumagen buttons."""
    coordinator = entry.runtime_data
    async_add_entities(LumagenButton(coordinator, desc) for desc in BUTTONS)


class LumagenButton(LumagenEntity, ButtonEntity):
    """A Lumagen button."""

    entity_description: LumagenButtonEntityDescription

    def __init__(
        self,
        coordinator: LumagenCoordinator,
        description: LumagenButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    def _update_attrs(self) -> None:
        super()._update_attrs()
        if self.entity_description.available_in_standby:
            data = self.coordinator.data
            self._attr_available = (
                self.coordinator.last_update_success and data.connected
            )

    async def async_press(self) -> None:
        await call_client(self.entity_description.press_fn(self.coordinator))
