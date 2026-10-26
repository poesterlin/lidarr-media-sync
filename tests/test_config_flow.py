"""Tests for the config and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
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
)

BASE_URL = "http://lidarr.local:8686"
ENTITY_ID = "sensor.pixel_media_session"


def _mock_lidarr(aioclient_mock) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", json={"version": "3.1.0.4875"}
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/rootfolder",
        json=[{"id": 4, "name": "ingest", "path": "/music-ingest"}],
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/qualityprofile",
        json=[
            {"id": 1, "name": "Any"},
            {"id": 2, "name": "Lossless"},
        ],
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/metadataprofile",
        json=[{"id": 1, "name": "Standard"}],
    )


def _settings_input(**overrides):
    data = {
        CONF_ENTITY_ID: ENTITY_ID,
        CONF_PACKAGES: "com.google.android.apps.youtube.music",
        CONF_ONLY_WHEN_PLAYING: True,
        CONF_MIN_PLAY_SECONDS: 0,
        CONF_ROOT_FOLDER: "/music-ingest",
        CONF_QUALITY_PROFILE_ID: "2",
        CONF_METADATA_PROFILE_ID: "1",
        CONF_MONITOR: "all",
        CONF_SEARCH_MISSING: False,
        CONF_MATCH_STRATEGY: "exact",
        CONF_DRY_RUN: False,
        CONF_NOTIFY_ON_ADD: False,
        CONF_IGNORED_ARTISTS: "",
    }
    data.update(overrides)
    return data


async def test_full_config_flow(hass, aioclient_mock):
    """The two-step flow creates an entry with normalised options."""
    hass.states.async_set(
        ENTITY_ID,
        "Playing",
        {"artist_com.google.android.apps.youtube.music": "JENNIE"},
    )
    _mock_lidarr(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE_URL + "/", CONF_API_KEY: "secret-key"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _settings_input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: BASE_URL, CONF_API_KEY: "secret-key"}
    assert result["options"][CONF_PACKAGES] == ["com.google.android.apps.youtube.music"]
    assert result["options"][CONF_QUALITY_PROFILE_ID] == 2
    assert result["options"][CONF_METADATA_PROFILE_ID] == 1
    assert result["options"][CONF_IGNORED_ARTISTS] == []


async def test_config_flow_invalid_auth(hass, aioclient_mock):
    """A rejected key is shown as an invalid_auth error."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/system/status", status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE_URL, CONF_API_KEY: "wrong"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_config_flow_cannot_connect(hass, aioclient_mock):
    """A server error is shown as cannot_connect."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/system/status", status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE_URL, CONF_API_KEY: "secret-key"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_config_flow_without_root_folder(hass, aioclient_mock):
    """Setup stops with a useful error when Lidarr has no root folder."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", json={"version": "3.1.0.4875"}
    )
    aioclient_mock.get(f"{BASE_URL}/api/v1/rootfolder", json=[])
    aioclient_mock.get(f"{BASE_URL}/api/v1/qualityprofile", json=[{"id": 1}])
    aioclient_mock.get(f"{BASE_URL}/api/v1/metadataprofile", json=[{"id": 1}])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE_URL, CONF_API_KEY: "secret-key"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_root_folder"}


async def test_reauth_flow(hass, aioclient_mock):
    """A reauthentication updates the API key and reloads the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidarr Media Sync",
        data={CONF_URL: BASE_URL, CONF_API_KEY: "old-key"},
        options=_settings_input(),
        unique_id="test",
    )
    entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/system/status", json={"version": "3.1.0.4875"}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL, CONF_API_KEY: "new-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"


async def test_options_flow(hass, aioclient_mock):
    """Options are editable after setup and reload the entry."""
    _mock_lidarr(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Lidarr Media Sync",
        data={CONF_URL: BASE_URL, CONF_API_KEY: "secret-key"},
        options=_settings_input(
            **{
                CONF_QUALITY_PROFILE_ID: 2,
                CONF_METADATA_PROFILE_ID: 1,
            }
        ),
        unique_id="test",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _settings_input(**{CONF_DRY_RUN: True, CONF_MONITOR: "future"}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DRY_RUN] is True
    assert result["data"][CONF_MONITOR] == "future"
