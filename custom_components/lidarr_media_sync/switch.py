"""Switch for turning automatic artist syncing on or off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Add the automatic sync switch."""
    manager: LidarrMediaSyncManager = entry.runtime_data
    async_add_entities([LidarrAutoSyncSwitch(manager)])


class LidarrAutoSyncSwitch(LidarrMediaSyncEntity, SwitchEntity):
    """Pause or resume automatic artist additions."""

    _attr_translation_key = "enabled"
    _attr_icon = "mdi:music-note-plus"

    def __init__(self, manager: LidarrMediaSyncManager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_enabled"

    @property
    def is_on(self) -> bool:
        return self.manager.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_enabled(False)
