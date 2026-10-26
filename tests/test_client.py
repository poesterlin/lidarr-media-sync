"""Tests for the Lidarr API client."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.lidarr_media_sync.client import (
    LidarrAuthError,
    LidarrClient,
    LidarrConnectionError,
    LidarrError,
)

BASE_URL = "http://lidarr.local:8686"


@pytest.fixture
def client(hass) -> LidarrClient:
    """Return a client using Home Assistant's mocked session."""
    return LidarrClient(async_get_clientsession(hass), BASE_URL, "secret-key")


async def test_system_status_sends_api_key(hass, aioclient_mock, client):
    """The API key is sent in the X-Api-Key header."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", json={"version": "3.1.0.4875"}
    )

    status = await client.async_get_system_status()

    assert status["version"] == "3.1.0.4875"
    assert aioclient_mock.mock_calls[0][3]["X-Api-Key"] == "secret-key"


async def test_auth_error(hass, aioclient_mock, client):
    """A 401 becomes LidarrAuthError."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/system/status", status=401)

    with pytest.raises(LidarrAuthError):
        await client.async_get_system_status()


async def test_server_error(hass, aioclient_mock, client):
    """Other HTTP errors become LidarrError."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/system/status", status=500, text="boom")

    with pytest.raises(LidarrError, match="HTTP 500"):
        await client.async_get_system_status()


async def test_connection_error(hass, aioclient_mock, client):
    """Network errors become LidarrConnectionError."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", exc=aiohttp.ClientError("unreachable")
    )

    with pytest.raises(LidarrConnectionError, match="Could not reach Lidarr"):
        await client.async_get_system_status()


async def test_lookup_artist(hass, aioclient_mock, client):
    """Lookup results are converted into candidates, including library ids."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/artist/lookup",
        params={"term": "Dua Lipa"},
        json=[
            {
                "id": 337,
                "artistName": "Dua Lipa",
                "foreignArtistId": "mbid-dua",
                "artistType": "Person",
            },
            {
                "artistName": "Dua",
                "foreignArtistId": "mbid-dua-other",
            },
        ],
    )

    candidates = await client.async_lookup_artist("Dua Lipa")

    assert [candidate.name for candidate in candidates] == ["Dua Lipa", "Dua"]
    assert candidates[0].library_id == 337
    assert candidates[1].library_id is None


async def test_add_artist_payload(hass, aioclient_mock, client):
    """The add payload matches Lidarr's ArtistResource expectations."""
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/artist", json={"id": 42, "artistName": "JENNIE"}
    )

    result = await client.async_add_artist(
        mbid="779351de-0da5-4943-928b-495a3c40e8c0",
        name="JENNIE",
        root_folder="/music-ingest",
        quality_profile_id=2,
        metadata_profile_id=1,
        monitor="all",
        search_for_missing_albums=False,
    )

    assert result["id"] == 42
    method, url, body, _headers = aioclient_mock.mock_calls[0]
    assert method.lower() == "post"
    assert str(url) == f"{BASE_URL}/api/v1/artist"
    assert body == {
        "artistName": "JENNIE",
        "foreignArtistId": "779351de-0da5-4943-928b-495a3c40e8c0",
        "qualityProfileId": 2,
        "metadataProfileId": 1,
        "rootFolderPath": "/music-ingest",
        "monitored": True,
        "monitorNewItems": "all",
        "addOptions": {
            "monitor": "all",
            "albumsToMonitor": [],
            "monitored": True,
            "searchForMissingAlbums": False,
        },
    }
