"""Sensor entity for the last artist added to Lidarr."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LidarrMediaSyncEntity
from .manager import LidarrMediaSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the sensor for this config entry."""
    manager: LidarrMediaSyncManager = entry.runtime_data
    async_add_entities([LidarrLastAddedSensor(manager)])


class LidarrLastAddedSensor(LidarrMediaSyncEntity, SensorEntity):
    """Shows the artist most recently added to Lidarr."""

    _attr_translation_key = "last_added"
    _attr_icon = "mdi:music-note-plus"

    def __init__(self, manager: LidarrMediaSyncManager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_last_added"

    @property
    def native_value(self) -> str | None:
        last_added = self.manager.last_added
        if not last_added:
            return None
        return last_added.get("artist")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the last action and the current runtime configuration."""
        return {
            "last_added": self.manager.last_added,
            "last_result": self.manager.last_result,
            "pending_artist": self.manager.pending_artist,
            "seen_artists": self.manager.seen_count,
            "dry_run": self.manager.dry_run,
            "source_entity": self.manager.entity_id,
            "packages": self.manager.packages,
            "lidarr_url": self.manager.client.url,
        }
