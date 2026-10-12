# pyright: reportPrivateUsage=false
"""Tests for the volume OSD follower (state-change handling)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from homeassistant.core import Event, State

from custom_components.lumagen.client import LumagenClient
from custom_components.lumagen.osd_pattern import VolumePattern
from custom_components.lumagen.volume_osd import VolumeOsdFollower

VOL = "number.isp_volume_level"
MUTE = "switch.isp_mute"


class _States:
    def __init__(self) -> None:
        self.data: dict[str, State] = {}

    def get(self, entity_id: str) -> State | None:
        return self.data.get(entity_id)


class _Hass:
    def __init__(self) -> None:
        self.states = _States()


class _Entry:
    def async_create_background_task(
        self, hass: object, coro: Coroutine[Any, Any, None], name: str
    ) -> asyncio.Task[None]:
        return asyncio.get_running_loop().create_task(coro)


class _Coordinator:
    def __init__(self) -> None:
        self.entry = _Entry()
        self.client = LumagenClient("127.0.0.1", 1)
        self.client.state.connected = True
        self.client.state.power = True
        self.sent: list[str] = []

        async def _send(cmd: str) -> None:
            self.sent.append(cmd)

        self.client._send_command = _send  # type: ignore[method-assign]


def _state(entity_id: str, value: str, **attrs: Any) -> State:
    return State(entity_id, value, attrs or {"min": 0, "max": 100})


class Harness:
    def __init__(self, pattern: VolumePattern | None = None) -> None:
        self.hass = _Hass()
        self.coord = _Coordinator()
        self.hass.states.data[VOL] = _state(VOL, "40")
        self.hass.states.data[MUTE] = State(MUTE, "off")
        self.follower = VolumeOsdFollower(
            self.hass,  # type: ignore[arg-type]
            self.coord,  # type: ignore[arg-type]
            volume_entity=VOL,
            mute_entity=MUTE,
            pattern=pattern
            or VolumePattern(bar_type="none", label="- Volume", value_suffix=" -"),
        )
        self.follower._last = self.follower._current()

    def change(self, entity_id: str, value: str) -> None:
        old = self.hass.states.get(entity_id)
        new = _state(entity_id, value) if entity_id == VOL else State(entity_id, value)
        self.hass.states.data[entity_id] = new
        event = Event(
            "state_changed",
            {"entity_id": entity_id, "old_state": old, "new_state": new},
        )
        self.follower._handle_event(event)  # type: ignore[arg-type]

    async def settle(self) -> list[str]:
        await asyncio.sleep(0.4)
        return self.coord.sent


class TestFollower:
    @pytest.mark.anyio
    async def test_volume_change_shows_text(self):
        h = Harness()
        h.change(VOL, "42")
        sent = await h.settle()
        assert sent == ["ZT1- Volume 42 -\r"]

    @pytest.mark.anyio
    async def test_mute_persists_and_unmute_replaces(self):
        h = Harness()
        h.change(MUTE, "on")
        h.change(MUTE, "off")
        sent = await h.settle()
        # latest wins after coalescing: unmute shows the volume
        assert sent[-1] == "ZT1- Volume 40 -\r"

    @pytest.mark.anyio
    async def test_mute_shows_persistent(self):
        h = Harness()
        h.change(MUTE, "on")
        sent = await h.settle()
        assert sent == ["ZT9- MUTE -\r"]

    @pytest.mark.anyio
    async def test_power_on_transitions_are_silent(self):
        h = Harness()
        h.change(VOL, "unavailable")
        h.change(MUTE, "unavailable")
        h.change(VOL, "40")
        h.change(MUTE, "off")
        assert await h.settle() == []

    @pytest.mark.anyio
    async def test_mute_cleared_when_processor_goes_away(self):
        h = Harness()
        h.change(MUTE, "on")
        await h.settle()
        h.change(VOL, "unavailable")
        sent = await h.settle()
        assert sent[-1] == "ZC"

    @pytest.mark.anyio
    async def test_repeated_value_is_skipped(self):
        h = Harness()
        h.change(VOL, "42")
        await h.settle()
        h.change(VOL, "42")
        assert len(await h.settle()) == 1

    @pytest.mark.anyio
    async def test_rapid_steps_coalesce(self):
        h = Harness()
        for v in range(41, 61):
            h.change(VOL, str(v))
        sent = await h.settle()
        assert len(sent) <= 3
        assert sent[-1] == "ZT1- Volume 60 -\r"

    @pytest.mark.anyio
    async def test_nothing_sent_in_standby(self):
        h = Harness()
        h.coord.client.state.power = False
        h.change(VOL, "42")
        assert await h.settle() == []

    @pytest.mark.anyio
    async def test_bar_uses_block_char(self):
        h = Harness(VolumePattern())
        h.change(VOL, "50")
        sent = await h.settle()
        assert sent[0].startswith("ZBXZT1Volume 50")
