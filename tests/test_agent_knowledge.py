"""Bundled-reference contracts; these tests never read a user's game installation."""
import json

import pytest

from backend.agent.knowledge import knowledge_manifest, read_knowledge, search_knowledge


def test_complete_search_pagination_and_topic_filtering():
    all_entries = []
    page = search_knowledge(limit=3)
    total = page["total"]
    while True:
        all_entries.extend(item["id"] for item in page["entries"])
        if page["next_offset"] is None:
            break
        page = search_knowledge(offset=page["next_offset"], limit=3)
        assert page["total"] == total
    assert len(all_entries) == len(set(all_entries)) == total
    assert total == knowledge_manifest()["entry_count"]
    limited = search_knowledge(topic="language", limit=20)
    assert limited["total"] > 1
    assert all(entry["topic"] == "language" for entry in limited["entries"])


@pytest.mark.parametrize("query,expected", [
    ("on_action", "on-actions"),
    ("call_ally_interaction", "character-interactions"),
    ("last mod wins", "files-and-definitions"),
    ("dynamic references", "helpers-and-dynamic-references"),
    ("save compatibility", "updates-and-saves"),
    ("hardcoded", "evidence-and-limits"),
    ("reader_export", "reader-variables"),
])
def test_realistic_investigation_topics_find_the_relevant_reference(query, expected):
    result = search_knowledge(query)
    assert result["total"]
    assert expected in [entry["id"] for entry in result["entries"]]


def test_version_label_match_never_grants_game_or_repair_authority():
    matched = read_knowledge("on-actions", game_version="1.19.0.4")
    other = read_knowledge("on-actions", game_version="99.0.0")
    assert matched["applicability"]["status"] == "matching_label_only"
    assert other["applicability"]["status"] == "different_or_unrecognized_label"
    for reference in (matched, other):
        assert not reference["applicability"]["runtime_qualified"]
        assert not reference["grants_repair_capability"]
        assert reference["game_observations"] == []
        assert {claim["basis"] for claim in reference["claims"]} >= {"documented", "unknown"}
        for source in reference["sources"]:
            assert not source["executed_game_observation"]
            assert len(source["sha256"]) == 64


def test_research_suggestions_never_include_a_private_search_query():
    private_query = "/Users/example/private_campaign/secret-character-save.ck3"
    result = search_knowledge(private_query)
    assert result["total"] == 0
    assert private_query not in json.dumps(result)
    assert result["research"]["allowed"]
    assert not result["research"]["private_content_in_queries"]
    assert not read_knowledge("history")["research"]["promotes_game_evidence"]


def test_read_returns_independent_data_and_never_treats_ids_as_paths():
    first = read_knowledge("events")
    first["claims"][0]["text"] = "invented"
    first["sources"][0]["sha256"] = "invented"
    second = read_knowledge("events")
    assert second["claims"][0]["text"] != "invented"
    assert second["sources"][0]["sha256"] != "invented"
    with pytest.raises(ValueError, match="does not exist"):
        read_knowledge("../../private-file")


@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": 21}, {"limit": True}, {"offset": -1},
    {"offset": True}, {"query": "x" * 501}, {"query": "line\nbreak"},
    {"game_version": "x" * 101}, {"topic": ["language"]},
])
def test_invalid_queries_are_rejected_before_lookup(kwargs):
    with pytest.raises(ValueError):
        search_knowledge(**kwargs)


def test_external_sources_are_pinned_and_separate_from_shipped_documentation():
    reference = read_knowledge("scopes-and-chains")
    external = [source for source in reference["sources"] if source["kind"] == "pinned_specialist_source"]
    local = [source for source in reference["sources"] if source["kind"] == "installed_game_documentation"]
    assert external and local
    assert all(len(source["revision"]) == 40 and source["revision"] in source["url"] for source in external)
    assert all(source["game_version_label"] is None for source in external)
    assert all(source["relative_path"].startswith("game/") and "url" not in source for source in local)
