"""Connectivity sensor for Lidarr."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Add the connectivity sensor."""
    manager: LidarrMediaSyncManager = entry.runtime_data
    async_add_entities([LidarrConnectionSensor(manager)])


class LidarrConnectionSensor(LidarrMediaSyncEntity, BinarySensorEntity):
    """Reports whether Lidarr answered the last health check."""

    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, manager: LidarrMediaSyncManager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_connected"

    @property
    def is_on(self) -> bool:
        return self.manager.coordinator.last_update_success
