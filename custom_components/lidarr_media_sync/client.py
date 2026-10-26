"""Small async client for the Lidarr v1 API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT
from .matching import ArtistCandidate, candidates_from_api

_LOGGER = logging.getLogger(__name__)


class LidarrError(Exception):
    """Base error for Lidarr communication problems."""


class LidarrAuthError(LidarrError):
    """Lidarr rejected the API key."""


class LidarrConnectionError(LidarrError):
    """Lidarr could not be reached."""


class LidarrClient:
    """Minimal Lidarr API client used by the integration."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        api_key: str,
    ) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._api_url = f"{self._url}/api/v1"

    @property
    def url(self) -> str:
        """Return the configured base URL (never the API key)."""
        return self._url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._api_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                headers={
                    "X-Api-Key": self._api_key,
                    "Accept": "application/json",
                },
                params=params,
                json=json,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise LidarrAuthError("Lidarr rejected the API key")
                if response.status >= 400:
                    body = (await response.text())[:500]
                    raise LidarrError(
                        f"Lidarr API returned HTTP {response.status}: {body}"
                    )
                if response.status == 204:
                    return None
                return await response.json(content_type=None)
        except LidarrError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LidarrConnectionError(
                f"Could not reach Lidarr at {self._url}: {err}"
            ) from err

    async def async_get_system_status(self) -> dict[str, Any]:
        """Return /system/status, which also validates the API key."""
        return await self._request("GET", "/system/status")

    async def async_get_root_folders(self) -> list[dict[str, Any]]:
        """Return all configured root folders."""
        return await self._request("GET", "/rootfolder")

    async def async_get_quality_profiles(self) -> list[dict[str, Any]]:
        """Return all quality profiles."""
        return await self._request("GET", "/qualityprofile")

    async def async_get_metadata_profiles(self) -> list[dict[str, Any]]:
        """Return all metadata profiles."""
        return await self._request("GET", "/metadataprofile")

    async def async_lookup_artist(self, term: str) -> list[ArtistCandidate]:
        """Search MusicBrainz through Lidarr and return candidates.

        Results that are already in the library carry a non-zero ``id`` which
        is used as the "already added" check without downloading the whole
        (multi-megabyte) artist list.
        """
        results = await self._request("GET", "/artist/lookup", params={"term": term})
        if not isinstance(results, list):
            return []
        return candidates_from_api(results)

    async def async_add_artist(
        self,
        *,
        mbid: str,
        name: str,
        root_folder: str,
        quality_profile_id: int,
        metadata_profile_id: int,
        monitor: str = "all",
        search_for_missing_albums: bool = False,
    ) -> dict[str, Any]:
        """Add an artist to Lidarr and return the created resource."""
        payload = {
            "artistName": name,
            "foreignArtistId": mbid,
            "qualityProfileId": quality_profile_id,
            "metadataProfileId": metadata_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "monitorNewItems": "all",
            "addOptions": {
                "monitor": monitor,
                "albumsToMonitor": [],
                "monitored": True,
                "searchForMissingAlbums": search_for_missing_albums,
            },
        }
        _LOGGER.debug("Adding artist %s (%s) to Lidarr", name, mbid)
        return await self._request("POST", "/artist", json=payload)
