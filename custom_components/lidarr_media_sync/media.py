"""Parsing helpers for media session sensors and media_player entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    ATTR_ALBUM_PREFIX,
    ATTR_ARTIST_PREFIX,
    ATTR_MEDIA_ALBUM,
    ATTR_MEDIA_ALBUM_ARTIST,
    ATTR_MEDIA_ARTIST,
    ATTR_MEDIA_TITLE,
    ATTR_PLAYBACK_STATE_PREFIX,
    ATTR_TITLE_PREFIX,
    PLAYING_STATES,
)

_EMPTY_VALUES = frozenset({"", "none", "null", "unknown", "unavailable", "n/a"})


@dataclass(frozen=True, slots=True)
class NowPlaying:
    """A single now-playing entry extracted from an entity state."""

    artist: str
    package: str | None = None
    album: str | None = None
    title: str | None = None
    playback_state: str | None = None


def clean_text(value: Any) -> str | None:
    """Return a useful string or None for placeholder values."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value if item not in (None, ""))
    text = str(value).strip()
    if not text or text.casefold() in _EMPTY_VALUES:
        return None
    return text


def parse_now_playing(
    attributes: Mapping[str, Any] | None,
    packages: list[str],
    *,
    only_when_playing: bool = True,
    entity_state: str | None = None,
) -> NowPlaying | None:
    """Extract the first configured package that has an artist.

    The companion app adds one attribute per active media session:
    ``artist_<package>``, ``album_<package>``, ``title_<package>``,
    ``playback_state_<package>``. The state of the sensor itself is the
    playback state of the primary session, which is used as a fallback when a
    package does not expose its own state.
    """
    if not attributes:
        return None

    for package in packages:
        if not package:
            continue
        artist = clean_text(attributes.get(f"{ATTR_ARTIST_PREFIX}{package}"))
        if artist is None:
            continue

        playback_state = clean_text(
            attributes.get(f"{ATTR_PLAYBACK_STATE_PREFIX}{package}")
        ) or clean_text(entity_state)

        if (
            only_when_playing
            and playback_state is not None
            and playback_state.casefold() not in PLAYING_STATES
        ):
            continue

        return NowPlaying(
            artist=artist,
            package=package,
            album=clean_text(attributes.get(f"{ATTR_ALBUM_PREFIX}{package}")),
            title=clean_text(attributes.get(f"{ATTR_TITLE_PREFIX}{package}")),
            playback_state=playback_state,
        )

    return None


def parse_media_player(
    attributes: Mapping[str, Any] | None,
    entity_state: str | None,
    *,
    only_when_playing: bool = True,
) -> NowPlaying | None:
    """Extract now-playing data from a standard Home Assistant media_player.

    Works with Spotify, Music Assistant, Plex, Sonos, Chromecast and anything
    else that exposes the standard ``media_artist`` / ``media_album_name`` /
    ``media_title`` attributes.
    """
    if not attributes:
        return None

    artist = clean_text(attributes.get(ATTR_MEDIA_ARTIST)) or clean_text(
        attributes.get(ATTR_MEDIA_ALBUM_ARTIST)
    )
    if artist is None:
        return None

    playback_state = clean_text(entity_state)
    if (
        only_when_playing
        and playback_state is not None
        and playback_state.casefold() not in PLAYING_STATES
    ):
        return None

    return NowPlaying(
        artist=artist,
        album=clean_text(attributes.get(ATTR_MEDIA_ALBUM)),
        title=clean_text(attributes.get(ATTR_MEDIA_TITLE)),
        playback_state=playback_state,
    )
