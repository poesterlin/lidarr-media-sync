"""Artist name matching helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_PUNCTUATION = re.compile(r"[^0-9a-z]+")
_WHITESPACE = re.compile(r"\s+")
_AMPERSAND = re.compile(r"\s*&\s*")


def normalize_name(value: str) -> str:
    """Normalise an artist name for comparison.

    Case, accents, punctuation and ``&`` vs ``and`` should not prevent a
    match. Genuine differences such as "The Weeknd" vs "Weeknd" are kept.
    """
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = _AMPERSAND.sub(" and ", text)
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class ArtistCandidate:
    """A single result from Lidarr's artist lookup."""

    name: str
    mbid: str
    library_id: int | None = None
    disambiguation: str | None = None
    artist_type: str | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ArtistCandidate | None:
        mbid = data.get("foreignArtistId") or data.get("mbId")
        name = data.get("artistName")
        if not mbid or not name:
            return None
        library_id = data.get("id")
        return cls(
            name=str(name),
            mbid=str(mbid),
            library_id=int(library_id) if library_id else None,
            disambiguation=data.get("disambiguation") or None,
            artist_type=data.get("artistType") or None,
        )


def candidates_from_api(results: Iterable[Mapping[str, Any]]) -> list[ArtistCandidate]:
    """Convert raw Lidarr lookup results into candidates."""
    candidates = []
    for result in results:
        candidate = ArtistCandidate.from_api(result)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def choose_candidate(
    candidates: list[ArtistCandidate],
    query: str,
    strategy: str = "exact",
) -> ArtistCandidate | None:
    """Pick the best candidate for a now-playing artist name.

    ``exact`` only accepts a normalised exact name match and prefers the
    candidate whose capitalisation matches the source, which is what
    disambiguates e.g. "JENNIE" (BLACKPINK) from "Jennie" (Finnish artist).
    ``first`` trusts Lidarr's relevance order.
    """
    if not candidates:
        return None

    if strategy == "first":
        return candidates[0]

    target = normalize_name(query)
    if not target:
        return None

    matches = [
        candidate
        for candidate in candidates
        if normalize_name(candidate.name) == target
    ]
    if not matches:
        return None

    query_stripped = query.strip()
    same_case = [
        candidate for candidate in matches if candidate.name.strip() == query_stripped
    ]
    return (same_case or matches)[0]
