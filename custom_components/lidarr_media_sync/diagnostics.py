"""Diagnostics support for Lidarr Media Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_URL
from .manager import LidarrMediaSyncManager


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without exposing the API key."""
    manager: LidarrMediaSyncManager = entry.runtime_data
    return {
        "config": {
            "url": entry.data.get(CONF_URL),
            "api_key": "**REDACTED**" if entry.data.get(CONF_API_KEY) else None,
            "options": dict(entry.options),
        },
        "runtime": manager.diagnostics(),
        "coordinator": {
            "last_update_success": manager.coordinator.last_update_success,
            "last_exception": (
                str(manager.coordinator.last_exception)
                if manager.coordinator.last_exception
                else None
            ),
            "data": manager.coordinator.data,
        },
    }
