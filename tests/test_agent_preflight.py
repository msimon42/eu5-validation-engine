"""Read-only preflight contracts on disposable Mac/Windows-shaped layouts."""
import json
from pathlib import Path

import pytest

from backend.agent.context import AssistantContext
from backend.agent.preflight import (
    Preflight, briefing_preflight, candidate_search_summary, version_preference, version_relation,
)
from backend.app.service import Service
from backend.app.store import Conflict
from test_agent_context import finish
from test_ck3_service import installation


def missing_fixture(tmp_path, platform="macos", *, registration=True):
    options, user = installation(tmp_path / "sources", platform)
    registry = "mod/ugc_12345.mod"
    if registration:
        (user / registry).write_text('name="Lost mod"\npath="mod/absent"\nremote_file_id="12345"\nsupported_version="1.18.*"\n')
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": ["mod/one.mod", "mod/two.mod", registry]}))
    library = tmp_path / "sources" / "Custom Steam"
    payload = library / "steamapps/workshop/content/1158310/12345"
    (payload / "common/traits").mkdir(parents=True)
    (payload / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="12345"\n')
    (payload / "common/traits/extra.txt").write_text("found_trait = { diplomacy = 2 }\n")
    steam = Path(options["steam_roots"][0])
    (steam / "steamapps/libraryfolders.vdf").write_text(f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}')
    return options, user, payload


def context_for(service, options):
    context = AssistantContext(service).get(locations=options)
    # The real context hook is owned by the integration task; this also keeps
    # the preflight tests usable independently of that integration.
    discovery = service._discover_selection(context["options"])
    return service.store.put("agent_context", {**context, "preflight": briefing_preflight(discovery)})


@pytest.mark.parametrize("platform", ["macos", "windows"])
@pytest.mark.parametrize("registration", [True, False])
def test_custom_library_missing_candidate_is_not_loaded_and_search_reuses_receipt(tmp_path, platform, registration, monkeypatch):
    options, _, payload = missing_fixture(tmp_path, platform, registration=registration)
    originals = {str(p): p.read_bytes() for p in (tmp_path / "sources").rglob("*") if p.is_file()}
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        original_workspaces = service.store.list("workspace")
        api = Preflight(service)
        result = api.find_missing_mod_candidates(context["id"])
        assert result["total"] == 1 and not result["reused"]
        row = result["mods"][0]
        assert row["state"] == "candidates_found" and not row["available_at_registered_location"]
        candidate = row["candidates"][0]
        assert candidate["path"] == str(payload) and candidate["inspectable"]
        assert service.store.get("agent_context", context["id"])["source_status"]["missing_enabled_mods"]
        assert not service.store.list("scan") and service.store.list("workspace") == original_workspaces
        monkeypatch.setattr(api, "_search", lambda *a: pytest.fail("Repeated a saved directory search"))
        assert api.find_missing_mod_candidates(context["id"])["reused"]
        summary = candidate_search_summary(service.store, context)
        assert summary["mods_with_candidates"] == 1
        assert {str(p): p.read_bytes() for p in (tmp_path / "sources").rglob("*") if p.is_file()} == originals
    finally:
        service.close()


def test_alternative_candidate_inspection_is_separate_and_preserves_missing_registration(tmp_path):
    options, user, payload = missing_fixture(tmp_path, registration=False)
    settings = Path(options["steam_roots"][0]) / "steamapps/common/Crusader Kings III/launcher/launcher-settings.json"
    settings.write_text(json.dumps({**json.loads(settings.read_text()), "rawVersion": "1.19.0.4"}))
    (payload / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="12345"\nsupported_version="1.19.*"\n')
    selection = json.loads((user / "dlc_load.json").read_text())
    selection["enabled_mods"].append("mod/ugc_67890.mod")
    (user / "dlc_load.json").write_text(json.dumps(selection))
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        original = finish(service, AssistantContext(service).request_check(context["id"]))
        api = Preflight(service)
        candidates = api.find_missing_mod_candidates(context["id"])
        candidate = candidates["mods"][0]["candidates"][0]
        alternative = api.inspect_mod_candidate(context["id"], candidate["id"])
        result = finish(service, alternative)
        assert result["workspace_id"] != original["workspace_id"]
        workspace = service.store.get("workspace", result["workspace_id"])
        assert workspace["inspection_scope"]["kind"] == "alternative_candidate"
        assert not workspace["discovery_complete"] and "ck3:mod/ugc_12345.mod" in workspace["default_playset"]
        assert [mod["owner"] for mod in workspace["inspection_missing_mods"]] == ["ck3:mod/ugc_67890.mod"]
        assert not alternative["launcher_changed"] and alternative["game_runs"] == 0
        current = AssistantContext(service).get(locations=options)
        assert current["workspace_id"] == original["workspace_id"]
        assert current["source_status"]["missing_enabled_mods"]
        resumed = AssistantContext(service).get(selection="resume", locations=options)
        assert resumed["workspace_id"] == original["workspace_id"]
        selected_alternative = AssistantContext(service).get(selection="resume", workspace_id=result["workspace_id"])
        assert selected_alternative["workspace_id"] == result["workspace_id"]
        assert selected_alternative["inspection_scope"]["kind"] == "alternative_candidate"
        assert selected_alternative["source_status"]["missing_enabled_mods_total"] == 1
        saved_alternative = service.store.get("agent_context", selected_alternative["id"])
        versions = saved_alternative["preflight"]["versions"]
        assert versions["game_version"] == "1.19.0.4"
        found_version = next(mod for mod in versions["mods"] if mod["owner"] == "ck3:mod/ugc_12345.mod")
        assert found_version["relation"] == "matches_declaration"
        assert found_version["origin"] == "player_selected_alternative"
        alternate_search = api.find_missing_mod_candidates(selected_alternative["id"])
        assert alternate_search["total"] == 1
        from backend.agent.reviews import ReviewWorkflow
        report = ReviewWorkflow(service).get_investigation_report(result["workspace_id"], result["index_id"])
        assert report["missing_mod_count"] == 1
        assert "1 enabled mods were unavailable" in report["narrative"]
    finally:
        service.close()


def test_candidate_tampering_and_context_mismatch_fail_before_workspace_creation(tmp_path):
    options, _, payload = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        original_workspaces = service.store.list("workspace")
        api = Preflight(service)
        candidate = api.find_missing_mod_candidates(context["id"])["mods"][0]["candidates"][0]
        other = context_for(service, options)
        with pytest.raises(Conflict, match="another selection"):
            api.inspect_mod_candidate(other["id"], candidate["id"])
        (payload / "descriptor.mod").write_text('name="Changed"\nremote_file_id="12345"\n')
        with pytest.raises(Conflict, match="candidate changed"):
            api.inspect_mod_candidate(context["id"], candidate["id"])
        assert service.store.list("workspace") == original_workspaces
    finally:
        service.close()


def test_conflicting_ids_name_only_and_archive_candidates_are_not_inspectable(tmp_path):
    options, user, payload = missing_fixture(tmp_path)
    (payload / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="99999"\n')
    suggestion = user / "mod" / "same name"
    suggestion.mkdir()
    (suggestion / "descriptor.mod").write_text('name="Lost mod"\n')
    archived = user / "mod" / "archive"
    archived.mkdir()
    (archived / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="12345"\narchive="pack.zip"\n')
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        api = Preflight(service)
        candidates = api.find_missing_mod_candidates(context["id"])["mods"][0]["candidates"]
        assert {c["match"] for c in candidates} == {"name_only_suggestion", "conflicting_identity", "matching_workshop_identity"}
        assert all(not c["inspectable"] for c in candidates)
        for candidate in candidates:
            with pytest.raises(ValueError, match="unambiguous supported"):
                api.inspect_mod_candidate(context["id"], candidate["id"])
    finally:
        service.close()


def test_duplicate_candidates_and_boundaries_are_reported(tmp_path, monkeypatch):
    options, user, _ = missing_fixture(tmp_path)
    second = user / "mod/duplicate"
    second.mkdir()
    (second / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="12345"\n')
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "descriptor.mod").write_text('name="Lost mod"\nremote_file_id="12345"\n')
    (user / "mod/link").symlink_to(outside, target_is_directory=True)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        api = Preflight(service)
        row = api.find_missing_mod_candidates(context["id"])["mods"][0]
        assert row["ambiguous"] and len(row["candidates"]) == 2
        assert all(str(outside) != c["path"] for c in row["candidates"])
        monkeypatch.setattr("backend.agent.preflight.MAX_DIRECTORIES", 1)
        bounded = api.find_missing_mod_candidates(context_for(service, options)["id"])
        assert not bounded["coverage"]["complete"]
        assert any(g["reason"] == "directory_budget" for g in bounded["coverage"]["gaps"])
    finally:
        service.close()


@pytest.mark.parametrize("version,declarations,relation", [
    ("1.19.0.4", ["1.19.*"], "matches_declaration"),
    ("1.19.0.4", ["1.18.*"], "version_question"),
    ("1.19.0.4", ["1.19"], "version_question"),
    ("1.19.0.4", ["1.19.0.4"], "matches_declaration"),
    ("1.19.0.4", [], "unknown"), ("beta", ["1.19.*"], "unknown"),
    ("1.19.0.4", ["1.19.*", "1.18.*"], "unknown"),
    ("1.19.0.4", ["latest"], "unknown"), ("1.19.0.4", [["1.19"]], "unknown"),
])
def test_version_comparisons_are_narrow(version, declarations, relation):
    assert version_relation(version, declarations) == relation


def test_preferences_persist_without_creating_approval(tmp_path):
    options, _, _ = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        assert version_preference(service.store, context)["preference"] == "undecided"
        Preflight(service).set_version_preference(context["id"], "preserve_current")
        new_context = context_for(service, options)
        assert version_preference(service.store, new_context)["preference"] == "preserve_current"
        assert not service.store.list("agent_question") and not service.store.list("decision")
        with pytest.raises(ValueError):
            Preflight(service).set_version_preference(context["id"], "approve_all")
    finally:
        service.close()


def test_unknown_preflight_version_and_incomplete_locations_are_explicit(tmp_path):
    options, _, payload = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        api = Preflight(service)
        future = service.store.put("agent_context", {**context, "preflight": {**context["preflight"], "version": "future"}})
        with pytest.raises(Conflict, match="unsupported version"):
            api.find_missing_mod_candidates(future["id"])
        context = context_for(service, options)
        (payload / "descriptor.mod").unlink()
        result = api.find_missing_mod_candidates(context["id"])
        assert result["mods"][0]["state"] == "search_incomplete"
        assert not result["coverage"]["complete"]
        assert any(g["reason"] == "payload_descriptor_missing" for g in result["coverage"]["gaps"])
    finally:
        service.close()


def exclude_payload_descriptors(service):
    policy = {key: value for key, value in service.inference_policy().items() if key != "key_configured"}
    service.store.put("configuration", {"id": "inference-policy", "policy": {**policy, "excluded_patterns": ["descriptor.mod"]}})


def test_search_policy_change_during_descriptor_read_returns_no_results_or_receipt(tmp_path, monkeypatch):
    from backend.agent import preflight
    options, _, _ = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        read = preflight.read_source_bytes

        def changing_read(*args, **kwargs):
            raw = read(*args, **kwargs)
            exclude_payload_descriptors(service)
            return raw

        monkeypatch.setattr(preflight, "read_source_bytes", changing_read)
        with pytest.raises(Conflict, match="source policy changed"):
            Preflight(service).find_missing_mod_candidates(context["id"])
        assert not service.store.list("agent_candidate_search")
    finally:
        service.close()


def test_cached_search_policy_change_during_load_returns_no_results(tmp_path, monkeypatch):
    options, _, _ = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        api = Preflight(service)
        api.find_missing_mod_candidates(context["id"])
        get = service.store.get

        def changing_get(kind, identifier):
            record = get(kind, identifier)
            if kind == "agent_candidate_search":
                exclude_payload_descriptors(service)
            return record

        monkeypatch.setattr(service.store, "get", changing_get)
        with pytest.raises(Conflict, match="source policy changed"):
            api.find_missing_mod_candidates(context["id"])
    finally:
        service.close()


@pytest.mark.parametrize("stage", ["read", "context"])
def test_candidate_policy_change_during_inspection_never_queues_a_check(tmp_path, monkeypatch, stage):
    from backend.agent import preflight
    options, _, _ = missing_fixture(tmp_path)
    service = Service(tmp_path / "managed")
    try:
        context = context_for(service, options)
        api = Preflight(service)
        candidate = api.find_missing_mod_candidates(context["id"])["mods"][0]["candidates"][0]
        read = preflight.read_source_bytes
        get_context = AssistantContext.get

        def changing_read(*args, **kwargs):
            raw = read(*args, **kwargs)
            exclude_payload_descriptors(service)
            return raw

        def changing_context(*args, **kwargs):
            result = get_context(*args, **kwargs)
            exclude_payload_descriptors(service)
            return result

        if stage == "read":
            monkeypatch.setattr(preflight, "read_source_bytes", changing_read)
        else:
            monkeypatch.setattr(AssistantContext, "get", changing_context)
        with pytest.raises(Conflict, match="source policy changed"):
            api.inspect_mod_candidate(context["id"], candidate["id"])
        assert not service.store.list("job")
    finally:
        service.close()
