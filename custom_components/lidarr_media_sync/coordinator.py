"""Coordinator for Lidarr connectivity and health."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import LidarrAuthError, LidarrClient, LidarrError
from .const import DOMAIN, NAME, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class LidarrCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Lidarr for connectivity and version information.

    Artist lookups and additions are event-driven; polling only keeps the
    connection sensor honest and triggers reauthentication when the API key
    stops working.
    """

    def __init__(self, hass: HomeAssistant, client: LidarrClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.url}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_system_status()
        except LidarrAuthError as err:
            raise ConfigEntryAuthFailed(
                f"{NAME} could not authenticate with Lidarr"
            ) from err
        except LidarrError as err:
            raise UpdateFailed(str(err)) from err
