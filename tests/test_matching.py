"""Tests for artist candidate matching."""

from __future__ import annotations

from custom_components.lidarr_media_sync.matching import (
    ArtistCandidate,
    candidates_from_api,
    choose_candidate,
    normalize_name,
)


def _candidate(name: str, mbid: str, **kwargs) -> ArtistCandidate:
    return ArtistCandidate(name=name, mbid=mbid, **kwargs)


def test_normalize_name_ignores_case_accents_and_punctuation():
    assert normalize_name("Beyoncé") == normalize_name("BEYONCE")
    assert normalize_name("AC/DC") == normalize_name("AC DC")
    assert normalize_name("Simon & Garfunkel") == normalize_name("Simon and Garfunkel")
    assert normalize_name("  The   Weeknd ") == normalize_name("the weeknd")


def test_prefers_exact_case_match_for_ambiguous_names():
    candidates = [
        _candidate("Jennie", "finnish", disambiguation="Finnish artist"),
        _candidate("JENNIE", "blackpink", disambiguation="BLACKPINK"),
        _candidate("Jennie Löfgren", "lofgren"),
    ]
    chosen = choose_candidate(candidates, "JENNIE", "exact")
    assert chosen is not None
    assert chosen.mbid == "blackpink"


def test_exact_match_ignores_case_when_only_one_candidate():
    candidates = [_candidate("jennie", "lower")]
    chosen = choose_candidate(candidates, "JENNIE", "exact")
    assert chosen is not None
    assert chosen.mbid == "lower"


def test_exact_strategy_rejects_fuzzy_match():
    candidates = [_candidate("Jennie Kim", "kim")]
    assert choose_candidate(candidates, "JENNIE", "exact") is None


def test_first_strategy_trusts_lidarr_order():
    candidates = [_candidate("Jennie Kim", "kim"), _candidate("JENNIE", "blackpink")]
    chosen = choose_candidate(candidates, "JENNIE", "first")
    assert chosen is not None
    assert chosen.mbid == "kim"


def test_empty_results():
    assert choose_candidate([], "JENNIE") is None
    assert choose_candidate([_candidate("JENNIE", "x")], "   ") is None


def test_candidates_from_api_reads_library_id():
    candidates = candidates_from_api(
        [
            {
                "id": 337,
                "artistName": "Dua Lipa",
                "foreignArtistId": "mbid-1",
                "disambiguation": None,
                "artistType": "Person",
            },
            {
                "artistName": "Not In Library",
                "foreignArtistId": "mbid-2",
            },
            {"artistName": "Missing MBID"},
        ]
    )
    assert len(candidates) == 2
    assert candidates[0].library_id == 337
    assert candidates[1].library_id is None
