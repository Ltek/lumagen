"""Select platform for Lumagen integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import ASPECT_COMMANDS, InputMemory, LumagenState
from .const import CONF_ASPECT_RATIOS
from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import LumagenEntity, call_client

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class LumagenSelectEntityDescription(SelectEntityDescription):
    """Describes Lumagen select entity."""

    current_option_fn: Callable[[LumagenState, LumagenCoordinator], str | None]
    select_option_fn: Callable[[LumagenCoordinator, str], Awaitable[None]]
    options_fn: Callable[[LumagenCoordinator], list[str]] | None = None
    static_options: list[str] | None = None


# -- Option callbacks -------------------------------------------------------


def _current_input_source(data: LumagenState, coord: LumagenCoordinator) -> str | None:
    """Map logical_input back to its label in the current source list."""
    if data.logical_input is None:
        return None
    source_list = coord.client.get_source_list()
    idx = data.logical_input - 1  # logical_input is 1-based
    if 0 <= idx < len(source_list):
        return source_list[idx]
    return None


async def _select_input_source(coord: LumagenCoordinator, option: str) -> None:
    source_list = coord.client.get_source_list()
    try:
        input_number = source_list.index(option) + 1  # 1-based
    except ValueError:
        _LOGGER.error("Could not find input number for label: %s", option)
        return
    await coord.client.select_input(input_number)


def _configured_aspects(coord: LumagenCoordinator) -> list[str]:
    """Return the user-configured aspect ratio list."""
    return coord.entry.options.get(CONF_ASPECT_RATIOS, list(ASPECT_COMMANDS.keys()))


def _current_aspect(data: LumagenState, coord: LumagenCoordinator) -> str | None:
    aspect = data.source_aspect
    if aspect is None:
        return None
    configured = _configured_aspects(coord)
    return aspect if aspect in configured else None


async def _select_aspect(coord: LumagenCoordinator, option: str) -> None:
    await coord.client.set_aspect(option)


def _current_memory(data: LumagenState, _coord: LumagenCoordinator) -> str | None:
    if data.input_memory is None:
        return None
    return f"MEM{data.input_memory}"


async def _select_memory(coord: LumagenCoordinator, option: str) -> None:
    await coord.client.select_memory(cast("InputMemory", option[-1]))  # "MEMA" → "A"


def _label_options(coord: LumagenCoordinator, prefix: str, name: str) -> list[str]:
    """Options like 'Rec709 (0)' built from cached CMS / style labels."""
    labels = coord.client.state.labels_by_prefix(prefix)
    return [f"{labels.get(f'{prefix}{i}') or f'{name} {i}'} ({i})" for i in range(8)]


def _option_index(option: str) -> int:
    """'Rec709 (3)' -> 3."""
    match = re.search(r"\((\d)\)$", option)
    if not match:
        raise ValueError(f"Unrecognized option: {option!r}")
    return int(match.group(1))


def _current_label_option(
    coord: LumagenCoordinator, prefix: str, name: str, index: int | None
) -> str | None:
    if index is None or not 0 <= index <= 7:
        return None
    return _label_options(coord, prefix, name)[index]


async def _select_cms(coord: LumagenCoordinator, option: str) -> None:
    await coord.client.set_cms(_option_index(option))


async def _select_style(coord: LumagenCoordinator, option: str) -> None:
    await coord.client.set_style(_option_index(option))


# -- Entity descriptions ----------------------------------------------------

SELECT_ENTITIES: tuple[LumagenSelectEntityDescription, ...] = (
    LumagenSelectEntityDescription(
        key="input",
        translation_key="input",
        icon="mdi:video-input-hdmi",
        current_option_fn=_current_input_source,
        select_option_fn=_select_input_source,
        options_fn=lambda coord: coord.client.get_source_list(),
    ),
    LumagenSelectEntityDescription(
        key="aspect_ratio",
        translation_key="aspect_ratio",
        icon="mdi:aspect-ratio",
        current_option_fn=_current_aspect,
        select_option_fn=_select_aspect,
        options_fn=_configured_aspects,
    ),
    LumagenSelectEntityDescription(
        key="memory",
        translation_key="memory",
        icon="mdi:memory",
        current_option_fn=_current_memory,
        select_option_fn=_select_memory,
        static_options=["MEMA", "MEMB", "MEMC", "MEMD"],
    ),
    LumagenSelectEntityDescription(
        key="cms",
        translation_key="cms",
        icon="mdi:palette",
        entity_registry_enabled_default=False,
        current_option_fn=lambda data, coord: _current_label_option(
            coord, "2", "CMS", data.output_cms
        ),
        select_option_fn=_select_cms,
        options_fn=lambda coord: _label_options(coord, "2", "CMS"),
    ),
    LumagenSelectEntityDescription(
        key="style",
        translation_key="style",
        icon="mdi:image-filter-hdr",
        entity_registry_enabled_default=False,
        current_option_fn=lambda data, coord: _current_label_option(
            coord, "3", "Style", data.output_style
        ),
        select_option_fn=_select_style,
        options_fn=lambda coord: _label_options(coord, "3", "Style"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumagenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Lumagen select entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        LumagenSelectEntity(coordinator, desc) for desc in SELECT_ENTITIES
    )


class LumagenSelectEntity(LumagenEntity, SelectEntity):
    """A Lumagen select entity."""

    entity_description: LumagenSelectEntityDescription

    def __init__(
        self,
        coordinator: LumagenCoordinator,
        description: LumagenSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._optimistic_option: str | None = None
        # HA reads options during entity registration, before the first
        # coordinator update calls _update_attrs, so seed them here.
        if description.static_options:
            self._attr_options = description.static_options
        elif description.options_fn:
            self._attr_options = description.options_fn(coordinator)
        else:
            self._attr_options = []

    def _update_attrs(self) -> None:
        super()._update_attrs()
        if self.entity_description.static_options:
            self._attr_options = self.entity_description.static_options
        elif self.entity_description.options_fn:
            self._attr_options = self.entity_description.options_fn(self.coordinator)
        else:
            self._attr_options = []
        if self._optimistic_option is not None:
            self._attr_current_option = self._optimistic_option
        else:
            self._attr_current_option = self.entity_description.current_option_fn(
                self.coordinator.data, self.coordinator
            )

    def _handle_coordinator_update(self) -> None:
        self._optimistic_option = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        self._optimistic_option = option
        self._attr_current_option = option
        self.async_write_ha_state()
        try:
            await call_client(
                self.entity_description.select_option_fn(self.coordinator, option)
            )
        except Exception:
            self._optimistic_option = None
            self._update_attrs()
            self.async_write_ha_state()
            raise
