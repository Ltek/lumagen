"""Diagnostics support for Lumagen."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import LumagenConfigEntry

TO_REDACT = {CONF_HOST, "serial_number", "host"}


def _iso(value: float | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value, UTC).isoformat()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LumagenConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    client = coordinator.client
    state = {k: v for k, v in asdict(client.state).items() if not k.startswith("_")}
    health = asdict(client.health)
    for key in ("connected_since", "last_data_received", "last_disconnect"):
        health[key] = _iso(health[key])
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "state": async_redact_data(state, TO_REDACT),
        "labels": client.state.labels,
        "health": health,
        "volume_osd": (
            {
                "volume_entity": coordinator.volume_osd.volume_entity,
                "mute_entity": coordinator.volume_osd.mute_entity,
            }
            if coordinator.volume_osd
            else None
        ),
        "traffic": [
            {"time": _iso(ts), "dir": direction, "data": data}
            for ts, direction, data in client.traffic
        ],
    }
