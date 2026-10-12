# pyright: reportPrivateUsage=false
"""Tests for new commands, response handlers, and setup cleanup."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.lumagen import async_setup_entry
from custom_components.lumagen.client import (
    LumagenClient,
    LumagenState,
    _on_game_mode,
    _on_hdr_status,
)


def _client() -> tuple[LumagenClient, list[str]]:
    client = LumagenClient("localhost", 0)
    client.state.connected = True
    client.state.power = True
    sent: list[str] = []

    async def _send(cmd: str) -> None:
        sent.append(cmd)

    client._send_command = _send  # type: ignore[method-assign]
    return client, sent


class TestHandlers:
    def test_hdr_status(self):
        s = LumagenState()
        _on_hdr_status(s, ["1", ".0050", "1000", "850"])
        assert (s.hdr_min_luminance, s.hdr_max_luminance, s.hdr_max_cll) == (
            0.005,
            1000,
            850,
        )
        _on_hdr_status(s, ["0", ".0000", "0", "0"])
        assert s.hdr_max_luminance is None
        assert s.hdr_max_cll is None

    def test_game_mode(self):
        s = LumagenState()
        _on_game_mode(s, ["1"])
        assert s.game_mode is True
        _on_game_mode(s, ["0"])
        assert s.game_mode is False

    @pytest.mark.anyio
    async def test_i52_via_readline(self):
        client, _ = _client()
        client._last_power = True  # no power-on refresh
        client._on_readline("ZQI52!I52,1,.0001,4000,1200")
        assert client.state.hdr_max_luminance == 4000


class TestCommands:
    @pytest.mark.anyio
    async def test_hotplug(self):
        client, sent = _client()
        await client.hotplug(None)
        await client.hotplug(1)
        await client.hotplug(8)
        assert sent == ["ZY520A\r", "ZY5200\r", "ZY5207\r"]
        with pytest.raises(ValueError):
            await client.hotplug(9)

    @pytest.mark.anyio
    async def test_reset_auto_aspect(self):
        client, sent = _client()
        await client.reset_auto_aspect()
        assert sent == ["ZY550\rZQI54ZQI25"]

    @pytest.mark.anyio
    async def test_cms_follows_dynamic_range(self):
        client, sent = _client()
        client.state.source_dynamic_range = "SDR"
        await client.set_cms(3)
        client.state.source_dynamic_range = "HDR"
        await client.set_cms(5)
        await client.set_style(2)
        assert sent == [
            "ZY530K3KK\rZQI25",
            "ZY530KK5K\rZQI25",
            "ZY530KKK2\rZQI25",
        ]
        with pytest.raises(ValueError):
            await client.set_style(8)

    @pytest.mark.anyio
    async def test_osd_colors(self):
        client, sent = _client()
        await client.set_osd_colors("FFFF00", "000000", 15)
        assert sent == ["ZY4180000000\rZY4181ffff00\rZY418200000f\r"]
        with pytest.raises(ValueError):
            await client.set_osd_colors("zzzzzz", "000000", 15)
        with pytest.raises(ValueError):
            await client.set_osd_colors("ffffff", "000000", 0)

    @pytest.mark.anyio
    async def test_block_char_reset_after_use(self):
        """Once ZB has been used, later plain messages re-point it."""
        client, sent = _client()
        await client.show_osd_message("Hello")
        await client.show_osd_volume_bar(0.5)
        await client.show_osd_message("X marks")
        assert sent[0] == "ZT3Hello\r"
        assert sent[1].startswith("ZBX")
        assert sent[2].startswith("ZB#ZT3X marks")

    @pytest.mark.anyio
    async def test_volume_bar_label_avoids_block_char(self):
        client, sent = _client()
        await client.show_osd_volume_bar(0.5, label="MAX")
        assert sent[0].startswith("ZB#ZT1MAX")


class TestSignalFollowup:
    @pytest.mark.anyio
    async def test_input_change_queries_game_mode_and_hdr(self):
        client, sent = _client()
        client.state.source_dynamic_range = "HDR"
        client.state.logical_input = 2
        client._check_signal_followup()
        assert client._followup_task is not None
        await client._followup_task
        assert sent == ["ZQI53ZQI52"]

    @pytest.mark.anyio
    async def test_sdr_clears_hdr_metadata(self):
        client, _ = _client()
        client.state.hdr_max_luminance = 1000
        client.state.source_dynamic_range = "SDR"
        client._check_signal_followup()
        assert client.state.hdr_max_luminance is None
        if client._followup_task:
            client._followup_task.cancel()


class TestSetupCleanup:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("connect_ok", "config_ok"),
        [(False, True), (True, False)],
    )
    async def test_failed_setup_disconnects(self, connect_ok: bool, config_ok: bool):
        coordinator: Any = MagicMock()
        coordinator.async_connect = AsyncMock(return_value=connect_ok)
        coordinator.async_load_stored_state = AsyncMock(return_value=False)
        coordinator.client.query_config = AsyncMock(return_value=config_ok)
        coordinator.client.disconnect = AsyncMock()
        entry: Any = MagicMock()
        entry.data = {"host": "1.2.3.4", "port": 4999}
        with (
            patch(
                "custom_components.lumagen.LumagenCoordinator",
                return_value=coordinator,
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(MagicMock(), entry)
        coordinator.client.disconnect.assert_awaited_once()

    @pytest.mark.anyio
    async def test_unexpected_error_disconnects(self):
        coordinator: Any = MagicMock()
        coordinator.async_connect = AsyncMock(side_effect=RuntimeError("boom"))
        coordinator.client.disconnect = AsyncMock()
        entry: Any = MagicMock()
        entry.data = {"host": "1.2.3.4", "port": 4999}
        with (
            patch(
                "custom_components.lumagen.LumagenCoordinator",
                return_value=coordinator,
            ),
            pytest.raises(ConfigEntryNotReady),
        ):
            await async_setup_entry(MagicMock(), entry)
        coordinator.client.disconnect.assert_awaited_once()
