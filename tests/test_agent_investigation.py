"""Captured-source investigation contracts, using only synthetic temporary roots."""
from __future__ import annotations

import json

import pytest

from backend.agent import investigation as module
from backend.agent.investigation import Investigation
from backend.agent.workflow import AgentWorkflow
from backend.app.service import Service
from backend.app.store import Conflict
from test_ck3_service import installation


@pytest.fixture
def captured(tmp_path):
    originals = tmp_path / "originals"
    contents = {
        ("V", "common/character_interactions/allies.txt"): b"call_ally_interaction = { effect = { vanilla = yes } }\n",
        ("one", "descriptor.mod"): b'name="First mod"\n',
        ("one", "common/character_interactions/allies.txt"): b"call_ally_interaction = { effect = { vanilla = yes } }\n",
        ("two", "descriptor.mod"): b'name="Second mod"\n',
        ("two", "common/character_interactions/allies.txt"): b"call_ally_interaction = { effect = { call_friends_effect = yes } }\n",
        ("one", "common/scripted_effects/helpers.txt"): b"\xef\xbb\xbf# caf\xc3\xa9\r\ncall_friends_effect = { add_prestige = 5 }\r\n",
        ("one", "common/traits/public.txt"): b"root_trait = { parent = child_trait }\ndynamic_trait = { parent = $PARENT$ }\n",
        ("one", "common/traits/private.txt"): b"shared_trait = { parent = SECRET_PARENT }\n",
        ("two", "common/traits/public.txt"): b"child_trait = { congenital = yes }\nshared_trait = { parent = child_trait }\n",
        ("one", "common/traits/broken.txt"): b"broken_trait = { parent = child_trait\n",
        ("one", "custom/deferred.txt"): b"not_in_the_semantic_index = { preserved = yes }\n",
        ("one", "custom/unsupported.txt"): b"\xff\xfex\0=\0y\0",
        ("V", "common/character_interactions/_actions.info"): b"Synthetic documentation: calling allies is an action.\n",
        ("one", "gfx/image.dds"): b"DDS \0\xff\x81\0saved asset",
    }
    for (owner, relative), raw in contents.items():
        target = originals / owner / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    service = Service(tmp_path / "managed")
    workspace = service.create_workspace({"game_id": "ck3", "target_platform": "macos", "mode": "game",
        "name": "Synthetic investigation", "sources": [{"owner": owner, "path": str(originals / owner)}
                                                        for owner in ("V", "one", "two")]})
    try:
        scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
        workspace = service.store.get("workspace", workspace["id"])
        flow = AgentWorkflow(service)
        index_id = flow.index(workspace, {"scan_id": scan_id}, lambda *args: None)["index_id"]
        yield service, Investigation(service), workspace, index_id, contents
        assert {(owner, relative): (originals / owner / relative).read_bytes() for owner, relative in contents} == contents
    finally:
        service.close()


@pytest.fixture
def launcher_capture(tmp_path, request):
    originals = tmp_path / "originals"
    options, user = installation(originals, "macos")
    raw = (b'\xef\xbb\xbfname="First launcher mod"\r\npath="mod/one"\r\n'
           b'replace_path="common/traits"\r\nreplace_path="events"\r\n'
           b'dependencies={"Second launcher mod"}\r\n# caf\xc3\xa9 preserved\r\n')
    (user / "mod/one.mod").write_bytes(raw)
    # A payload can contain the same spelling and bytes as our public metadata
    # namespace. Neither source identity may replace the other.
    collision = user / "mod/one/@launcher/mod/one.mod"
    collision.parent.mkdir(parents=True)
    collision.write_bytes(raw)
    (user / "mod/disabled.mod").write_bytes(b'name="Unrelated disabled mod"\npath="mod/one"\n')
    (user / "mod/missing.mod").write_bytes(b'name="Missing enabled mod"\npath="mod/absent"\nreplace_path="history"\n')
    enabled = ["mod/one.mod", "mod/two.mod", "mod/missing.mod"]
    for number in range(getattr(request, "param", 0)):
        name = f"extra-{number}"
        traits = user / "mod" / name / "common/traits"
        traits.mkdir(parents=True)
        (traits / "shared.txt").write_bytes(b"clever = { diplomacy = 4 }\n")
        (user / "mod" / f"{name}.mod").write_text(f'name="Extra {number}"\npath="mod/{name}"\n')
        enabled.append(f"mod/{name}.mod")
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": enabled}))
    before = {str(path): path.read_bytes() for path in originals.rglob("*") if path.is_file()}
    service = Service(tmp_path / "managed")
    workspace = service.create_workspace({"name": "Captured launcher metadata", "game_id": "ck3",
                                         "target_platform": "macos", "mode": "game"})
    try:
        discovered = service._discover_ck3(workspace, options, lambda *args: None)
        service._import_ck3(workspace, {"discovery_id": discovered["discovery_id"]})
        workspace = service.store.get("workspace", workspace["id"])
        scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
        workspace = service.store.get("workspace", workspace["id"])
        index_id = AgentWorkflow(service).index(workspace, {"scan_id": scan_id}, lambda *args: None)["index_id"]
        yield service, Investigation(service), workspace, index_id, user, raw
        assert {str(path): path.read_bytes() for path in originals.rglob("*") if path.is_file()} == before
    finally:
        service.close()


def launcher_source(capture):
    _, api, workspace, index_id, *_ = capture
    result = api.search_sources(workspace["id"], index_id, "one.mod", kind="path", owner="ck3:mod/one.mod")
    return next(item for item in result["results"] if item["origin"] == "launcher_descriptor")


def source(captured, query, owner=None):
    _, api, workspace, index_id, _ = captured
    result = api.search_sources(workspace["id"], index_id, query, kind="path", owner=owner)
    assert result["total"] == 1
    return result["results"][0]


def test_search_follows_helpers_beyond_collisions_and_retains_byte_offsets(captured):
    _, api, workspace, index_id, contents = captured
    found = api.search_sources(workspace["id"], index_id, "call_friends_effect", kind="symbol")
    assert found["total"] == 1
    definition = found["results"][0]
    assert definition["target"] == "game/scripted_effect/call_friends_effect"
    helper = definition["occurrences"][0]
    raw = contents[helper["owner"], helper["path"]]
    part = api.read_source(workspace["id"], index_id, helper["source_id"], offset=4, limit=7)
    assert part["span"] == [4, 11] and part["next_offset"] == 11
    assert part["text"] == raw[4:11].decode("utf-8", errors="backslashreplace")
    assert part["freshness"]["kind"] == "saved_capture" and not part["freshness"]["live_files_rechecked"]
    mentions = api.search_sources(workspace["id"], index_id, "call_friends_effect")
    assert mentions["matches_on_this_page"] == 2
    assert mentions["total"] is None and mentions["coverage"]["gaps"]
    assert all(item["match_kind"] == "literal_text" for item in mentions["results"])


def test_text_search_cursor_exhaustion_never_pretends_a_page_is_complete(captured, monkeypatch):
    _, api, workspace, index_id, _ = captured
    monkeypatch.setattr(module, "MAX_SEARCH_FILES", 2)
    pages, matches, cursor = [], [], 0
    while True:
        page = api.search_sources(workspace["id"], index_id, "call_friends_effect", offset=cursor, limit=1)
        pages.append(page)
        matches.extend(page["results"])
        assert page["total"] is None
        assert page["coverage"]["searched_range"][1] - cursor <= 2
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > cursor
        cursor = page["next_offset"]
    assert len(pages) > 1 and len(matches) == 2
    assert len({item["source_id"] for item in matches}) == 2
    assert not any(page["coverage"]["all_eligible_sources_searched"] for page in pages)
    assert pages[-1]["coverage"]["search_exhausted"]


def test_read_preserved_unknown_text_and_shipped_docs_without_parsing_claim(captured):
    _, api, workspace, index_id, _ = captured
    for query in ("deferred.txt", ".info"):
        selected = source(captured, query)
        read = api.read_source(workspace["id"], index_id, selected["source_id"])
        assert read["status"] == "available"
        assert read["source"]["kind"] == "opaque"
        assert not read["freshness"]["live_files_rechecked"]
    binary = source(captured, ".dds")
    unsupported = api.read_source(workspace["id"], index_id, binary["source_id"])
    assert unsupported["status"] == "unavailable" and "text" not in unsupported
    encoded = source(captured, "unsupported.txt")
    unavailable = api.read_source(workspace["id"], index_id, encoded["source_id"])
    assert unavailable["status"] == "unavailable" and "text" not in unavailable


def test_references_preserve_dynamic_missing_and_malformed_uncertainty(captured):
    _, api, workspace, index_id, _ = captured
    literal = api.related_definitions(workspace["id"], index_id, "game/trait/root_trait")
    assert literal["total"] == 1
    assert literal["edges"][0]["target"] == "game/trait/child_trait"
    assert literal["edges"][0]["resolution_state"] == "candidate_present"
    assert literal["related_definitions"][0]["occurrences"]
    dynamic = api.related_definitions(workspace["id"], index_id, "game/trait/dynamic_trait")
    assert dynamic["edges"][0]["target"] is None and dynamic["edges"][0]["certainty"] == "dynamic"
    missing = api.related_definitions(workspace["id"], index_id, "game/trait/shared_trait")
    assert {edge["resolution_state"] for edge in missing["edges"]} == {"candidate_present", "missing_in_snapshot"}
    broken = source(captured, "broken.txt")
    read = api.read_source(workspace["id"], index_id, broken["source_id"])
    assert read["status"] == "available" and read["parse_diagnostics"]
    recovered = api.related_definitions(workspace["id"], index_id, "game/trait/broken_trait")
    assert recovered["edges"][0]["resolution_state"] == "source_unparsed"


def test_exclusions_apply_to_direct_sources_and_all_derived_contributors(captured):
    service, api, workspace, index_id, _ = captured
    private = source(captured, "private.txt")
    issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                 if item["target"] == "game/trait/shared_trait")
    service.store.put("configuration", {"id": "inference-policy", "policy": {"excluded_patterns": ["*/private.txt"]}})
    results = [api.read_source(workspace["id"], index_id, private["source_id"]),
               api.search_sources(workspace["id"], index_id, "SECRET_PARENT"),
               api.search_sources(workspace["id"], index_id, "shared_trait", kind="symbol"),
               api.related_definitions(workspace["id"], index_id, "game/trait/child_trait"),
               api.brief(workspace["id"], index_id, issue["id"])]
    assert results[0]["excluded"]
    assert results[1]["matches_on_this_page"] == results[2]["total"] == 0
    assert results[4]["excluded"]
    assert "SECRET_PARENT" not in json.dumps(results)
    assert all(edge["source"] != "game/trait/shared_trait" for edge in results[3]["edges"])


def test_source_ids_cannot_cross_workspaces_or_new_scan_generations(captured):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    other = service.create_workspace({"name": "Other", "mode": "game", "game_id": "ck3", "target_platform": "macos"})
    with pytest.raises(ValueError):
        api.read_source(other["id"], index_id, selected["source_id"])
    with pytest.raises(ValueError, match="does not belong"):
        api.read_source(workspace["id"], index_id, "../../session-token")
    service.store.put("workspace", {**workspace, "generation": "a-newer-scan"})
    with pytest.raises(Conflict, match="newer scan"):
        api.read_source(workspace["id"], index_id, selected["source_id"])


def test_a_repeated_capture_requires_its_own_source_ids(captured):
    service, api, workspace, index_id, _ = captured
    previous = source(captured, "helpers.txt")
    scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
    current = service.store.get("workspace", workspace["id"])
    next_index = AgentWorkflow(service).index(current, {"scan_id": scan_id}, lambda *args: None)["index_id"]
    with pytest.raises(ValueError, match="does not belong"):
        api.read_source(workspace["id"], next_index, previous["source_id"])
    found = api.search_sources(workspace["id"], next_index, "helpers.txt", kind="path")["results"][0]
    assert found["sha256"] == previous["sha256"] and found["source_id"] != previous["source_id"]


def test_derived_index_cannot_cross_changed_schema_context(captured):
    service, api, workspace, index_id, _ = captured
    index = service.store.get("agent_index", index_id)
    service.store.put("agent_index", {**index, "schema_hash": "a-different-schema"})
    with pytest.raises(Conflict, match="current tools"):
        api.search_sources(workspace["id"], index_id, "helpers", kind="path")


def test_missing_or_changed_captured_bytes_cannot_be_silently_used(captured):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    path = f"blobs/sha256/{selected['sha256'][:2]}/{selected['sha256']}"
    original = service.store.fs.read_bytes(path)
    service.store.fs.write_bytes(path, b"corrupted")
    with pytest.raises(Conflict, match="copy changed"):
        api.read_source(workspace["id"], index_id, selected["source_id"])
    service.store.fs.write_bytes(path, original)
    service.store.fs.resolve(path).unlink()
    absent = api.read_source(workspace["id"], index_id, selected["source_id"])
    assert absent["status"] == "unavailable" and "text" not in absent
    search = api.search_sources(workspace["id"], index_id, "call_friends_effect")
    assert search["total"] is None and search["coverage"]["gaps"]


def test_byte_budget_and_unsupported_encoding_keep_coverage_explicit(captured, monkeypatch):
    _, api, workspace, index_id, _ = captured
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 40)
    limited = api.search_sources(workspace["id"], index_id, "call_friends_effect")
    assert limited["coverage"]["gaps"] and limited["total"] is None
    assert not limited["coverage"]["all_eligible_sources_searched"]
    for limit in (0, 8193, True):
        with pytest.raises(ValueError):
            api.read_source(workspace["id"], index_id, "anything", limit=limit)
    with pytest.raises(ValueError):
        api.search_sources(workspace["id"], index_id, "", kind="text")


def test_issue_brief_carries_baseline_comparison_and_never_claims_game_success(captured):
    service, api, workspace, index_id, _ = captured
    issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                 if item["target"] == "game/character_interaction/call_ally_interaction")
    brief = api.brief(workspace["id"], index_id, issue["id"])
    assert brief["recommendation_state"] == "investigate_before_recommending"
    assert any("First mod" in fact and "matches" in fact for fact in brief["observations"])
    assert brief["inactive_choices_applicable"]
    assert not brief["actions"]["game_test"]["available"]
    assert not brief["actions"]["activation"]["available"]
    assert brief["contribution_count"] == 3
    issue["comparison"] = "identical"
    index = service.store.get("agent_index", index_id)
    index["issues"] = [issue if item["id"] == issue["id"] else item for item in index["issues"]]
    service.store.put("agent_index", index)
    equal = api.brief(workspace["id"], index_id, issue["id"])
    assert equal["recommendation_state"] == "no_difference_to_repair"
    assert not equal["inactive_choices_applicable"]


def test_launcher_descriptors_are_searchable_immutable_sources_with_distinct_identity(launcher_capture, monkeypatch):
    service, api, workspace, index_id, user, raw = launcher_capture
    descriptor = launcher_source(launcher_capture)
    assert descriptor["path"] == "@launcher/mod/one.mod"
    assert descriptor["source_id"].startswith("descriptor_source_")
    assert descriptor["payload_status"] == "available"
    assert descriptor["selection_scope"] == "enabled_in_captured_playset"
    same_paths = api.search_sources(workspace["id"], index_id, "@launcher/mod/one.mod", kind="path")
    assert same_paths["total"] == 2
    assert {item["origin"] for item in same_paths["results"]} == {"payload", "launcher_descriptor"}
    assert len({item["source_id"] for item in same_paths["results"]}) == 2
    mentions = api.search_sources(workspace["id"], index_id, 'replace_path="events"', owner="ck3:mod/one.mod")
    assert any(item["source_id"] == descriptor["source_id"] for item in mentions["results"])
    assert mentions["coverage"]["all_eligible_sources_searched"]
    # Later edits cannot alter this saved view. They are restored before the
    # fixture's no-write check, and no live inspection capability is available.
    target = user / "mod/one.mod"
    target.write_bytes(b'name="Externally edited after capture"\n')
    try:
        monkeypatch.setattr(service, "_current_scan", lambda *a, **k: pytest.fail("Saved inspection rechecked live files"))
        monkeypatch.setattr(service, "_discover_selection", lambda *a, **k: pytest.fail("Saved inspection read launcher state"))
        read = api.read_source(workspace["id"], index_id, descriptor["source_id"])
        assert read["text"].encode("utf-8") == raw and read["span"] == [0, len(raw)]
        assert not read["freshness"]["live_files_rechecked"]
        part = api.read_source(workspace["id"], index_id, descriptor["source_id"], offset=3, limit=11)
        assert part["text"].encode("utf-8") == raw[3:14] and part["next_offset"] == 14
        issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                     if item["target"] == "game/trait/clever")
        brief = api.brief(workspace["id"], index_id, issue["id"])
        assert brief["launcher_descriptor_count"] == 2 and not brief["launcher_descriptors_truncated"]
        assert descriptor in brief["launcher_descriptors"]
        public = json.dumps([same_paths, mentions, read, part, brief])
        assert "source_path" not in public and str(user) not in public and "bytes_base64" not in public
    finally:
        target.write_bytes(raw)


def test_launcher_metadata_excludes_disabled_mods_and_marks_missing_enabled_payloads(launcher_capture):
    service, api, workspace, index_id, *_ = launcher_capture
    scan = service.store.get("scan", workspace["generation"])
    assert any(item["owner"] == "ck3:mod/disabled.mod" for item in scan["package_metadata"])
    disabled = api.search_sources(workspace["id"], index_id, "disabled.mod", kind="path")
    assert disabled["total"] == 0
    assert api.search_sources(workspace["id"], index_id, "Unrelated disabled mod")["matches_on_this_page"] == 0
    missing = api.search_sources(workspace["id"], index_id, "missing.mod", kind="path")
    assert missing["total"] == 1
    descriptor = missing["results"][0]
    assert descriptor["payload_status"] == "unavailable" and not descriptor["active"]
    assert descriptor["selection_scope"] == "enabled_in_captured_playset"
    read = api.read_source(workspace["id"], index_id, descriptor["source_id"])
    assert read["status"] == "available" and 'replace_path="history"' in read["text"]


@pytest.mark.parametrize("launcher_capture", [22], indirect=True)
def test_issue_brief_keeps_large_descriptor_sets_bounded(launcher_capture):
    service, api, workspace, index_id, *_ = launcher_capture
    issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                 if item["target"] == "game/trait/clever")
    brief = api.brief(workspace["id"], index_id, issue["id"])
    assert brief["launcher_descriptor_count"] == 24
    assert len(brief["launcher_descriptors"]) == 20 and brief["launcher_descriptors_truncated"]
    assert all(item["origin"] == "launcher_descriptor" for item in brief["launcher_descriptors"])


@pytest.mark.parametrize("pattern", ["mod/one.mod", "@launcher/mod/one.mod"])
def test_launcher_descriptor_exclusions_cover_original_and_displayed_paths(launcher_capture, pattern):
    service, api, workspace, index_id, *_ = launcher_capture
    descriptor = launcher_source(launcher_capture)
    service.store.put("configuration", {"id": "inference-policy", "policy": {"excluded_patterns": [pattern]}})
    assert api.read_source(workspace["id"], index_id, descriptor["source_id"])["excluded"]
    found = api.search_sources(workspace["id"], index_id, "one.mod", kind="path")
    assert descriptor["source_id"] not in {item["source_id"] for item in found["results"]}
    text = api.search_sources(workspace["id"], index_id, "replace_path", owner="ck3:mod/one.mod")
    assert descriptor["source_id"] not in {item["source_id"] for item in text["results"]}
    issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                 if item["target"] == "game/trait/clever")
    brief = api.brief(workspace["id"], index_id, issue["id"])
    assert brief["launcher_descriptor_count"] == 1
    assert all(item["source_id"] != descriptor["source_id"] for item in brief["launcher_descriptors"])


def test_launcher_descriptor_missing_corrupt_and_wrong_size_are_not_exposed(launcher_capture):
    service, api, workspace, index_id, _, raw = launcher_capture
    descriptor = launcher_source(launcher_capture)
    blob = f"blobs/sha256/{descriptor['sha256'][:2]}/{descriptor['sha256']}"
    service.store.fs.write_bytes(blob, raw[:-1] + b"!")
    with pytest.raises(Conflict, match="copy changed"):
        api.read_source(workspace["id"], index_id, descriptor["source_id"])
    service.store.fs.write_bytes(blob, raw + b"extra bytes")
    with pytest.raises(Conflict, match="copy changed"):
        api.read_source(workspace["id"], index_id, descriptor["source_id"])
    service.store.fs.resolve(blob).unlink()
    missing = api.read_source(workspace["id"], index_id, descriptor["source_id"])
    assert missing["status"] == "unavailable" and "text" not in missing
    search = api.search_sources(workspace["id"], index_id, "replace_path")
    assert search["total"] is None
    assert descriptor["source_id"] in {gap["source_id"] for gap in search["coverage"]["gaps"]}


@pytest.mark.parametrize("mutation", ["foreign_discovery", "unmatched_descriptor", "absolute_descriptor_path", "configuration"])
def test_launcher_descriptor_access_requires_matching_scan_and_discovery(launcher_capture, mutation):
    service, api, workspace, index_id, *_ = launcher_capture
    descriptor = launcher_source(launcher_capture)
    scan = service.store.get("scan", workspace["generation"])
    discovery = service.store.get("discovery", scan["discovery_id"])
    if mutation == "foreign_discovery":
        service.store.put("discovery", {**discovery, "workspace_id": "a-different-workspace"})
    elif mutation == "configuration":
        service.store.put("discovery", {**discovery, "configuration_hash": "a-different-selection"})
    else:
        scan["package_metadata"][0]["descriptor_path" if mutation == "absolute_descriptor_path" else "sha256"] = (
            "/private/secret.mod" if mutation == "absolute_descriptor_path" else "a" * 64)
        service.store.put("scan", scan)
    with pytest.raises((ValueError, Conflict)):
        api.read_source(workspace["id"], index_id, descriptor["source_id"])
