"""Follow a volume / mute entity and show it on the Lumagen OSD."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event

from .client import LumagenConnectionError
from .osd_pattern import OsdFrame, VolumePattern, render_volume

if TYPE_CHECKING:
    from .coordinator import LumagenCoordinator

_LOGGER = logging.getLogger(__name__)

_UNAVAILABLE = (STATE_UNAVAILABLE, STATE_UNKNOWN)

# Minimum gap between OSD writes; rapid volume steps collapse to the latest.
SEND_INTERVAL = 0.15


def read_volume(state: State | None) -> tuple[float | None, float, float]:
    """Return (value, minimum, maximum) for a volume entity state."""
    if state is None or state.state in _UNAVAILABLE:
        return None, 0.0, 100.0
    if state.domain == "media_player":
        level = state.attributes.get("volume_level")
        return (float(level) if level is not None else None), 0.0, 1.0
    try:
        value = float(state.state)
    except ValueError:
        return None, 0.0, 100.0
    minimum = float(state.attributes.get("min", 0.0))
    maximum = float(state.attributes.get("max", 100.0))
    return value, minimum, maximum


def read_muted(state: State | None) -> bool | None:
    """Return mute status for a mute entity (or a media_player)."""
    if state is None or state.state in _UNAVAILABLE:
        return None
    if state.domain == "media_player":
        muted = state.attributes.get("is_volume_muted")
        return None if muted is None else bool(muted)
    return state.state == STATE_ON


class VolumeOsdFollower:
    """Shows volume / mute changes from other entities on the Lumagen OSD.

    - Changes from or to unavailable/unknown never display (no pop-up when
      the AVR/processor powers on or HA restarts).
    - A persistent mute message is always cleared on unmute.
    - Rapid changes are coalesced; repeats of the same value are skipped.
    - Nothing is sent unless the Lumagen is connected and powered on.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: LumagenCoordinator,
        *,
        volume_entity: str,
        mute_entity: str | None,
        pattern: VolumePattern,
        full_scale: float | None = None,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.volume_entity = volume_entity
        self.mute_entity = mute_entity
        self.pattern = pattern
        self.full_scale = full_scale
        self._unsub: CALLBACK_TYPE | None = None
        self._last: tuple[float | None, bool] | None = None
        self._showing_mute = False
        self._pending: OsdFrame | None = None  # None = clear
        self._has_pending = False
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle ----------------------------------------------------------

    @callback
    def async_start(self) -> None:
        entities = [self.volume_entity]
        if self.mute_entity and self.mute_entity != self.volume_entity:
            entities.append(self.mute_entity)
        self._last = self._current()
        self._unsub = async_track_state_change_event(
            self.hass, entities, self._handle_event
        )

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._task and not self._task.done():
            self._task.cancel()

    # -- state --------------------------------------------------------------

    def _range(self) -> tuple[float | None, float, float]:
        value, minimum, maximum = read_volume(self.hass.states.get(self.volume_entity))
        if self.full_scale is not None and self.full_scale > minimum:
            maximum = self.full_scale
        return value, minimum, maximum

    def _is_muted(self) -> bool:
        entity = self.mute_entity
        if entity is None:
            if not self.volume_entity.startswith("media_player."):
                return False
            entity = self.volume_entity
        return bool(read_muted(self.hass.states.get(entity)))

    def _current(self) -> tuple[float | None, bool]:
        return self._range()[0], self._is_muted()

    @callback
    def _handle_event(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        if new is None:
            return
        if old is None or old.state in _UNAVAILABLE:
            # Entity just came up: record a baseline, display nothing.
            self._last = self._current()
            return
        if new.state in _UNAVAILABLE:
            if self._showing_mute:
                self._queue(None)  # never leave a persistent MUTE behind
            return

        value, minimum, maximum = self._range()
        muted = self._is_muted()
        key = (value, muted)
        previous = self._last
        self._last = key
        if key == previous:
            return  # attribute churn or a repeated value
        if previous is not None and previous[0] is None and not muted:
            return  # volume just became known (e.g. media player turned on)

        if muted:
            frame = render_volume(self.pattern, None, muted=True)
            if frame is not None:
                self._showing_mute = frame.duration == 0
                self._queue(frame)
            return

        frame = render_volume(self.pattern, value, minimum=minimum, maximum=maximum)
        if frame is None:
            if self._showing_mute:
                self._queue(None)
        else:
            self._queue(frame)
        self._showing_mute = False

    # -- sending ------------------------------------------------------------

    def _queue(self, frame: OsdFrame | None) -> None:
        """Queue *frame* (None = clear); only the latest queued frame is sent."""
        self._pending = frame
        self._has_pending = True
        if self._task is None or self._task.done():
            self._task = self.coordinator.entry.async_create_background_task(
                self.hass, self._flush(), "lumagen_volume_osd"
            )

    async def _flush(self) -> None:
        while self._has_pending:
            frame = self._pending
            self._has_pending = False
            await self._send(frame)
            await asyncio.sleep(SEND_INTERVAL)

    async def _send(self, frame: OsdFrame | None) -> None:
        client = self.coordinator.client
        if not client.state.connected or not client.state.power:
            return
        try:
            if frame is None:
                await client.clear_osd_message()
            else:
                await client.show_osd_message(
                    frame.line_one,
                    frame.line_two,
                    duration=frame.duration,
                    block_char=frame.block_char,
                )
        except LumagenConnectionError as err:
            _LOGGER.debug("Volume OSD not sent: %s", err)
