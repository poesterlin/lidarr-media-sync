"""Runtime logic for Lidarr Media Sync."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import LidarrAuthError, LidarrClient, LidarrError
from .const import (
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
    DEFAULT_DRY_RUN,
    DEFAULT_MATCH_STRATEGY,
    DEFAULT_MIN_PLAY_SECONDS,
    DEFAULT_MONITOR,
    DEFAULT_NOTIFY_ON_ADD,
    DEFAULT_ONLY_WHEN_PLAYING,
    DEFAULT_PACKAGES,
    DEFAULT_SEARCH_MISSING,
    DOMAIN,
    EVENT_ARTIST_ADDED,
    MEDIA_PLAYER_DOMAIN,
    NAME,
    SEEN_LIMIT,
    SEEN_RETRY_SECONDS,
    STORAGE_VERSION,
)
from .coordinator import LidarrCoordinator
from .matching import ArtistCandidate, choose_candidate, normalize_name
from .media import NowPlaying, parse_media_player, parse_now_playing

_LOGGER = logging.getLogger(__name__)

_TERMINAL_NEGATIVE_STATUSES = frozenset({"not_found", "error"})


def _as_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, str):
        parts = value.replace("\n", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return list(default)


class LidarrMediaSyncManager:
    """Watches a media session sensor and adds matching artists to Lidarr."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LidarrClient,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.coordinator = LidarrCoordinator(hass, client)
        self.signal_update = f"{DOMAIN}_{entry.entry_id}_update"

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._seen: dict[str, dict[str, Any]] = {}
        self._enabled = True
        self._last_added: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._pending_artist: str | None = None
        self._observed_key: str | None = None
        self._confirm_task: asyncio.Task | None = None
        self._process_task: asyncio.Task | None = None
        self._unsub_state: CALLBACK_TYPE | None = None
        self._started = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Options / properties
    # ------------------------------------------------------------------
    @property
    def entity_id(self) -> str | None:
        entity_id = self.entry.options.get(CONF_ENTITY_ID)
        return str(entity_id) if entity_id else None

    @property
    def packages(self) -> list[str]:
        return _as_list(
            self.entry.options.get(CONF_PACKAGES, DEFAULT_PACKAGES), DEFAULT_PACKAGES
        )

    @property
    def ignored_artists(self) -> list[str]:
        return _as_list(self.entry.options.get(CONF_IGNORED_ARTISTS, []), [])

    @property
    def only_when_playing(self) -> bool:
        return bool(
            self.entry.options.get(CONF_ONLY_WHEN_PLAYING, DEFAULT_ONLY_WHEN_PLAYING)
        )

    @property
    def min_play_seconds(self) -> int:
        try:
            return max(
                0,
                int(
                    self.entry.options.get(
                        CONF_MIN_PLAY_SECONDS, DEFAULT_MIN_PLAY_SECONDS
                    )
                ),
            )
        except (TypeError, ValueError):
            return DEFAULT_MIN_PLAY_SECONDS

    @property
    def match_strategy(self) -> str:
        value = str(self.entry.options.get(CONF_MATCH_STRATEGY, DEFAULT_MATCH_STRATEGY))
        return value if value in ("exact", "first") else DEFAULT_MATCH_STRATEGY

    @property
    def dry_run(self) -> bool:
        return bool(self.entry.options.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))

    @property
    def notify_on_add(self) -> bool:
        return bool(self.entry.options.get(CONF_NOTIFY_ON_ADD, DEFAULT_NOTIFY_ON_ADD))

    @property
    def root_folder(self) -> str:
        return str(self.entry.options.get(CONF_ROOT_FOLDER, "/music"))

    @property
    def quality_profile_id(self) -> int:
        return int(self.entry.options.get(CONF_QUALITY_PROFILE_ID, 1) or 1)

    @property
    def metadata_profile_id(self) -> int:
        return int(self.entry.options.get(CONF_METADATA_PROFILE_ID, 1) or 1)

    @property
    def monitor(self) -> str:
        return str(self.entry.options.get(CONF_MONITOR, DEFAULT_MONITOR))

    @property
    def search_missing_albums(self) -> bool:
        return bool(self.entry.options.get(CONF_SEARCH_MISSING, DEFAULT_SEARCH_MISSING))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_added(self) -> dict[str, Any] | None:
        return self._last_added

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    @property
    def pending_artist(self) -> str | None:
        return self._pending_artist

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_load(self) -> None:
        """Restore persisted history and the pause switch."""
        data = await self._store.async_load() or {}
        self._enabled = bool(data.get("enabled", True))
        seen = data.get("seen")
        if isinstance(seen, Mapping):
            self._seen = {
                str(key): value
                for key, value in seen.items()
                if isinstance(value, Mapping)
            }
        last_added = data.get("last_added")
        if isinstance(last_added, Mapping):
            self._last_added = dict(last_added)
        last_result = data.get("last_result")
        if isinstance(last_result, Mapping):
            self._last_result = dict(last_result)
        self._trim_seen()

    async def async_start(self) -> None:
        """Start listening for sensor changes."""
        self._started = True
        entity_id = self.entity_id
        if not entity_id:
            _LOGGER.warning("%s is configured without a media source entity", NAME)
            return

        self._unsub_state = async_track_state_change_event(
            self.hass, [entity_id], self._async_state_changed
        )
        _LOGGER.debug("%s is watching %s", NAME, entity_id)

    async def async_stop(self) -> None:
        """Stop listening and persist state."""
        self._started = False
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        self._cancel_confirm()
        if self._process_task is not None and not self._process_task.done():
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOGGER.debug(
                    "Error while stopping in-flight artist sync", exc_info=True
                )
        self._process_task = None
        await self._store.async_save(self._data_to_save())

    async def async_set_enabled(self, enabled: bool) -> None:
        """Turn automatic syncing on or off from the switch entity."""
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._cancel_confirm()
            self._pending_artist = None
            self._observed_key = None
        else:
            self._async_evaluate()
        self._save()
        self._dispatch()

    # ------------------------------------------------------------------
    # Sensor handling
    # ------------------------------------------------------------------
    @callback
    def _async_state_changed(self, _event: Any) -> None:
        self._async_evaluate()

    @callback
    def _async_evaluate(self) -> None:
        """React to a new sensor state without stacking work."""
        if not self._started or not self._enabled:
            return

        now_playing = self._current_now_playing()
        key = normalize_name(now_playing.artist) if now_playing else None

        if key == self._observed_key:
            return
        self._observed_key = key
        self._cancel_confirm()

        if now_playing is None:
            if self._pending_artist is not None:
                self._pending_artist = None
                self._dispatch()
            return

        if self._is_seen(key):
            if self._pending_artist is not None:
                self._pending_artist = None
                self._dispatch()
            return

        if self._is_ignored(key):
            if self._pending_artist is not None:
                self._pending_artist = None
                self._dispatch()
            return

        delay = self.min_play_seconds
        if delay <= 0:
            self._pending_artist = None
            self._start_process(now_playing)
            return

        self._pending_artist = now_playing.artist
        self._dispatch()
        self._confirm_task = self.hass.async_create_task(
            self._async_confirm(now_playing, delay)
        )

    async def _async_confirm(self, now_playing: NowPlaying, delay: int) -> None:
        """Wait, then make sure the same artist is still playing."""
        await asyncio.sleep(delay)

        self._pending_artist = None
        current = self._current_now_playing()
        if current is None or normalize_name(current.artist) != normalize_name(
            now_playing.artist
        ):
            _LOGGER.debug(
                "Artist changed from %s before the confirmation delay ended",
                now_playing.artist,
            )
            self._dispatch()
            return

        self._start_process(current)
        self._dispatch()

    @callback
    def _start_process(self, now_playing: NowPlaying) -> None:
        if self._process_task is not None and not self._process_task.done():
            _LOGGER.debug(
                "Skipping %s: another artist is being processed", now_playing.artist
            )
            return
        self._process_task = self.hass.async_create_task(
            self._async_process(now_playing)
        )

    async def _async_process(self, now_playing: NowPlaying) -> None:
        try:
            await self.async_add_artist_name(
                now_playing.artist,
                now_playing.album,
                source="sensor",
                now_playing=now_playing,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unexpected error while syncing %s", now_playing.artist)
            self._record_result(
                "error",
                now_playing.artist,
                album=now_playing.album,
                source="sensor",
                error="Unexpected error, see the Home Assistant log",
            )
        finally:
            self._pending_artist = None
            self._dispatch()

    def _current_now_playing(self) -> NowPlaying | None:
        entity_id = self.entity_id
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if entity_id.split(".", 1)[0] == MEDIA_PLAYER_DOMAIN:
            return parse_media_player(
                state.attributes,
                state.state,
                only_when_playing=self.only_when_playing,
            )
        return parse_now_playing(
            state.attributes,
            self.packages,
            only_when_playing=self.only_when_playing,
            entity_state=state.state,
        )

    # ------------------------------------------------------------------
    # Adding artists
    # ------------------------------------------------------------------
    async def async_check_now(self) -> dict[str, Any]:
        """Read the sensor immediately and sync the current artist."""
        if not self._enabled:
            return {"status": "disabled"}
        now_playing = self._current_now_playing()
        self._cancel_confirm()
        self._pending_artist = None
        if now_playing is None:
            return {"status": "no_media"}
        self._observed_key = normalize_name(now_playing.artist)
        try:
            return await self.async_add_artist_name(
                now_playing.artist,
                now_playing.album,
                source="service",
                force=True,
                now_playing=now_playing,
            )
        finally:
            self._dispatch()

    async def async_add_artist_name(
        self,
        artist: str,
        album: str | None = None,
        *,
        source: str = "service",
        force: bool = False,
        respect_ignore: bool = True,
        now_playing: NowPlaying | None = None,
    ) -> dict[str, Any]:
        """Look up and add a single artist, with de-duplication."""
        artist = artist.strip()
        key = normalize_name(artist)
        if not key:
            return {"status": "invalid", "artist": artist}

        if respect_ignore and self._is_ignored(key):
            self._record_result("ignored", artist, album=album, source=source)
            return {"status": "ignored", "artist": artist}

        if not force and self._is_seen(key):
            return {"status": "skipped", "reason": "already_seen", "artist": artist}

        async with self._lock:
            if not force and self._is_seen(key):
                return {
                    "status": "skipped",
                    "reason": "already_seen",
                    "artist": artist,
                }
            try:
                candidates = await self.client.async_lookup_artist(artist)
            except LidarrAuthError as err:
                _LOGGER.error("%s: %s", NAME, err)
                self._record_result(
                    "auth_error", artist, album=album, source=source, error=str(err)
                )
                return {"status": "auth_error", "artist": artist}
            except LidarrError as err:
                _LOGGER.warning("%s could not search for %s: %s", NAME, artist, err)
                self._record_result(
                    "error", artist, album=album, source=source, error=str(err)
                )
                return {"status": "error", "artist": artist, "error": str(err)}

            candidate = choose_candidate(candidates, artist, self.match_strategy)
            if candidate is None:
                _LOGGER.debug(
                    "%s found no confident match for %s (%d candidates)",
                    NAME,
                    artist,
                    len(candidates),
                )
                self._remember(key, artist, "not_found")
                self._record_result(
                    "not_found",
                    artist,
                    album=album,
                    source=source,
                    detail=(
                        "No exact artist name match in Lidarr. "
                        "Set the matching strategy to 'first' if Lidarr lists the artist."
                    ),
                )
                return {"status": "not_found", "artist": artist}

            if candidate.library_id is not None:
                _LOGGER.debug("%s is already in Lidarr (%s)", artist, candidate.mbid)
                self._remember(key, artist, "exists", mbid=candidate.mbid)
                self._record_result(
                    "exists",
                    artist,
                    album=album,
                    source=source,
                    candidate=candidate,
                )
                return {
                    "status": "exists",
                    "artist": candidate.name,
                    "mbid": candidate.mbid,
                }

            if self.dry_run:
                _LOGGER.info(
                    "%s dry run: would add %s (%s)",
                    NAME,
                    candidate.name,
                    candidate.mbid,
                )
                self._record_result(
                    "would_add",
                    artist,
                    album=album,
                    source=source,
                    candidate=candidate,
                )
                return {
                    "status": "would_add",
                    "artist": candidate.name,
                    "mbid": candidate.mbid,
                }

            try:
                added = await self.client.async_add_artist(
                    mbid=candidate.mbid,
                    name=candidate.name,
                    root_folder=self.root_folder,
                    quality_profile_id=self.quality_profile_id,
                    metadata_profile_id=self.metadata_profile_id,
                    monitor=self.monitor,
                    search_for_missing_albums=self.search_missing_albums,
                )
            except LidarrError as err:
                message = str(err)
                if any(
                    token in message.casefold()
                    for token in (
                        "already exists",
                        "already in database",
                        "already been added",
                        "artistexistsvalidator",
                    )
                ):
                    self._remember(key, artist, "exists", mbid=candidate.mbid)
                    self._record_result(
                        "exists",
                        artist,
                        album=album,
                        source=source,
                        candidate=candidate,
                    )
                    return {
                        "status": "exists",
                        "artist": candidate.name,
                        "mbid": candidate.mbid,
                    }
                _LOGGER.error("%s could not add %s: %s", NAME, candidate.name, err)
                self._record_result(
                    "error",
                    artist,
                    album=album,
                    source=source,
                    candidate=candidate,
                    error=message,
                )
                return {"status": "error", "artist": candidate.name, "error": message}

            library_id = added.get("id") if isinstance(added, Mapping) else None
            self._remember(key, artist, "added", mbid=candidate.mbid)
            self._last_added = {
                "artist": candidate.name,
                "album": album,
                "title": now_playing.title if now_playing else None,
                "mbid": candidate.mbid,
                "library_id": library_id,
                "added_at": dt_util.utcnow().isoformat(),
                "source": source,
                "package": now_playing.package if now_playing else None,
            }
            self._record_result(
                "added",
                artist,
                album=album,
                source=source,
                candidate=candidate,
            )
            _LOGGER.info("%s added %s to Lidarr", NAME, candidate.name)
            self.hass.bus.async_fire(
                EVENT_ARTIST_ADDED,
                {
                    "entry_id": self.entry.entry_id,
                    "artist": candidate.name,
                    "album": album,
                    "title": now_playing.title if now_playing else None,
                    "mbid": candidate.mbid,
                    "artist_id": library_id,
                    "package": now_playing.package if now_playing else None,
                    "source": source,
                    "url": self.client.url,
                },
            )
            self._notify_added(candidate, album, library_id)
            return {
                "status": "added",
                "artist": candidate.name,
                "mbid": candidate.mbid,
                "artist_id": library_id,
            }

    # ------------------------------------------------------------------
    # Persistence / bookkeeping
    # ------------------------------------------------------------------
    def _is_seen(self, key: str | None) -> bool:
        if not key:
            return False
        entry = self._seen.get(key)
        if entry is None:
            return False
        if entry.get("status") in _TERMINAL_NEGATIVE_STATUSES:
            try:
                age = time.time() - float(entry.get("ts", 0))
            except (TypeError, ValueError):
                age = SEEN_RETRY_SECONDS + 1
            if age > SEEN_RETRY_SECONDS:
                self._seen.pop(key, None)
                self._save()
                return False
        return True

    def _is_ignored(self, key: str | None) -> bool:
        if not key:
            return False
        return key in {normalize_name(name) for name in self.ignored_artists}

    def _remember(
        self,
        key: str,
        artist: str,
        status: str,
        *,
        mbid: str | None = None,
    ) -> None:
        self._seen[key] = {
            "artist": artist,
            "status": status,
            "ts": time.time(),
            "mbid": mbid,
        }
        self._trim_seen()
        self._save()

    def _trim_seen(self) -> None:
        if len(self._seen) <= SEEN_LIMIT:
            return
        newest = sorted(
            self._seen.items(),
            key=lambda item: float(item[1].get("ts", 0) or 0),
            reverse=True,
        )[:SEEN_LIMIT]
        self._seen = dict(newest)

    def _record_result(
        self,
        status: str,
        artist: str,
        *,
        album: str | None = None,
        source: str = "sensor",
        candidate: ArtistCandidate | None = None,
        error: str | None = None,
        detail: str | None = None,
    ) -> None:
        self._last_result = {
            "status": status,
            "artist": artist,
            "album": album,
            "source": source,
            "at": dt_util.utcnow().isoformat(),
            "mbid": candidate.mbid if candidate else None,
            "matched_name": candidate.name if candidate else None,
            "error": error,
            "detail": detail,
        }
        if status != "added":
            _LOGGER.debug("%s result for %s: %s", NAME, artist, status)
        self._save()
        self._dispatch()

    @callback
    def _notify_added(
        self,
        candidate: ArtistCandidate,
        album: str | None,
        library_id: int | None,
    ) -> None:
        if not self.notify_on_add:
            return
        message = f"Added **{candidate.name}** to Lidarr."
        if album:
            message += f"\n\nDetected while playing from _{album}_."
        if library_id:
            message += f"\n\nLidarr artist ID: `{library_id}`"
        persistent_notification.async_create(
            self.hass,
            message,
            title=f"{NAME}: artist added",
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_added",
        )

    @callback
    def _dispatch(self) -> None:
        async_dispatcher_send(self.hass, self.signal_update)

    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 2)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "version": STORAGE_VERSION,
            "enabled": self._enabled,
            "seen": self._seen,
            "last_added": self._last_added,
            "last_result": self._last_result,
        }

    @callback
    def _cancel_confirm(self) -> None:
        if self._confirm_task is not None and not self._confirm_task.done():
            self._confirm_task.cancel()
        self._confirm_task = None

    async def async_reset_history(self) -> None:
        """Forget everything that was seen, so artists can be retried."""
        self._seen.clear()
        self._last_added = None
        self._last_result = None
        self._observed_key = None
        await self._store.async_save(self._data_to_save())
        self._dispatch()

    def diagnostics(self) -> dict[str, Any]:
        """Return non-sensitive runtime information for diagnostics."""
        return {
            "enabled": self._enabled,
            "entity_id": self.entity_id,
            "packages": self.packages,
            "only_when_playing": self.only_when_playing,
            "min_play_seconds": self.min_play_seconds,
            "match_strategy": self.match_strategy,
            "dry_run": self.dry_run,
            "notify_on_add": self.notify_on_add,
            "root_folder": self.root_folder,
            "quality_profile_id": self.quality_profile_id,
            "metadata_profile_id": self.metadata_profile_id,
            "monitor": self.monitor,
            "search_missing_albums": self.search_missing_albums,
            "ignored_artists": self.ignored_artists,
            "pending_artist": self._pending_artist,
            "seen_count": len(self._seen),
            "last_added": self._last_added,
            "last_result": self._last_result,
            "lidarr_url": self.client.url,
            "lidarr_reachable": self.coordinator.last_update_success,
        }

    @staticmethod
    def result_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        """Shape service responses for one or more config entries."""
        if len(results) == 1:
            return results[0]
        return {"results": results}
