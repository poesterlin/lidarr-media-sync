"""Shared entity base class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import LidarrCoordinator
from .manager import LidarrMediaSyncManager


class LidarrMediaSyncEntity(CoordinatorEntity[LidarrCoordinator]):
    """Base entity bound to one config entry."""

    _attr_has_entity_name = True

    def __init__(self, manager: LidarrMediaSyncManager) -> None:
        super().__init__(manager.coordinator)
        self.manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=manager.entry.title or NAME,
            manufacturer="Lidarr",
            model="Media Sync",
            configuration_url=manager.client.url,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime updates as well as coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.manager.signal_update, self.async_write_ha_state
            )
        )

    @property
    def available(self) -> bool:
        """Stay available when Lidarr is down so the connection sensor works."""
        return True
