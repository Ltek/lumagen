"""Data coordinator for Lumagen integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import LumagenClient, LumagenConnectionError, LumagenState
from .const import (
    CONF_KEEPALIVE_INTERVAL,
    CONF_OSD_BACKGROUND,
    CONF_OSD_BLEND,
    CONF_OSD_COLORS,
    CONF_OSD_FOREGROUND,
    CONF_WATCHDOG,
    CONF_WATCHDOG_TIMEOUT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_WATCHDOG,
    DEFAULT_WATCHDOG_TIMEOUT,
    DOMAIN,
    OSD_COLOR_PRESETS,
)

if TYPE_CHECKING:
    from .volume_osd import VolumeOsdFollower

STORAGE_VERSION = 1

# Wait this long after power-on before applying OSD colors (device boot).
OSD_COLOR_DELAY = 12.0

_LOGGER = logging.getLogger(__name__)

type LumagenConfigEntry = ConfigEntry[LumagenCoordinator]


class LumagenCoordinator(DataUpdateCoordinator[LumagenState]):
    """Coordinator for Lumagen — pure event-driven, no polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        port: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        options = entry.options
        self.client = LumagenClient(
            host,
            port,
            watchdog=options.get(CONF_WATCHDOG, DEFAULT_WATCHDOG),
            watchdog_timeout=float(
                options.get(CONF_WATCHDOG_TIMEOUT, DEFAULT_WATCHDOG_TIMEOUT)
            ),
            keepalive_interval=float(
                options.get(CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL)
            ),
        )
        self.entry = entry
        self.volume_osd: VolumeOsdFollower | None = None
        self._store: Store[dict[str, object]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.info"
        )
        self._last_power: bool | None = None
        self._osd_color_task: asyncio.Task[None] | None = None

    async def async_connect(self) -> bool:
        """Connect to the Lumagen device. Returns True if it answered."""
        return await self.client.connect(
            on_state_changed=self.on_state_changed,
            on_connection_changed=self.on_connection_changed,
        )

    # -- Callbacks wired to LumagenClient -----------------------------------

    def on_state_changed(self) -> None:
        """Called (sync) by the client whenever device state changes."""
        power = self.client.state.power
        if power and not self._last_power:
            self._schedule_osd_colors()
        if power is not None:
            self._last_power = power
        self.async_set_updated_data(self.client.state)

    def on_connection_changed(self, connected: bool) -> None:
        """Called (sync) by the client on connect / disconnect."""
        _LOGGER.info("Connection %s", "established" if connected else "lost")
        if connected:
            self._last_power = None  # re-apply OSD colors once power is known
        self.async_set_updated_data(self.client.state)

    # -- OSD colors ---------------------------------------------------------

    def osd_colors(self) -> tuple[str, str, int] | None:
        """Configured (foreground, background, blend), or None to leave alone."""
        options = self.entry.options
        preset = options.get(CONF_OSD_COLORS, "device")
        if preset == "custom":
            return (
                str(options.get(CONF_OSD_FOREGROUND, "ffffff")),
                str(options.get(CONF_OSD_BACKGROUND, "000000")),
                int(options.get(CONF_OSD_BLEND, 15)),
            )
        return OSD_COLOR_PRESETS.get(preset)

    def _schedule_osd_colors(self) -> None:
        if self.osd_colors() is None:
            return
        if self._osd_color_task and not self._osd_color_task.done():
            self._osd_color_task.cancel()
        self._osd_color_task = self.entry.async_create_background_task(
            self.hass, self._apply_osd_colors(), "lumagen_osd_colors"
        )

    async def _apply_osd_colors(self) -> None:
        await asyncio.sleep(OSD_COLOR_DELAY)
        colors = self.osd_colors()
        if colors is None or not self.client.state.power:
            return
        try:
            await self.client.set_osd_colors(*colors)
        except (LumagenConnectionError, ValueError) as err:
            _LOGGER.warning("Could not apply OSD colors: %s", err)

    # -- Storage ------------------------------------------------------------

    async def async_load_stored_state(self) -> bool:
        """Load identity, config, and labels from disk into client state.

        Returns True if found.
        """
        data = await self._store.async_load()
        if not data:
            return False
        self.client.state.load_stored_dict(data)
        self.async_set_updated_data(self.client.state)
        _LOGGER.debug("Loaded identity and labels from storage")
        return True

    async def async_save_stored_state(self) -> None:
        """Persist identity, config, and labels to disk."""
        await self._store.async_save(self.client.state.to_stored_dict())

    async def reload_config(self) -> None:
        """Re-fetch identity and labels from device."""
        if not await self.client.query_config():
            _LOGGER.warning("Config reload incomplete — stored state not updated")
            return
        await self.async_save_stored_state()
        _LOGGER.info("Config reloaded from device")

    async def _async_update_data(self) -> LumagenState:
        """Fallback for first refresh — returns current state snapshot."""
        return self.client.state

    async def async_shutdown(self) -> None:
        """Stop the volume follower and disconnect the client."""
        _LOGGER.info("Shutting down Lumagen coordinator")
        if self.volume_osd:
            self.volume_osd.async_stop()
            self.volume_osd = None
        if self._osd_color_task and not self._osd_color_task.done():
            self._osd_color_task.cancel()
        await self.client.disconnect()
        await super().async_shutdown()
