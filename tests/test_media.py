"""Tests for media session parsing."""

from __future__ import annotations

from custom_components.lidarr_media_sync.media import (
    clean_text,
    parse_media_player,
    parse_now_playing,
)

YT_MUSIC = "com.google.android.apps.youtube.music"
YOUTUBE = "com.google.android.youtube"


def test_parses_artist_album_and_state():
    result = parse_now_playing(
        {
            f"artist_{YT_MUSIC}": "JENNIE",
            f"album_{YT_MUSIC}": "Fallen Angel (Digital EP)",
            f"title_{YT_MUSIC}": "Fallen Angel",
            f"playback_state_{YT_MUSIC}": "Playing",
        },
        [YT_MUSIC],
        entity_state="Playing",
    )
    assert result is not None
    assert result.artist == "JENNIE"
    assert result.album == "Fallen Angel (Digital EP)"
    assert result.title == "Fallen Angel"
    assert result.package == YT_MUSIC
    assert result.playback_state == "Playing"


def test_skips_paused_package_and_uses_next_playing_package():
    result = parse_now_playing(
        {
            f"artist_{YT_MUSIC}": "Paused Artist",
            f"playback_state_{YT_MUSIC}": "Paused",
            f"artist_{YOUTUBE}": "Video Artist",
            f"playback_state_{YOUTUBE}": "Playing",
        },
        [YT_MUSIC, YOUTUBE],
    )
    assert result is not None
    assert result.artist == "Video Artist"
    assert result.package == YOUTUBE


def test_falls_back_to_entity_state():
    attributes = {
        f"artist_{YT_MUSIC}": "JENNIE",
        f"album_{YT_MUSIC}": "Fallen Angel",
    }
    assert parse_now_playing(attributes, [YT_MUSIC], entity_state="Paused") is None
    result = parse_now_playing(
        attributes, [YT_MUSIC], only_when_playing=False, entity_state="Paused"
    )
    assert result is not None
    assert result.artist == "JENNIE"


def test_missing_playback_state_is_allowed():
    result = parse_now_playing(
        {f"artist_{YT_MUSIC}": "JENNIE"},
        [YT_MUSIC],
        entity_state="Playing",
    )
    assert result is not None
    assert result.playback_state == "Playing"


def test_null_artist_and_album_are_ignored():
    result = parse_now_playing(
        {
            f"artist_{YT_MUSIC}": "null",
            f"album_{YT_MUSIC}": "null",
            f"playback_state_{YT_MUSIC}": "Playing",
        },
        [YT_MUSIC],
    )
    assert result is None


def test_unknown_package_is_ignored():
    result = parse_now_playing(
        {
            "artist_com.spotify.music": "Spotify Artist",
            "playback_state_com.spotify.music": "Playing",
        },
        [YT_MUSIC],
    )
    assert result is None


def test_clean_text_handles_lists_and_placeholders():
    assert clean_text(None) is None
    assert clean_text("   ") is None
    assert clean_text("null") is None
    assert clean_text("Unknown") is None
    assert clean_text(["A", "B"]) == "A, B"
    assert clean_text("  Artist  ") == "Artist"


def test_media_player_playing():
    result = parse_media_player(
        {
            "media_artist": "JENNIE",
            "media_album_name": "Fallen Angel (Digital EP)",
            "media_title": "Fallen Angel",
        },
        "playing",
    )
    assert result is not None
    assert result.artist == "JENNIE"
    assert result.album == "Fallen Angel (Digital EP)"
    assert result.title == "Fallen Angel"
    assert result.playback_state == "playing"
    assert result.package is None


def test_media_player_paused_is_skipped_by_default():
    attributes = {"media_artist": "JENNIE"}
    assert parse_media_player(attributes, "paused") is None
    result = parse_media_player(attributes, "paused", only_when_playing=False)
    assert result is not None
    assert result.artist == "JENNIE"


def test_media_player_album_artist_fallback_and_lists():
    result = parse_media_player(
        {"media_album_artist": ["Artist One", "Artist Two"]},
        "playing",
    )
    assert result is not None
    assert result.artist == "Artist One, Artist Two"


def test_media_player_without_artist_is_ignored():
    assert parse_media_player({"media_title": "A title"}, "playing") is None
    assert parse_media_player({"media_artist": "null"}, "playing") is None
