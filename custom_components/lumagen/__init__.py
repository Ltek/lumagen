"""The Lumagen integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_MUTE_ENTITY,
    CONF_VOLUME_ENABLED,
    CONF_VOLUME_ENTITY,
    CONF_VOLUME_FULL_SCALE,
    CONF_VOLUME_PATTERN,
    DEFAULT_PORT,
    DOMAIN,
)
from .coordinator import LumagenConfigEntry, LumagenCoordinator
from .entity import call_client
from .osd_pattern import (
    BAR_TYPES,
    MUTE_DISPLAYS,
    PLACEMENTS,
    VALUE_DISPLAYS,
    VolumePattern,
    render_volume,
)
from .volume_osd import VolumeOsdFollower

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.REMOTE,
]


SERVICE_SHOW_OSD_MESSAGE = "show_osd_message"
SERVICE_SHOW_OSD_VOLUME_BAR = "show_osd_volume_bar"
SERVICE_SHOW_OSD_VOLUME = "show_osd_volume"
SERVICE_CLEAR_OSD_MESSAGE = "clear_osd_message"
SERVICE_HOTPLUG = "hotplug"
SERVICE_SET_OSD_COLORS = "set_osd_colors"

_HEX_COLOR = vol.Match(r"^#?[0-9A-Fa-f]{6}$")

SHOW_OSD_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("line_one"): cv.string,
        vol.Optional("line_two", default=""): cv.string,
        vol.Optional("duration", default=3): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=8)
        ),
        vol.Optional("block_char", default=""): cv.string,
    },
    extra=vol.REMOVE_EXTRA,
)

SHOW_OSD_VOLUME_BAR_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("level"): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        vol.Optional("label", default=None): vol.Any(None, cv.string),
    },
    extra=vol.REMOVE_EXTRA,
)

# Pattern fields are optional: anything not given comes from the volume
# display configured in the integration options (or the built-in defaults).
SHOW_OSD_VOLUME_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("value"): vol.Coerce(float),
        vol.Optional("minimum", default=0.0): vol.Coerce(float),
        vol.Optional("maximum", default=100.0): vol.Coerce(float),
        vol.Optional("muted", default=False): cv.boolean,
        vol.Optional("lines"): vol.All(vol.Coerce(int), vol.In([1, 2])),
        vol.Optional("bar_type"): vol.In(BAR_TYPES),
        vol.Optional("value_placement"): vol.In(PLACEMENTS),
        vol.Optional("bar_width"): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
        vol.Optional("fill_char"): cv.string,
        vol.Optional("empty_char"): vol.Any(None, cv.string),
        vol.Optional("end_caps"): vol.Any(None, cv.string),
        vol.Optional("label"): vol.Any(None, cv.string),
        vol.Optional("value_suffix"): vol.Any(None, cv.string),
        vol.Optional("value_display"): vol.In(VALUE_DISPLAYS),
        vol.Optional("value_scale"): vol.Coerce(float),
        vol.Optional("value_offset"): vol.Coerce(float),
        vol.Optional("decimals"): vol.All(vol.Coerce(int), vol.Range(min=0, max=2)),
        vol.Optional("min_max_text"): cv.boolean,
        vol.Optional("mute_display"): vol.In(MUTE_DISPLAYS),
        vol.Optional("mute_text"): vol.Any(None, cv.string),
        vol.Optional("mute_persist"): cv.boolean,
        vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    },
    extra=vol.REMOVE_EXTRA,
)

CLEAR_OSD_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    },
    extra=vol.REMOVE_EXTRA,
)

HOTPLUG_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("input"): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    },
    extra=vol.REMOVE_EXTRA,
)

SET_OSD_COLORS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("foreground"): _HEX_COLOR,
        vol.Required("background"): _HEX_COLOR,
        vol.Optional("blend", default=15): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=15)
        ),
    },
    extra=vol.REMOVE_EXTRA,
)

_PATTERN_FIELDS = set(VolumePattern().to_dict())


def _get_coordinator(hass: HomeAssistant, entity_id: str) -> LumagenCoordinator:
    """Resolve an entity_id to its LumagenCoordinator."""
    ent_reg = er.async_get(hass)
    entity = ent_reg.async_get(entity_id)
    if entity is None or entity.config_entry_id is None:
        raise ServiceValidationError(f"Unknown entity: {entity_id}")

    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise ServiceValidationError(f"No loaded Lumagen device for: {entity_id}")
    coordinator: LumagenCoordinator = entry.runtime_data
    return coordinator


def configured_pattern(entry: LumagenConfigEntry) -> VolumePattern:
    """Volume pattern from options (defaults if not configured)."""
    return VolumePattern.from_dict(dict(entry.options.get(CONF_VOLUME_PATTERN, {})))


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up domain-level services."""

    async def show_osd_message(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        await call_client(
            coordinator.client.show_osd_message(
                line_one=call.data["line_one"],
                line_two=call.data["line_two"],
                duration=call.data["duration"],
                block_char=call.data["block_char"],
            )
        )

    async def show_osd_volume_bar(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        await call_client(
            coordinator.client.show_osd_volume_bar(
                call.data["level"], label=call.data.get("label")
            )
        )

    async def show_osd_volume(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        overrides = {
            k: ("" if v is None else v)
            for k, v in call.data.items()
            if k in _PATTERN_FIELDS
        }
        base = configured_pattern(coordinator.entry).to_dict()
        pattern = VolumePattern.from_dict({**base, **overrides})
        if errors := pattern.errors():
            raise ServiceValidationError(
                "; ".join(f"{k}: {v}" for k, v in errors.items())
            )
        muted = call.data["muted"]
        if not muted and "value" not in call.data:
            raise ServiceValidationError("value is required unless muted is true")
        frame = render_volume(
            pattern,
            call.data.get("value"),
            minimum=call.data["minimum"],
            maximum=call.data["maximum"],
            muted=muted,
        )
        if frame is None:
            return
        await call_client(
            coordinator.client.show_osd_message(
                frame.line_one,
                frame.line_two,
                duration=frame.duration,
                block_char=frame.block_char,
            )
        )

    async def clear_osd_message(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        await call_client(coordinator.client.clear_osd_message())

    async def hotplug(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        await call_client(coordinator.client.hotplug(call.data.get("input")))

    async def set_osd_colors(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entity_id"])
        await call_client(
            coordinator.client.set_osd_colors(
                call.data["foreground"].lstrip("#"),
                call.data["background"].lstrip("#"),
                call.data["blend"],
            )
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_OSD_MESSAGE,
        show_osd_message,
        SHOW_OSD_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_OSD_VOLUME_BAR,
        show_osd_volume_bar,
        SHOW_OSD_VOLUME_BAR_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_OSD_VOLUME,
        show_osd_volume,
        SHOW_OSD_VOLUME_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_OSD_MESSAGE,
        clear_osd_message,
        CLEAR_OSD_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_HOTPLUG,
        hotplug,
        HOTPLUG_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OSD_COLORS,
        set_osd_colors,
        SET_OSD_COLORS_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: LumagenConfigEntry) -> bool:
    """Set up Lumagen from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    coordinator = LumagenCoordinator(hass, entry, host, port)

    try:
        if not await coordinator.async_connect():
            raise ConfigEntryNotReady(f"Lumagen at {host}:{port} did not respond")

        # Seed device info from stored state (identity + labels)
        has_stored = await coordinator.async_load_stored_state()

        if not has_stored and not await coordinator.client.query_config():
            raise ConfigEntryNotReady("Config query incomplete")

        # Kick off runtime state (power arrives shortly after)
        await coordinator.client.query_runtime()

        if not has_stored:
            await coordinator.async_save_stored_state()
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # Never leave a connected client (and its reconnect loop) behind:
        # adapters like the iTach allow a single TCP client by default.
        await coordinator.client.disconnect()
        raise
    except asyncio.CancelledError:
        await coordinator.client.disconnect()
        raise
    except Exception as err:
        await coordinator.client.disconnect()
        _LOGGER.error("Failed to set up Lumagen at %s:%s: %s", host, port, err)
        raise ConfigEntryNotReady(f"Failed to set up: {err}") from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _start_volume_osd(hass, entry, coordinator)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info("Lumagen integration ready (%s:%s)", host, port)
    return True


def _start_volume_osd(
    hass: HomeAssistant, entry: LumagenConfigEntry, coordinator: LumagenCoordinator
) -> None:
    options = entry.options
    volume_entity = options.get(CONF_VOLUME_ENTITY)
    if not options.get(CONF_VOLUME_ENABLED) or not volume_entity:
        return
    pattern = configured_pattern(entry)
    if errors := pattern.errors():
        _LOGGER.error("Volume display disabled — invalid pattern: %s", errors)
        return
    full_scale = options.get(CONF_VOLUME_FULL_SCALE)
    follower = VolumeOsdFollower(
        hass,
        coordinator,
        volume_entity=volume_entity,
        mute_entity=options.get(CONF_MUTE_ENTITY) or None,
        pattern=pattern,
        full_scale=float(full_scale) if full_scale not in (None, "") else None,
    )
    follower.async_start()
    coordinator.volume_osd = follower


async def _async_options_updated(
    hass: HomeAssistant, entry: LumagenConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LumagenConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
