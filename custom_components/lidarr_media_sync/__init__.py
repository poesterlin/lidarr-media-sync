"""Set up the Lidarr Media Sync integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import LidarrClient
from .const import (
    ATTR_ALBUM,
    ATTR_ARTIST,
    CONF_API_KEY,
    CONF_ENTRY_ID,
    CONF_URL,
    DOMAIN,
    NAME,
    SERVICE_ADD_ARTIST,
    SERVICE_RESET_HISTORY,
    SERVICE_SYNC_NOW,
)
from .manager import LidarrMediaSyncManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
]

ADD_ARTIST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ARTIST): cv.string,
        vol.Optional(ATTR_ALBUM): cv.string,
        vol.Optional(CONF_ENTRY_ID): cv.string,
    }
)

ENTRY_SCHEMA = vol.Schema({vol.Optional(CONF_ENTRY_ID): cv.string})


def _get_managers(
    hass: HomeAssistant, entry_id: str | None = None
) -> list[LidarrMediaSyncManager]:
    managers: list[LidarrMediaSyncManager] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry_id is not None and entry.entry_id != entry_id:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            continue
        manager = getattr(entry, "runtime_data", None)
        if manager is not None:
            managers.append(manager)
    if not managers:
        raise HomeAssistantError(
            "No loaded Lidarr Media Sync config entry was found"
            + (f" for entry_id {entry_id}" if entry_id else "")
        )
    return managers


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services once."""

    if hass.services.has_service(DOMAIN, SERVICE_ADD_ARTIST):
        return True

    async def _async_add_artist(call: ServiceCall) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for manager in _get_managers(hass, call.data.get(CONF_ENTRY_ID)):
            results.append(
                {
                    "entry_id": manager.entry.entry_id,
                    **await manager.async_add_artist_name(
                        call.data[ATTR_ARTIST],
                        call.data.get(ATTR_ALBUM),
                        source="service",
                        force=True,
                        respect_ignore=False,
                    ),
                }
            )
        return LidarrMediaSyncManager.result_summary(results)

    async def _async_sync_now(call: ServiceCall) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for manager in _get_managers(hass, call.data.get(CONF_ENTRY_ID)):
            results.append(
                {
                    "entry_id": manager.entry.entry_id,
                    **await manager.async_check_now(),
                }
            )
        return LidarrMediaSyncManager.result_summary(results)

    async def _async_reset_history(call: ServiceCall) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for manager in _get_managers(hass, call.data.get(CONF_ENTRY_ID)):
            await manager.async_reset_history()
            results.append({"entry_id": manager.entry.entry_id, "status": "reset"})
        return LidarrMediaSyncManager.result_summary(results)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_ARTIST,
        _async_add_artist,
        schema=ADD_ARTIST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_NOW,
        _async_sync_now,
        schema=ENTRY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_HISTORY,
        _async_reset_history,
        schema=ENTRY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Lidarr instance and watched sensor."""
    client = LidarrClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_API_KEY],
    )
    manager = LidarrMediaSyncManager(hass, entry, client)
    await manager.async_load()

    await manager.coordinator.async_config_entry_first_refresh()
    await manager.async_start()

    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("%s set up for %s", NAME, entry.data[CONF_URL])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    manager: LidarrMediaSyncManager | None = getattr(entry, "runtime_data", None)
    if manager is not None:
        await manager.async_stop()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
