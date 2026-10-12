"""Config flow for Lumagen integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .client import ASPECT_COMMANDS, LumagenClient
from .const import (
    CONF_ASPECT_RATIOS,
    CONF_KEEPALIVE_INTERVAL,
    CONF_MUTE_ENTITY,
    CONF_OSD_BACKGROUND,
    CONF_OSD_BLEND,
    CONF_OSD_COLORS,
    CONF_OSD_FOREGROUND,
    CONF_VOLUME_ENABLED,
    CONF_VOLUME_ENTITY,
    CONF_VOLUME_FULL_SCALE,
    CONF_VOLUME_PATTERN,
    CONF_WATCHDOG,
    CONF_WATCHDOG_TIMEOUT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_WATCHDOG,
    DEFAULT_WATCHDOG_TIMEOUT,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
)
from .osd_pattern import SOLID, VolumePattern, preview_samples
from .volume_osd import read_volume

_LOGGER = logging.getLogger(__name__)

ALL_ASPECT_KEYS = list(ASPECT_COMMANDS.keys())

# Selector value standing in for "" (selectors can't carry an empty value).
_NONE = "none"
_PATTERN_KEYS = set(VolumePattern().to_dict())

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


class LumagenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lumagen."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Return the options flow handler."""
        return LumagenOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user configuration — host and port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            if await self._test_connection(host, port):
                await self.async_set_unique_id(f"{host}_{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Lumagen ({host})",
                    data=user_input,
                )
            errors["base"] = ERROR_CANNOT_CONNECT

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of host and port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            if await self._test_connection(host, port):
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    title=f"Lumagen ({host})",
                    data={CONF_HOST: host, CONF_PORT: port},
                    unique_id=f"{host}_{port}",
                )
            errors["base"] = ERROR_CANNOT_CONNECT

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
                    vol.Required(
                        CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    async def _test_connection(host: str, port: int) -> bool:
        """Connect via LumagenClient and verify the device responds."""
        client = LumagenClient(host, port)
        try:
            await client.connect()
            if not await client.wait_for(lambda s: s.connected, timeout=5):
                _LOGGER.debug("Connection test: TCP connect failed")
                return False
            await client.query_runtime()
            if not await client.wait_for(lambda s: s.power is not None, timeout=5):
                _LOGGER.debug("Connection test: device did not respond")
                return False
            return True
        except Exception:
            _LOGGER.debug(
                "Connection test failed for %s:%s",
                host,
                port,
                exc_info=True,
            )
            return False
        finally:
            await client.disconnect()


def _choices(values: list[tuple[str, str]]) -> list[SelectOptionDict]:
    return [SelectOptionDict(value=v, label=label) for v, label in values]


_LINES = _choices([("1", "1 line"), ("2", "2 lines (label/value above, bar below)")])
_BAR_TYPES = _choices(
    [
        ("none", "None (text only)"),
        ("left_to_right", "Left to right"),
        ("center_out", "Center out"),
    ]
)
_PLACEMENTS = _choices([("left", "Left"), ("center", "Center"), ("right", "Right")])
_FILL = _choices(
    [(SOLID, "Solid block"), ("=", "="), ("#", "#"), ("*", "*"), ("+", "+"), (">", ">")]
)
_EMPTY = _choices(
    [
        (_NONE, "None (blank)"),
        ("-", "-"),
        (".", "."),
        (":", ":"),
        ("_", "_"),
        ("=", "="),
    ]
)
_CAPS = _choices([(_NONE, "None"), ("[]", "[ ]"), ("<>", "< >"), ("()", "( )")])
_VALUE_DISPLAY = _choices(
    [
        ("raw", "Raw value (as the entity reports it)"),
        ("percent", "Percent of range"),
        ("linear", "Custom: value x scale + offset (e.g. Denon dB: x100 -80)"),
    ]
)
_MUTE_DISPLAY = _choices(
    [
        ("text", "Mute text"),
        ("empty_bar", "Empty bar with label and mute text"),
        ("none", "Nothing"),
    ]
)
_WATCHDOG = _choices(
    [
        ("auto", "Auto (detect Lumagen echo)"),
        ("echo", "Echo-based (Echo-RS232 must be On)"),
        ("query", "Query-based (works with Echo Off)"),
        ("off", "Off (keepalive only)"),
    ]
)
_OSD_COLORS = _choices(
    [
        ("device", "Leave the Lumagen setting alone"),
        ("dark_translucent", "White on translucent black"),
        ("high_contrast", "Yellow on solid black"),
        ("custom", "Custom"),
    ]
)


def _select(options: list[SelectOptionDict], *, custom: bool = False):
    return SelectSelector(
        SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.DROPDOWN, custom_value=custom
        )
    )


def _number(minimum: float, maximum: float, step: float = 1):
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX
        )
    )


_TEXT = TextSelector(TextSelectorConfig())


def _pattern_from_form(user_input: dict[str, Any]) -> VolumePattern:
    """Build a VolumePattern from the flat options form."""
    data = {k: v for k, v in user_input.items() if k in _PATTERN_KEYS}
    for key in ("empty_char", "end_caps"):
        if data.get(key) == _NONE:
            data[key] = ""
    for key in ("label", "value_suffix", "mute_text"):
        data.setdefault(key, "")
    return VolumePattern.from_dict(data)


def _pattern_to_form(pattern: VolumePattern) -> dict[str, Any]:
    data = pattern.to_dict()
    data["lines"] = str(data["lines"])
    for key in ("empty_char", "end_caps"):
        if data[key] == "":
            data[key] = _NONE
    return data


class LumagenOptionsFlow(OptionsFlow):
    """Handle Lumagen options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending: dict[str, Any] = {}

    def _save(self, updates: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data={**self._config_entry.options, **updates})

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Top-level options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "aspect_ratios",
                "volume_display",
                "osd_colors",
                "connection",
            ],
        )

    async def async_step_aspect_ratios(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure which aspect ratios appear in the select menu."""
        if user_input is not None:
            return self._save(user_input)

        current = self._config_entry.options.get(CONF_ASPECT_RATIOS, ALL_ASPECT_KEYS)

        schema = vol.Schema(
            {
                vol.Required(CONF_ASPECT_RATIOS, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=k, label=k) for k in ALL_ASPECT_KEYS
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="aspect_ratios", data_schema=schema)

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Link watchdog and keepalive settings."""
        if user_input is not None:
            return self._save(
                {
                    CONF_WATCHDOG: user_input[CONF_WATCHDOG],
                    CONF_WATCHDOG_TIMEOUT: float(user_input[CONF_WATCHDOG_TIMEOUT]),
                    CONF_KEEPALIVE_INTERVAL: int(user_input[CONF_KEEPALIVE_INTERVAL]),
                }
            )
        opts = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WATCHDOG, default=opts.get(CONF_WATCHDOG, DEFAULT_WATCHDOG)
                ): _select(_WATCHDOG),
                vol.Required(
                    CONF_WATCHDOG_TIMEOUT,
                    default=opts.get(CONF_WATCHDOG_TIMEOUT, DEFAULT_WATCHDOG_TIMEOUT),
                ): _number(0.5, 10, 0.5),
                vol.Required(
                    CONF_KEEPALIVE_INTERVAL,
                    default=opts.get(
                        CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL
                    ),
                ): _number(10, 300),
            }
        )
        return self.async_show_form(step_id="connection", data_schema=schema)

    async def async_step_osd_colors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """OSD message colors (applied after each power-on)."""
        errors: dict[str, str] = {}
        opts = self._config_entry.options
        if user_input is not None:
            fg = str(user_input.get(CONF_OSD_FOREGROUND, "ffffff")).lstrip("#")
            bg = str(user_input.get(CONF_OSD_BACKGROUND, "000000")).lstrip("#")
            for key, value in ((CONF_OSD_FOREGROUND, fg), (CONF_OSD_BACKGROUND, bg)):
                if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
                    errors[key] = "invalid_color"
            if not errors:
                return self._save(
                    {
                        CONF_OSD_COLORS: user_input[CONF_OSD_COLORS],
                        CONF_OSD_FOREGROUND: fg.lower(),
                        CONF_OSD_BACKGROUND: bg.lower(),
                        CONF_OSD_BLEND: int(user_input[CONF_OSD_BLEND]),
                    }
                )
            opts = user_input
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OSD_COLORS, default=opts.get(CONF_OSD_COLORS, "device")
                ): _select(_OSD_COLORS),
                vol.Optional(
                    CONF_OSD_FOREGROUND, default=opts.get(CONF_OSD_FOREGROUND, "ffffff")
                ): _TEXT,
                vol.Optional(
                    CONF_OSD_BACKGROUND, default=opts.get(CONF_OSD_BACKGROUND, "000000")
                ): _TEXT,
                vol.Required(
                    CONF_OSD_BLEND, default=opts.get(CONF_OSD_BLEND, 15)
                ): _number(1, 15),
            }
        )
        return self.async_show_form(
            step_id="osd_colors", data_schema=schema, errors=errors
        )

    async def async_step_volume_display(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Volume follower + pattern builder."""
        errors: dict[str, str] = {}
        opts = self._config_entry.options
        if user_input is not None:
            pattern = _pattern_from_form(user_input)
            for key in pattern.errors():
                errors[key] = "invalid_pattern"
            if user_input.get(CONF_VOLUME_ENABLED) and not user_input.get(
                CONF_VOLUME_ENTITY
            ):
                errors[CONF_VOLUME_ENTITY] = "volume_entity_required"
            if not errors:
                self._pending = {
                    CONF_VOLUME_ENABLED: bool(user_input.get(CONF_VOLUME_ENABLED)),
                    CONF_VOLUME_ENTITY: user_input.get(CONF_VOLUME_ENTITY, ""),
                    CONF_MUTE_ENTITY: user_input.get(CONF_MUTE_ENTITY, ""),
                    CONF_VOLUME_FULL_SCALE: user_input.get(CONF_VOLUME_FULL_SCALE),
                    CONF_VOLUME_PATTERN: pattern.to_dict(),
                }
                return await self.async_step_volume_preview()
            form = user_input
        else:
            form = {
                CONF_VOLUME_ENABLED: opts.get(CONF_VOLUME_ENABLED, False),
                CONF_VOLUME_ENTITY: opts.get(CONF_VOLUME_ENTITY),
                CONF_MUTE_ENTITY: opts.get(CONF_MUTE_ENTITY),
                CONF_VOLUME_FULL_SCALE: opts.get(CONF_VOLUME_FULL_SCALE),
                **_pattern_to_form(
                    VolumePattern.from_dict(dict(opts.get(CONF_VOLUME_PATTERN, {})))
                ),
            }

        def sv(key: str) -> dict[str, Any]:
            value = form.get(key)
            return {} if value in (None, "") else {"suggested_value": value}

        defaults = _pattern_to_form(VolumePattern())

        def dv(key: str) -> Any:
            value = form.get(key)
            return defaults[key] if value in (None, "") else value

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_VOLUME_ENABLED, default=bool(form.get(CONF_VOLUME_ENABLED))
                ): BooleanSelector(),
                vol.Optional(
                    CONF_VOLUME_ENTITY, description=sv(CONF_VOLUME_ENTITY)
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["number", "input_number", "media_player", "sensor"]
                    )
                ),
                vol.Optional(
                    CONF_MUTE_ENTITY, description=sv(CONF_MUTE_ENTITY)
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=[
                            "switch",
                            "input_boolean",
                            "binary_sensor",
                            "media_player",
                        ]
                    )
                ),
                vol.Optional(
                    CONF_VOLUME_FULL_SCALE, description=sv(CONF_VOLUME_FULL_SCALE)
                ): _number(-1000, 1000, 0.01),
                vol.Required("lines", default=dv("lines")): _select(_LINES),
                vol.Required("bar_type", default=dv("bar_type")): _select(_BAR_TYPES),
                vol.Required("value_placement", default=dv("value_placement")): _select(
                    _PLACEMENTS
                ),
                vol.Required("bar_width", default=dv("bar_width")): _number(0, 30),
                vol.Required("fill_char", default=dv("fill_char")): _select(
                    _FILL, custom=True
                ),
                vol.Required("empty_char", default=dv("empty_char")): _select(
                    _EMPTY, custom=True
                ),
                vol.Required("end_caps", default=dv("end_caps")): _select(
                    _CAPS, custom=True
                ),
                vol.Optional("label", description=sv("label")): _TEXT,
                vol.Optional("value_suffix", description=sv("value_suffix")): _TEXT,
                vol.Required("value_display", default=dv("value_display")): _select(
                    _VALUE_DISPLAY
                ),
                vol.Required("value_scale", default=dv("value_scale")): _number(
                    -1000, 1000, 0.001
                ),
                vol.Required("value_offset", default=dv("value_offset")): _number(
                    -1000, 1000, 0.001
                ),
                vol.Required("decimals", default=dv("decimals")): _number(0, 2),
                vol.Required(
                    "min_max_text", default=bool(form.get("min_max_text"))
                ): BooleanSelector(),
                vol.Required("mute_display", default=dv("mute_display")): _select(
                    _MUTE_DISPLAY
                ),
                vol.Optional("mute_text", description=sv("mute_text")): _TEXT,
                vol.Required(
                    "mute_persist", default=bool(form.get("mute_persist", True))
                ): BooleanSelector(),
                vol.Required("duration", default=dv("duration")): _number(1, 8),
            }
        )
        return self.async_show_form(
            step_id="volume_display", data_schema=schema, errors=errors
        )

    async def async_step_volume_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the rendered pattern; save or go back and edit."""
        pattern = VolumePattern.from_dict(self._pending[CONF_VOLUME_PATTERN])
        minimum, maximum = self._preview_range()
        preview = preview_samples(pattern, minimum, maximum)
        return self.async_show_menu(
            step_id="volume_preview",
            menu_options=["volume_save", "volume_display"],
            description_placeholders={"preview": f"```\n{preview}\n```"},
        )

    def _preview_range(self) -> tuple[float, float]:
        """Range of the selected volume entity (for a realistic preview)."""
        entity = self._pending.get(CONF_VOLUME_ENTITY) or ""
        _, minimum, maximum = read_volume(self.hass.states.get(entity))
        if entity.startswith("media_player."):
            minimum, maximum = 0.0, 1.0
        full_scale = self._pending.get(CONF_VOLUME_FULL_SCALE)
        if full_scale not in (None, "") and float(full_scale) > minimum:
            maximum = float(full_scale)
        return minimum, maximum

    async def async_step_volume_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Persist the pending volume display settings."""
        return self._save(self._pending)
