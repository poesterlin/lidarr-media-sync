"""Constants for the Lidarr Media Sync integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "lidarr_media_sync"
NAME = "Lidarr Media Sync"
VERSION = "0.1.0"

# Configuration keys -------------------------------------------------------
CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_ENTITY_ID = "entity_id"
CONF_PACKAGES = "packages"
CONF_ONLY_WHEN_PLAYING = "only_when_playing"
CONF_MIN_PLAY_SECONDS = "min_play_seconds"
CONF_ROOT_FOLDER = "root_folder"
CONF_QUALITY_PROFILE_ID = "quality_profile_id"
CONF_METADATA_PROFILE_ID = "metadata_profile_id"
CONF_MONITOR = "monitor"
CONF_SEARCH_MISSING = "search_missing_albums"
CONF_MATCH_STRATEGY = "match_strategy"
CONF_DRY_RUN = "dry_run"
CONF_NOTIFY_ON_ADD = "notify_on_add"
CONF_IGNORED_ARTISTS = "ignored_artists"

# Defaults ----------------------------------------------------------------
DEFAULT_URL = "http://localhost:8686"
DEFAULT_PACKAGES = ["com.google.android.apps.youtube.music"]
DEFAULT_ONLY_WHEN_PLAYING = True
DEFAULT_MIN_PLAY_SECONDS = 0
DEFAULT_MONITOR = "all"
DEFAULT_MATCH_STRATEGY = "exact"
DEFAULT_SEARCH_MISSING = False
DEFAULT_DRY_RUN = False
DEFAULT_NOTIFY_ON_ADD = False

# Behaviour ---------------------------------------------------------------
# The companion app reports these values in playback_state_<package>.
PLAYING_STATES = frozenset({"playing", "buffering"})

CONF_ENTRY_ID = "entry_id"
ATTR_ARTIST = "artist"
ATTR_ALBUM = "album"

SERVICE_ADD_ARTIST = "add_artist"
SERVICE_SYNC_NOW = "sync_now"
SERVICE_RESET_HISTORY = "reset_history"

EVENT_ARTIST_ADDED = f"{DOMAIN}_artist_added"

# Attribute names exposed by the Android companion app's media_session sensor.
ATTR_ARTIST_PREFIX = "artist_"
ATTR_ALBUM_PREFIX = "album_"
ATTR_TITLE_PREFIX = "title_"
ATTR_PLAYBACK_STATE_PREFIX = "playback_state_"

# Standard media_player attributes.
ATTR_MEDIA_ARTIST = "media_artist"
ATTR_MEDIA_ALBUM_ARTIST = "media_album_artist"
ATTR_MEDIA_ALBUM = "media_album_name"
ATTR_MEDIA_TITLE = "media_title"

MEDIA_PLAYER_DOMAIN = "media_player"
SENSOR_DOMAIN = "sensor"

MONITOR_OPTIONS = (
    "all",
    "future",
    "missing",
    "existing",
    "latest",
    "first",
    "none",
)
MONITOR_LABELS = {
    "all": "All albums",
    "future": "Future albums",
    "missing": "Missing albums",
    "existing": "Existing albums",
    "latest": "Latest album",
    "first": "First album",
    "none": "No albums",
}
MATCH_STRATEGIES = ("exact", "first")
MATCH_STRATEGY_LABELS = {
    "exact": "Exact name match (safest)",
    "first": "First Lidarr search result",
}

# Polling / housekeeping --------------------------------------------------
UPDATE_INTERVAL = timedelta(minutes=5)
REQUEST_TIMEOUT = 20
SEEN_RETRY_SECONDS = 24 * 60 * 60
SEEN_LIMIT = 2000
STORAGE_VERSION = 1
