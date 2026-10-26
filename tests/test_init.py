"""End-to-end tests for the integration setup and sync flow."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lidarr_media_sync.const import (
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
    DOMAIN,
    EVENT_ARTIST_ADDED,
    SERVICE_ADD_ARTIST,
)

BASE_URL = "http://lidarr.local:8686"
ENTITY_ID = "sensor.pixel_media_session"
PACKAGE = "com.google.android.apps.youtube.music"

JENNIE_LOOKUP = [
    {
        "artistName": "Jennie",
        "foreignArtistId": "finnish-jennie",
        "disambiguation": "Finnish artist",
    },
    {
        "artistName": "JENNIE",
        "foreignArtistId": "blackpink-jennie",
        "disambiguation": "BLACKPINK",
    },
]


def _options(**overrides: Any) -> dict[str, Any]:
    options = {
        CONF_ENTITY_ID: ENTITY_ID,
        CONF_PACKAGES: [PACKAGE],
        CONF_ONLY_WHEN_PLAYING: True,
        CONF_MIN_PLAY_SECONDS: 0,
        CONF_ROOT_FOLDER: "/music-ingest",
        CONF_QUALITY_PROFILE_ID: 2,
        CONF_METADATA_PROFILE_ID: 1,
        CONF_MONITOR: "all",
        CONF_SEARCH_MISSING: False,
        CONF_MATCH_STRATEGY: "exact",
        CONF_DRY_RUN: False,
        CONF_NOTIFY_ON_ADD: False,
        CONF_IGNORED_ARTISTS: [],
    }
    options.update(overrides)
    return options


def _set_media(
    hass, artist: str, *, state: str = "Playing", album: str = "Album"
) -> None:
    hass.states.async_set(
        ENTITY_ID,
        state,
        {
            f"artist_{PACKAGE}": artist,
            f"album_{PACKAGE}": album,
            f"playback_state_{PACKAGE}": state,
        },
    )


async def _setup_entry(hass, aioclient_mock, **overrides) -> MockConfigEntry:
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", json={"version": "3.1.0.4875"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidarr Media Sync",
        data={CONF_URL: BASE_URL, CONF_API_KEY: "secret-key"},
        options=_options(**overrides),
        entry_id="test-entry",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass, platform: str, unique_id: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, unique_id)


async def test_adds_exact_match_and_updates_sensor(hass, aioclient_mock):
    """A new YouTube Music artist is looked up and added once."""
    events = []
    hass.bus.async_listen(EVENT_ARTIST_ADDED, events.append)
    entry = await _setup_entry(hass, aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist", json={"id": 9001, "artistName": "JENNIE"}
    )

    _set_media(hass, "JENNIE", album="Fallen Angel (Digital EP)")
    await hass.async_block_till_done()

    lookups = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and "/artist/lookup" in str(call[1])
    ]
    posts = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == f"{BASE_URL}/api/v1/artist"
    ]
    assert len(lookups) == 1
    assert len(posts) == 1
    body = posts[0][2]
    assert body["foreignArtistId"] == "blackpink-jennie"
    assert body["rootFolderPath"] == "/music-ingest"
    assert body["qualityProfileId"] == 2

    sensor_id = _entity_id(hass, "sensor", f"{entry.entry_id}_last_added")
    assert sensor_id is not None
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == "JENNIE"
    assert state.attributes["last_result"]["status"] == "added"
    assert state.attributes["last_added"]["album"] == "Fallen Angel (Digital EP)"

    assert len(events) == 1
    assert events[0].data["artist"] == "JENNIE"
    assert events[0].data["mbid"] == "blackpink-jennie"
    assert events[0].data["album"] == "Fallen Angel (Digital EP)"
    assert events[0].data["artist_id"] == 9001
    assert events[0].data["entry_id"] == entry.entry_id

    binary_id = _entity_id(hass, "binary_sensor", f"{entry.entry_id}_connected")
    assert binary_id is not None
    assert hass.states.get(binary_id).state == "on"

    switch_id = _entity_id(hass, "switch", f"{entry.entry_id}_enabled")
    assert switch_id is not None
    assert hass.states.get(switch_id).state == "on"


async def test_media_player_source(hass, aioclient_mock):
    """A standard media_player entity can be the source."""
    media_player_id = "media_player.kitchen"
    entry = await _setup_entry(
        hass, aioclient_mock, **{CONF_ENTITY_ID: media_player_id}
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist", json={"id": 9001, "artistName": "JENNIE"}
    )

    hass.states.async_set(
        media_player_id,
        "paused",
        {
            "media_artist": "JENNIE",
            "media_album_name": "Fallen Angel (Digital EP)",
            "media_title": "Fallen Angel",
        },
    )
    await hass.async_block_till_done()

    lookups = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and "/artist/lookup" in str(call[1])
    ]
    assert lookups == []

    hass.states.async_set(
        media_player_id,
        "playing",
        {
            "media_artist": "JENNIE",
            "media_album_name": "Fallen Angel (Digital EP)",
            "media_title": "Fallen Angel",
        },
    )
    await hass.async_block_till_done()

    posts = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == f"{BASE_URL}/api/v1/artist"
    ]
    assert len(posts) == 1
    assert posts[0][2]["foreignArtistId"] == "blackpink-jennie"

    sensor_id = _entity_id(hass, "sensor", f"{entry.entry_id}_last_added")
    state = hass.states.get(sensor_id)
    assert state.state == "JENNIE"
    assert state.attributes["last_added"]["album"] == "Fallen Angel (Digital EP)"


async def test_does_not_add_the_same_artist_twice(hass, aioclient_mock):
    """Repeated sensor updates for the same artist do not trigger more calls."""
    await _setup_entry(hass, aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist", json={"id": 9001, "artistName": "JENNIE"}
    )

    _set_media(hass, "JENNIE")
    await hass.async_block_till_done()
    _set_media(hass, "JENNIE", album="Another Album")
    await hass.async_block_till_done()

    lookups = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and "/artist/lookup" in str(call[1])
    ]
    posts = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == f"{BASE_URL}/api/v1/artist"
    ]
    assert len(lookups) == 1
    assert len(posts) == 1


async def test_existing_artist_is_not_added_again(hass, aioclient_mock):
    """A lookup result with a library id means the artist already exists."""
    entry = await _setup_entry(hass, aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "Dua Lipa"},
        json=[
            {
                "id": 337,
                "artistName": "Dua Lipa",
                "foreignArtistId": "mbid-dua",
            }
        ],
    )

    _set_media(hass, "Dua Lipa")
    await hass.async_block_till_done()

    posts = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == f"{BASE_URL}/api/v1/artist"
    ]
    assert posts == []

    sensor_id = _entity_id(hass, "sensor", f"{entry.entry_id}_last_added")
    state = hass.states.get(sensor_id)
    assert state.attributes["last_result"]["status"] == "exists"
    assert state.state == "unknown"


async def test_duplicate_error_is_treated_as_exists(hass, aioclient_mock):
    """Lidarr's 'already been added' validation error is not a failure."""
    entry = await _setup_entry(hass, aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist",
        status=400,
        text='[{"errorMessage":"This artist has already been added."}]',
    )

    _set_media(hass, "JENNIE")
    await hass.async_block_till_done()

    sensor_id = _entity_id(hass, "sensor", f"{entry.entry_id}_last_added")
    state = hass.states.get(sensor_id)
    assert state.attributes["last_result"]["status"] == "exists"


async def test_dry_run_does_not_write_to_lidarr(hass, aioclient_mock):
    """Dry run reports would_add without a POST."""
    entry = await _setup_entry(hass, aioclient_mock, **{CONF_DRY_RUN: True})
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )

    _set_media(hass, "JENNIE")
    await hass.async_block_till_done()

    posts = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == f"{BASE_URL}/api/v1/artist"
    ]
    assert posts == []

    sensor_id = _entity_id(hass, "sensor", f"{entry.entry_id}_last_added")
    state = hass.states.get(sensor_id)
    assert state.attributes["last_result"]["status"] == "would_add"


async def test_pause_switch_stops_automatic_adds(hass, aioclient_mock):
    """Turning the switch off prevents lookups."""
    entry = await _setup_entry(hass, aioclient_mock)
    switch_id = _entity_id(hass, "switch", f"{entry.entry_id}_enabled")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch_id}, blocking=True
    )
    _set_media(hass, "JENNIE")
    await hass.async_block_till_done()

    lookups = [
        call
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and "/artist/lookup" in str(call[1])
    ]
    assert lookups == []


async def test_add_artist_service(hass, aioclient_mock):
    """The manual service uses the same matching pipeline."""
    await _setup_entry(hass, aioclient_mock)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "JENNIE"},
        json=JENNIE_LOOKUP,
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist", json={"id": 9001, "artistName": "JENNIE"}
    )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_ARTIST,
        {"artist": "JENNIE"},
        blocking=True,
        return_response=True,
    )

    assert response["status"] == "added"
    assert response["mbid"] == "blackpink-jennie"


async def test_unload_entry(hass, aioclient_mock):
    """Unloading stops listeners and removes entities."""
    entry = await _setup_entry(hass, aioclient_mock)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.name == "NOT_LOADED"
