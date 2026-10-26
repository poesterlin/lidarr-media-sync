<img src="assets/icon.svg" width="72" height="72" alt="Lidarr Media Sync icon">

# Lidarr Media Sync

A Home Assistant custom integration that watches a media source and adds the
artist you are listening to in YouTube Music, Spotify, Music Assistant, Plex,
Sonos or any other player to [Lidarr](https://lidarr.audio).

The source can be the Android Companion App's **Media session** sensor or any
standard Home Assistant `media_player` entity. When a track changes, the artist
name is looked up in Lidarr and, if it is not already in your library, added with
the root folder, quality profile, metadata profile and album monitoring you
configured. Everything stays on your LAN: Home Assistant talks to Lidarr, nothing
is sent to a third party by this integration.

> Example: YouTube Music reports `JENNIE` and `Fallen Angel (Digital EP)` in the
> media session attributes. Lidarr Media Sync looks up `JENNIE`, prefers the
> exact name match (the BLACKPINK artist rather than the Finnish artist with the
> same name), and adds the artist.

## Features

- Works with the Android Companion App's media session sensor and with any
  standard `media_player` entity (Spotify, Music Assistant, Plex, Sonos,
  Chromecast, ...).
- For the companion sensor, reads several Android packages (YouTube Music by
  default) and only reacts while the session is playing.
- Adds the artist once, with a persistent seen-artist cache.
- Detects artists that are already in Lidarr before adding them.
- Exact-name matching by default, with an optional "first search result" mode.
- Configurable root folder, quality profile, metadata profile, album monitoring
  and "search for missing albums".
- Dry-run mode for testing without writing to Lidarr.
- Ignore list for artists you never want to add.
- Pause switch, connection sensor, last-added sensor and diagnostics.
- Services for manual adds, immediate syncs and resetting history.
- Fires a `lidarr_media_sync_artist_added` event for automations.

## Requirements

- Home Assistant 2025.4 or newer.
- Lidarr 3.x reachable from Home Assistant.
- A source entity:
  - the Android Companion App's **Media session** sensor. It needs notification
    access; its state is the playback state and its attributes look like:

    ```text
    artist_com.google.android.apps.youtube.music: JENNIE
    album_com.google.android.apps.youtube.music: Fallen Angel (Digital EP)
    playback_state_com.google.android.apps.youtube.music: Playing
    ```

  - **or** any `media_player` entity that exposes `media_artist`,
    `media_album_name` and `media_title` (Spotify, Music Assistant, Plex, Sonos,
    Chromecast, ...).

- A Lidarr API key: **Settings → General → Security → API Key**.

## Installation

### HACS

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/poesterlin/lidarr-media-sync` with category
   **Integration**.
3. Install **Lidarr Media Sync** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Lidarr Media
   Sync**.

For HACS updates, publish a release/tag in the repository after making changes.

### Manual

Copy `custom_components/lidarr_media_sync` into your Home Assistant `config`
directory:

```bash
cp -r custom_components/lidarr_media_sync /path/to/homeassistant/config/custom_components/
```

Restart Home Assistant, then add the integration from the UI.

## Configuration

The setup flow has two steps.

**Step 1 — connect to Lidarr**

| Field | Description |
| --- | --- |
| Lidarr URL | Base URL, e.g. `http://YOUR-LIDARR-HOST:8686`. No `/api/v1` suffix. |
| API key | From Lidarr's security settings. |

The URL is validated and the root folder and profile lists are loaded from
Lidarr. The field is prefilled from Home Assistant's own internal host on port
`8686`; change it if Lidarr runs on another machine.

**Step 2 — sensor and defaults**

| Option | Default | Description |
| --- | --- | --- |
| Media source | auto-detected | The Companion App media session sensor or any `media_player` entity. |
| Android media app packages | `com.google.android.apps.youtube.music` | Comma-separated Android packages to read when the source is a companion sensor. Ignored for `media_player` entities. Add `com.spotify.music` or `com.google.android.youtube` as needed. |
| Only when playing | on | Ignore `Paused`, `Stopped`, `Idle` and similar sessions. |
| Confirmation delay | 0 s | Wait and re-check the same artist before adding. `0` acts on the next sensor update. |
| Root folder | first Lidarr root folder | Where new artists are created. |
| Quality profile | first profile | Applied to new artists. |
| Metadata profile | first profile | Applied to new artists. |
| Monitor albums | All albums | `All`, `Future`, `Missing`, `Existing`, `Latest`, `First` or `None`. |
| Search for missing albums | off | Start a Lidarr search immediately after adding. Can trigger many downloads. |
| Artist matching | Exact name match | `Exact` only accepts a name match. `First search result` trusts Lidarr's order and is fuzzier. |
| Dry run | off | Look up and log without adding. |
| Create a persistent notification | off | Show a notification when an artist is added. |
| Ignored artists | empty | One name per line (or comma-separated) that is never added. |

All options except the Lidarr URL and API key can be changed later with
**Configure** on the integration card.

### Matching

`Exact` normalises case, accents, punctuation and `&`/`and`, then requires the
artist name to match. If several artists have the same normalised name, the
candidate with exactly the same capitalisation wins. This is what picks
`JENNIE` (BLACKPINK) over `Jennie` (Finnish artist) from Lidarr's lookup
results.

If an artist is not found, the sensor attribute `last_result.status` explains
why:

| Status | Meaning |
| --- | --- |
| `added` | Artist was added. |
| `exists` | Already in Lidarr, nothing changed. |
| `would_add` | Dry run: this is what would have been added. |
| `not_found` | No confident name match. Try the `First search result` strategy, or add the artist manually. |
| `ignored` | Matched the ignored-artist list. |
| `error` / `auth_error` | Lidarr could not be reached or rejected the key. Check the connection sensor and log. |
| `skipped` | Already handled in this or a previous session. |

`not_found` results are retried after 24 hours. `reset_history` clears the whole
cache and can be used after changing Lidarr's metadata or removing an artist
from Lidarr. Names reported as a collaboration (for example `A feat. B`) only
match if Lidarr has that exact artist name.

The integration does **not** download anything itself. It only creates the
artist in Lidarr. Whether albums are downloaded depends on your Lidarr profiles,
monitoring options, indexers and the optional immediate search.

### Media sources

**Android media session sensor**

The Companion App lists all active media sessions as separate attributes.
Configure the packages you want to read; YouTube Music is
`com.google.android.apps.youtube.music`, Spotify is `com.spotify.music`, YouTube
is `com.google.android.youtube`. The per-package `playback_state_<package>`
attribute is used, so a paused YouTube Music session does not block a playing
Spotify session.

**Any media_player entity**

Select a `media_player` entity (for example one from Spotify, Music Assistant,
Plex, Sonos, Chromecast or a TV) and the integration reads the standard
`media_artist`, `media_album_name` and `media_title` attributes while its state
is `playing` or `buffering`. Paused, idle, off and unavailable players are
ignored when **Only when playing** is enabled.

Each integration entry watches one source. To watch a second player as well, add
the integration again and select the other entity; both entries share the same
Lidarr defaults if you configure them the same way.

## Entities

| Entity | Description |
| --- | --- |
| `sensor.lidarr_media_sync_last_added_artist` | Artist most recently added. Attributes contain `last_added`, `last_result`, `pending_artist`, `seen_artists`, `dry_run`, `source_entity` and `packages`. |
| `binary_sensor.lidarr_media_sync_lidarr_connection` | On when the last Lidarr health check succeeded. |
| `switch.lidarr_media_sync_automatic_sync` | Turns automatic additions on or off. The manual `add_artist` service still works while paused. |

Entity IDs may differ if you renamed the integration or already had an entity
with the same name.

## Services

### `lidarr_media_sync.add_artist`

Add an artist manually through the same lookup pipeline. Ignores the pause
switch, the seen cache and the ignored-artist list.

```yaml
action: lidarr_media_sync.add_artist
data:
  artist: JENNIE
  album: Fallen Angel   # optional
```

### `lidarr_media_sync.sync_now`

Read the configured media source immediately and process the current artist,
bypassing the seen cache. Useful after changing options or for testing.

```yaml
action: lidarr_media_sync.sync_now
```

### `lidarr_media_sync.reset_history`

Forget which artists were seen. Previously `not_found` or `error` artists will
be looked up again.

```yaml
action: lidarr_media_sync.reset_history
```

All three services accept an optional `entry_id` when more than one instance is
configured, and return their result when called with `return_response: true`.

## Events

Every successful add fires `lidarr_media_sync_artist_added`:

```yaml
automation:
  - alias: Notify when Lidarr Media Sync adds an artist
    triggers:
      - trigger: event
        event_type: lidarr_media_sync_artist_added
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Added to Lidarr
          message: >-
            {{ trigger.event.data.artist }}
            {% if trigger.event.data.album %}— {{ trigger.event.data.album }}{% endif %}
```

Event data: `entry_id`, `artist`, `album`, `title`, `mbid`, `artist_id`, `package`,
`source` and `url`.

## How it works

1. Home Assistant fires a state event when the configured media source updates.
2. The integration reads the configured package attributes and ignores
   sessions that are not playing (unless that option is disabled).
3. The artist is normalised and checked against the seen cache and ignore list.
4. Lidarr's `/artist/lookup` is queried. Lookup results that are already in the
   library have a non-zero `id`, so no full library download is needed.
5. The best candidate is matched (see above).
6. If the artist is new, `POST /artist` is sent with the configured folder and
   profiles.
7. The cache, sensor and `lidarr_media_sync_artist_added` event are updated.

### Sensor update timing

The Companion App updates the media session sensor on its normal sensor
interval: every 15 minutes by default, or every minute with **Sensor Update
Frequency → Fast Always**. The sensor does not necessarily update on every
track change, so an artist may be added when the sensor next reports, not
instantly. Set the app's update frequency to **Fast Always** for the best
results. A confirmation delay cannot make a one-minute sensor more precise; it
only avoids adding artists from very short, already-stale updates.

`media_player` entities are updated by their own integration and usually emit a
state change as soon as the track changes, so those additions are prompt.

## Troubleshooting

**The integration was configured, but nothing happens**

- Check that the watched sensor really has `artist_<package>` attributes:
  **Developer tools → States**, select the sensor, and play something.
- For a `media_player`, check that it exposes `media_artist` and that its state
  is `playing` while music plays.
- Check the package name. YouTube Music is
  `com.google.android.apps.youtube.music`; Spotify is `com.spotify.music`; the
  normal YouTube app is `com.google.android.youtube`.
- Make sure the media session sensor is enabled in the Companion App and the app
  has notification access.
- Look at `last_result` on
  `sensor.lidarr_media_sync_last_added_artist`, or call
  `lidarr_media_sync.sync_now`.
- Try **Dry run** first to see what the integration would add.

**No match / wrong artist**

- Use the **First search result** strategy for names that Lidarr spells
  differently, or add the artist manually.
- Add recurring wrong matches to **Ignored artists**.
- Check the matched name in `last_result.matched_name`.

**Lidarr connection errors**

- The connection sensor goes off when the health check fails. Confirm the URL
  from Home Assistant's network namespace, not from your laptop.
- If Lidarr is behind a VPN container, use the host port that is actually
  published.
- A 401 means the API key is wrong; the integration starts a reauthentication
  flow automatically.

**"Already exists" appears in the log**

The artist was added between the lookup and the POST, or Lidarr knew it under a
different name. This is treated as success and remembered; no duplicate is
created.

Enable debug logging if needed:

```yaml
logger:
  logs:
    custom_components.lidarr_media_sync: debug
```

## Development

The integration is dependency-free (it uses Home Assistant's shared `aiohttp`
session). Tests use `pytest-homeassistant-custom-component`:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component aiohttp
.venv/bin/python -m pytest -q
```

The test suite covers media session parsing, `media_player` parsing, artist
matching, the Lidarr client payload, config/options flows, the end-to-end
add/exists/dry-run/pause paths, both source types, services and unload.

```
custom_components/lidarr_media_sync/
├── __init__.py          setup, services, config entry lifecycle
├── client.py            Lidarr v1 API client
├── config_flow.py       two-step setup, options and reauth flows
├── const.py
├── coordinator.py       Lidarr health polling
├── manager.py           sensor listener, matching, de-duplication, persistence
├── matching.py          name normalisation and candidate selection
├── media.py             companion sensor and media_player parsing
├── entity.py            shared device/entity base
├── sensor.py            last-added artist
├── binary_sensor.py     connection
├── switch.py            automatic sync pause switch
└── diagnostics.py
```

## Security notes

- The Lidarr API key is stored in Home Assistant's config entry storage and is
  redacted from diagnostics. It is never written to the sensor attributes or
  logs.
- The integration makes only LAN requests to the configured Lidarr URL.
- Adding an artist with `Monitor albums: All` and
  `Search for missing albums: true` can cause a large number of downloads. Start
  with monitoring off or use dry run when trying it out.
