"""Config and options flow for Lidarr Media Sync."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import LidarrAuthError, LidarrClient, LidarrConnectionError, LidarrError
from .const import (
    ATTR_ARTIST_PREFIX,
    ATTR_MEDIA_ALBUM_ARTIST,
    ATTR_MEDIA_ARTIST,
    CONF_API_KEY,
    CONF_DRY_RUN,
    CONF_ENTITY_ID,
    CONF_IGNORED_ARTISTS,
    CONF_MATCH_STRATEGY,
    CONF_METADATA_PROFILE_ID,
    CONF_MIN_PLAY_SECONDS,
    CONF_MONITOR,
    CONF_NOTIFY_ON_ADD,
    CONF_ONLY_WHEN_PLAYING,
    CONF_PACKAGES,
    CONF_QUALITY_PROFILE_ID,
    CONF_ROOT_FOLDER,
    CONF_SEARCH_MISSING,
    CONF_URL,
    DEFAULT_DRY_RUN,
    DEFAULT_MATCH_STRATEGY,
    DEFAULT_MIN_PLAY_SECONDS,
    DEFAULT_MONITOR,
    DEFAULT_NOTIFY_ON_ADD,
    DEFAULT_ONLY_WHEN_PLAYING,
    DEFAULT_PACKAGES,
    DEFAULT_SEARCH_MISSING,
    DEFAULT_URL,
    MATCH_STRATEGIES,
    MATCH_STRATEGY_LABELS,
    MEDIA_PLAYER_DOMAIN,
    MONITOR_LABELS,
    MONITOR_OPTIONS,
    NAME,
    SENSOR_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _split_list(value: Any, default: list[str] | None = None) -> list[str]:
    if isinstance(value, str):
        parts = value.replace("\n", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return list(default or [])


def _default_lidarr_url(hass: HomeAssistant) -> str:
    """Guess Lidarr on Home Assistant's own host instead of hardcoding an IP.

    Many installations run Lidarr next to Home Assistant. Deriving the host
    from HA's internal URL avoids shipping a personal LAN address in the code
    while still prefilling a useful value. The user can always edit the field.
    """
    try:
        from homeassistant.helpers.network import get_url

        internal_url = get_url(
            hass,
            allow_external=False,
            allow_cloud=False,
            prefer_external=False,
        )
    except Exception:  # noqa: BLE001 - any failure should fall back
        return DEFAULT_URL

    host = urlparse(internal_url).hostname
    if not host:
        return DEFAULT_URL
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:8686"


def _profile_options(profiles: list[dict[str, Any]]) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(profile["id"]),
            label=str(profile.get("name") or f"Profile {profile['id']}"),
        )
        for profile in profiles
        if profile.get("id") is not None
    ]


def _profile_select(
    profiles: list[dict[str, Any]], current: int
) -> selector.SelectSelector:
    options = _profile_options(profiles)
    values = {option["value"] for option in options}
    if str(current) not in values:
        options.append(
            selector.SelectOptionDict(
                value=str(current), label=f"Profile {current} (not found)"
            )
        )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _root_select(
    root_folders: list[dict[str, Any]], current: str
) -> selector.SelectSelector:
    paths = [str(folder["path"]) for folder in root_folders if folder.get("path")]
    if current not in paths:
        paths.append(current)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=paths, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _detect_entity_id(hass: HomeAssistant) -> str | None:
    """Find a companion media session sensor or a playing media_player."""
    sensors = []
    players = []
    named_sensors = []
    for state in hass.states.async_all():
        domain = state.entity_id.split(".", 1)[0]
        attributes = state.attributes or {}
        if domain == SENSOR_DOMAIN:
            if any(str(key).startswith(ATTR_ARTIST_PREFIX) for key in attributes):
                sensors.append(state.entity_id)
            elif "media session" in (state.name or "").casefold() or (
                "media_session" in state.entity_id
            ):
                named_sensors.append(state.entity_id)
        elif domain == MEDIA_PLAYER_DOMAIN and (
            attributes.get(ATTR_MEDIA_ARTIST) or attributes.get(ATTR_MEDIA_ALBUM_ARTIST)
        ):
            players.append(state.entity_id)
    for candidates in (sensors, players, named_sensors):
        if candidates:
            return min(candidates)
    return None


def _build_schema(
    *,
    hass: HomeAssistant,
    root_folders: list[dict[str, Any]],
    quality_profiles: list[dict[str, Any]],
    metadata_profiles: list[dict[str, Any]],
    defaults: Mapping[str, Any],
) -> vol.Schema:
    entity_default = defaults.get(CONF_ENTITY_ID) or _detect_entity_id(hass)
    entity_field = (
        vol.Required(CONF_ENTITY_ID, default=entity_default)
        if entity_default
        else vol.Required(CONF_ENTITY_ID)
    )
    current_root = str(defaults.get(CONF_ROOT_FOLDER) or "/music")
    current_quality = int(defaults.get(CONF_QUALITY_PROFILE_ID) or 1)
    current_metadata = int(defaults.get(CONF_METADATA_PROFILE_ID) or 1)
    return vol.Schema(
        {
            entity_field: selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=[SENSOR_DOMAIN, MEDIA_PLAYER_DOMAIN]
                )
            ),
            vol.Required(
                CONF_PACKAGES,
                default=", ".join(defaults.get(CONF_PACKAGES) or DEFAULT_PACKAGES),
            ): selector.TextSelector(),
            vol.Required(
                CONF_ONLY_WHEN_PLAYING,
                default=bool(
                    defaults.get(CONF_ONLY_WHEN_PLAYING, DEFAULT_ONLY_WHEN_PLAYING)
                ),
            ): bool,
            vol.Required(
                CONF_MIN_PLAY_SECONDS,
                default=int(
                    defaults.get(CONF_MIN_PLAY_SECONDS, DEFAULT_MIN_PLAY_SECONDS)
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=600,
                    step=5,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="seconds",
                )
            ),
            vol.Required(
                CONF_ROOT_FOLDER,
                default=current_root,
            ): _root_select(root_folders, current_root),
            vol.Required(
                CONF_QUALITY_PROFILE_ID,
                default=str(current_quality),
            ): _profile_select(quality_profiles, current_quality),
            vol.Required(
                CONF_METADATA_PROFILE_ID,
                default=str(current_metadata),
            ): _profile_select(metadata_profiles, current_metadata),
            vol.Required(
                CONF_MONITOR, default=str(defaults.get(CONF_MONITOR, DEFAULT_MONITOR))
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=option, label=MONITOR_LABELS.get(option, option)
                        )
                        for option in MONITOR_OPTIONS
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SEARCH_MISSING,
                default=bool(defaults.get(CONF_SEARCH_MISSING, DEFAULT_SEARCH_MISSING)),
            ): bool,
            vol.Required(
                CONF_MATCH_STRATEGY,
                default=str(defaults.get(CONF_MATCH_STRATEGY, DEFAULT_MATCH_STRATEGY)),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=option,
                            label=MATCH_STRATEGY_LABELS.get(option, option),
                        )
                        for option in MATCH_STRATEGIES
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_DRY_RUN, default=bool(defaults.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
            ): bool,
            vol.Required(
                CONF_NOTIFY_ON_ADD,
                default=bool(defaults.get(CONF_NOTIFY_ON_ADD, DEFAULT_NOTIFY_ON_ADD)),
            ): bool,
            vol.Optional(
                CONF_IGNORED_ARTISTS,
                default="\n".join(defaults.get(CONF_IGNORED_ARTISTS) or []),
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        }
    )


def _normalize_settings(user_input: Mapping[str, Any]) -> dict[str, Any]:
    packages = _split_list(user_input.get(CONF_PACKAGES), DEFAULT_PACKAGES)
    if not packages:
        packages = list(DEFAULT_PACKAGES)
    return {
        CONF_ENTITY_ID: str(user_input[CONF_ENTITY_ID]),
        CONF_PACKAGES: packages,
        CONF_ONLY_WHEN_PLAYING: bool(user_input.get(CONF_ONLY_WHEN_PLAYING, True)),
        CONF_MIN_PLAY_SECONDS: int(user_input.get(CONF_MIN_PLAY_SECONDS, 0) or 0),
        CONF_ROOT_FOLDER: str(user_input[CONF_ROOT_FOLDER]),
        CONF_QUALITY_PROFILE_ID: int(user_input[CONF_QUALITY_PROFILE_ID]),
        CONF_METADATA_PROFILE_ID: int(user_input[CONF_METADATA_PROFILE_ID]),
        CONF_MONITOR: str(user_input.get(CONF_MONITOR, DEFAULT_MONITOR)),
        CONF_SEARCH_MISSING: bool(user_input.get(CONF_SEARCH_MISSING, False)),
        CONF_MATCH_STRATEGY: str(
            user_input.get(CONF_MATCH_STRATEGY, DEFAULT_MATCH_STRATEGY)
        ),
        CONF_DRY_RUN: bool(user_input.get(CONF_DRY_RUN, False)),
        CONF_NOTIFY_ON_ADD: bool(user_input.get(CONF_NOTIFY_ON_ADD, False)),
        CONF_IGNORED_ARTISTS: _split_list(user_input.get(CONF_IGNORED_ARTISTS)),
    }


class LidarrMediaSyncConfigFlow(ConfigFlow, domain="lidarr_media_sync"):
    """Set up Lidarr Media Sync."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}
        self._root_folders: list[dict[str, Any]] = []
        self._quality_profiles: list[dict[str, Any]] = []
        self._metadata_profiles: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            api_key = str(user_input[CONF_API_KEY]).strip()
            client = LidarrClient(async_get_clientsession(self.hass), url, api_key)
            try:
                await client.async_get_system_status()
                self._root_folders = await client.async_get_root_folders()
                self._quality_profiles = await client.async_get_quality_profiles()
                self._metadata_profiles = await client.async_get_metadata_profiles()
            except LidarrAuthError:
                errors["base"] = "invalid_auth"
            except (LidarrConnectionError, LidarrError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while validating Lidarr")
                errors["base"] = "unknown"
            else:
                if not self._root_folders:
                    errors["base"] = "no_root_folder"
                else:
                    self._credentials = {CONF_URL: url, CONF_API_KEY: api_key}
                    return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_URL, default=_default_lidarr_url(self.hass)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._credentials:
            return await self.async_step_user()

        if user_input is not None:
            entity_id = str(user_input[CONF_ENTITY_ID])
            await self.async_set_unique_id(
                f"{self._credentials[CONF_URL]}|{entity_id}", raise_on_progress=False
            )
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=NAME,
                data=dict(self._credentials),
                options=_normalize_settings(user_input),
            )

        defaults = {
            CONF_PACKAGES: list(DEFAULT_PACKAGES),
            CONF_ONLY_WHEN_PLAYING: DEFAULT_ONLY_WHEN_PLAYING,
            CONF_MIN_PLAY_SECONDS: DEFAULT_MIN_PLAY_SECONDS,
            CONF_ROOT_FOLDER: (
                str(self._root_folders[0]["path"]) if self._root_folders else "/music"
            ),
            CONF_QUALITY_PROFILE_ID: (
                int(self._quality_profiles[0]["id"]) if self._quality_profiles else 1
            ),
            CONF_METADATA_PROFILE_ID: (
                int(self._metadata_profiles[0]["id"]) if self._metadata_profiles else 1
            ),
            CONF_MONITOR: DEFAULT_MONITOR,
            CONF_SEARCH_MISSING: DEFAULT_SEARCH_MISSING,
            CONF_MATCH_STRATEGY: DEFAULT_MATCH_STRATEGY,
            CONF_DRY_RUN: DEFAULT_DRY_RUN,
            CONF_NOTIFY_ON_ADD: DEFAULT_NOTIFY_ON_ADD,
            CONF_IGNORED_ARTISTS: [],
        }
        return self.async_show_form(
            step_id="settings",
            data_schema=_build_schema(
                hass=self.hass,
                root_folders=self._root_folders,
                quality_profiles=self._quality_profiles,
                metadata_profiles=self._metadata_profiles,
                defaults=defaults,
            ),
        )

    # ------------------------------------------------------------------
    # Reauthentication
    # ------------------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is not None:
            url = str(user_input[CONF_URL]).strip().rstrip("/")
            api_key = str(user_input[CONF_API_KEY]).strip()
            client = LidarrClient(async_get_clientsession(self.hass), url, api_key)
            try:
                await client.async_get_system_status()
            except LidarrAuthError:
                errors["base"] = "invalid_auth"
            except (LidarrConnectionError, LidarrError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while validating Lidarr")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry, data={CONF_URL: url, CONF_API_KEY: api_key}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_URL, default=entry.data.get(CONF_URL, DEFAULT_URL)
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LidarrMediaSyncOptionsFlow:
        return LidarrMediaSyncOptionsFlow(config_entry)


class LidarrMediaSyncOptionsFlow(OptionsFlow):
    """Edit the watched entity and Lidarr defaults."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data=_normalize_settings(user_input)
            )

        errors: dict[str, str] = {}
        client = LidarrClient(
            async_get_clientsession(self.hass),
            self._entry.data[CONF_URL],
            self._entry.data[CONF_API_KEY],
        )
        root_folders: list[dict[str, Any]] = []
        quality_profiles: list[dict[str, Any]] = []
        metadata_profiles: list[dict[str, Any]] = []
        try:
            root_folders = await client.async_get_root_folders()
            quality_profiles = await client.async_get_quality_profiles()
            metadata_profiles = await client.async_get_metadata_profiles()
        except LidarrAuthError:
            errors["base"] = "invalid_auth"
        except (LidarrConnectionError, LidarrError):
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while loading Lidarr options")
            errors["base"] = "unknown"

        defaults = dict(self._entry.options)
        if self._entry.options.get(CONF_ROOT_FOLDER) and not root_folders:
            root_folders = [{"path": self._entry.options[CONF_ROOT_FOLDER]}]

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                hass=self.hass,
                root_folders=root_folders,
                quality_profiles=quality_profiles,
                metadata_profiles=metadata_profiles,
                defaults=defaults,
            ),
            errors=errors,
        )
