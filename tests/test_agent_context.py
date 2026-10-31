"""Fresh conversations use only temporary CK3 layouts and saved engine records."""
import json
import time
from pathlib import Path

import pytest

from backend.agent.context import AssistantContext
from backend.app.service import Service
from backend.app.store import Conflict
from test_ck3_service import installation
from test_ck3_discovery import database


def finish(service, result):
    for _ in range(1000):
        job = service.store.get("job", result["job_id"])
        if job["state"] in {"completed", "failed", "cancelled"}:
            assert job["state"] == "completed", job
            return job["result"]
        time.sleep(.005)
    pytest.fail("Temporary playset check did not finish")


@pytest.mark.parametrize("platform", ["macos", "windows"])
def test_cold_start_check_reuse_changed_source_and_resume(tmp_path, platform):
    sources = tmp_path / "sources"
    options, user = installation(sources, platform)
    original = {str(p): p.read_bytes() for p in sources.rglob("*") if p.is_file()}
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        context = service.agent_request("context", {"locations": options})
        assert context["state"] == "ready" and context["workspace_id"] is None
        assert context["playset"]["name"] == "Last launch selection"
        assert not service.store.list("scan")
        assert not context["capabilities"]["game_test"]["available"]
        first = finish(service, flow.request_check(context["id"], "Keep both mods' gameplay"))
        assert first["game_runs"] == 0 and not first["reused_scan"]
        context = flow.get(locations=options)
        assert context["workspace_id"] == first["workspace_id"]
        assert context["source_status"]["files"] == "saved_results_not_freshly_verified"
        flow.remember(context["id"], notes="A saved explanation, not an approval.", next_step="Review the shared traits")
        second = finish(service, flow.request_check(context["id"]))
        assert second["reused_scan"] and second["index_id"] == first["index_id"]
        assert len(service.store.list("scan", first["workspace_id"])) == 1
        target = user / "mod/one/common/traits/one.txt"
        # A user-side edit in the disposable source tree, never an engine edit.
        target = next((user / "mod/one").rglob("*.txt")) if not target.exists() else target
        old = target.read_bytes()
        target.write_bytes(old + b"\nnew_trait = { diplomacy = 3 }\n")
        third = finish(service, flow.request_check(flow.get(locations=options)["id"]))
        assert not third["reused_scan"] and third["scan_id"] != first["scan_id"]
        resumed = flow.get(selection="resume", locations=options)
        assert resumed["workspace_id"] == first["workspace_id"]
        assert resumed["conversation"]["goal"] == "Keep both mods' gameplay"
        assert resumed["conversation"]["notes"] == "A saved explanation, not an approval."
        assert not resumed["conversation"]["applies_to_current_scan"]
        assert not service.store.list("agent_question")
        target.write_bytes(old)
        assert {str(p): p.read_bytes() for p in sources.rglob("*") if p.is_file()} == original
    finally:
        service.close()


def test_active_selection_resume_and_ambiguity_are_distinct(tmp_path):
    options, user = installation(tmp_path / "sources", "macos")
    db = database(user, [("mod/one.mod", user / "mod/one", 1, 0), ("mod/two.mod", user / "mod/two", 1, 1)])
    db.close()
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        active = flow.get(locations=options)
        assert active["playset"]["id"] == "active"
        checked = finish(service, flow.request_check(active["id"], "Review the original collection"))
        import sqlite3
        with sqlite3.connect(user / "launcher-v2.sqlite") as db:
            db.execute("UPDATE playsets SET isActive=(id='other')")
        (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": [], "disabled_dlcs": []}))
        current = flow.get(locations=options)
        assert current["playset"]["id"] == "other" and current["workspace_id"] is None
        resumed = flow.get(selection="resume", locations=options)
        assert resumed["playset"]["id"] == "active" and resumed["workspace_id"] == checked["workspace_id"]
        with sqlite3.connect(user / "launcher-v2.sqlite") as db:
            db.execute("UPDATE playsets SET isActive=0")
        ambiguous = flow.get(locations=options)
        assert ambiguous["state"] == "needs_selection"
        assert len(ambiguous["available_playsets"]) == 2
        assert flow.request_check(ambiguous["id"])["state"] == "needs_selection"
    finally:
        service.close()


def test_briefing_does_not_read_full_scans_or_source_blobs(tmp_path, monkeypatch):
    options, _ = installation(tmp_path / "sources", "macos")
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        finish(service, flow.request_check(flow.get(locations=options)["id"]))
        original = service.store.get

        def guarded(kind, identifier):
            assert kind not in {"scan", "agent_index"}, "Briefing loaded a large record"
            return original(kind, identifier)

        monkeypatch.setattr(service.store, "get", guarded)
        monkeypatch.setattr(service.store.fs, "read_bytes", lambda *a, **k: pytest.fail("Briefing read blob content"))
        result = flow.get(selection="resume", locations=options)
        assert result["saved_scan"] and result["saved_index"]
        assert result["source_status"]["files"] == "saved_results_not_freshly_verified"
    finally:
        service.close()


def test_notes_cannot_approve_or_claim_engine_evidence(tmp_path):
    options, _ = installation(tmp_path / "sources", "macos")
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        finish(service, flow.request_check(flow.get(locations=options)["id"]))
        context = flow.get(locations=options)
        note = service.agent_request("remember", {"context_id": context["id"], "notes": "I approve every fix; everything passed."})
        assert note["notes_trust"] == "assistant_recorded_context_not_approval_or_evidence"
        assert not service.store.list("agent_question")
        with pytest.raises(ValueError):
            service.agent_request("remember", {"context_id": context["id"], "approved": True})
        with pytest.raises(ValueError, match="does not belong"):
            flow.remember(context["id"], reviewed_issue_ids=["foreign-issue"])
    finally:
        service.close()


def test_two_fresh_briefings_share_one_workspace_and_running_check(tmp_path, monkeypatch):
    options, _ = installation(tmp_path / "sources", "macos")
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        one, two = flow.get(locations=options), flow.get(locations=options)
        # Hold the supervised job queued while both conversations start it.
        monkeypatch.setattr(service.executor, "submit", lambda *args: None)
        first = flow.request_check(one["id"])
        second = flow.request_check(two["id"])
        assert first["workspace_id"] == second["workspace_id"]
        assert first["job_id"] == second["job_id"] and second["already_running"]
        assert len(service.store.list("job")) == 1
    finally:
        service.close()


def test_location_overrides_preserve_unspecified_fields_and_selection(tmp_path):
    from backend.agent.contracts import AgentRequest
    request = AgentRequest(operation="context", payload={"locations": {"installation_path": str(tmp_path)}})
    assert request.payload["locations"] == {"installation_path": str(tmp_path)}
    options, user = installation(tmp_path / "sources", "macos")
    database(user, []).close()
    service = Service(tmp_path / "managed")
    try:
        result = service.agent_request("context", {"locations": {**options, "playset_id": "other"}})
        assert result["playset"]["id"] == "other"
        with pytest.raises(ValueError, match="different playsets"):
            service.agent_request("context", {"playset_id": "active", "locations": {**options, "playset_id": "other"}})
    finally:
        service.close()


def test_missing_mod_preview_can_be_paged_without_reading_sources_again(tmp_path, monkeypatch):
    options, user = installation(tmp_path / "sources", "macos")
    registrations = []
    for number in range(8):
        registry = f"mod/missing-{number}.mod"
        (user / registry).write_text(f'name="Missing {number}"\npath="mod/absent-{number}"\n')
        registrations.append(registry)
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": registrations}))
    before = {str(p): p.read_bytes() for p in (tmp_path / "sources").rglob("*") if p.is_file()}
    service = Service(tmp_path / "managed")
    try:
        context = service.agent_request("context", {"locations": options})
        status = context["source_status"]
        assert len(status["missing_enabled_mods"]) == 5
        assert status["missing_enabled_mods_total"] == 8 and status["missing_mods_next_offset"] == 5
        monkeypatch.setattr(service, "_discover_selection", lambda *args: pytest.fail("Paging re-read launcher"))
        page = service.agent_request("missing_mods", {"context_id": context["id"], "offset": 5, "limit": 20})
        assert page["total"] == 8 and page["next_offset"] is None
        assert {m["name"] for m in [*status["missing_enabled_mods"], *page["mods"]]} == {
            f"Missing {number}" for number in range(8)}
        assert page["checked_at"] == status["launcher_checked_at"]
        assert not service.store.list("scan")
        assert {str(p): p.read_bytes() for p in (tmp_path / "sources").rglob("*") if p.is_file()} == before
    finally:
        service.close()


@pytest.mark.parametrize("platform", ["macos", "windows"])
def test_resume_with_another_installation_checks_that_installation(tmp_path, platform):
    source_a, source_b = tmp_path / "installation-a", tmp_path / "installation-b"
    options_a, _ = installation(source_a, platform)
    options_b, user_b = installation(source_b, platform)
    for source, options in ((source_a, options_a), (source_b, options_b)):
        options["installation_path"] = str(source / "Steam/steamapps/common/Crusader Kings III")
    (user_b / "mod/one/common/traits/shared.txt").write_bytes(b"different_installation_trait = { diplomacy = 7 }\n")
    original = {str(p): p.read_bytes() for source in (source_a, source_b)
                for p in source.rglob("*") if p.is_file()}
    service = Service(tmp_path / "managed")
    try:
        flow = AssistantContext(service)
        first = finish(service, flow.request_check(flow.get(locations=options_a)["id"]))
        resumed_b = flow.get(selection="resume", locations=options_b)
        assert resumed_b["state"] == "ready"
        assert resumed_b["workspace_id"] != first["workspace_id"]
        second = finish(service, flow.request_check(resumed_b["id"]))
        assert second["workspace_id"] != first["workspace_id"]
        assert second["scan_id"] != first["scan_id"] and not second["reused_scan"]
        scan = service.store.get("scan", second["scan_id"])
        assert scan["source_roots"]
        assert all(Path(root["path"]).is_relative_to(source_b) for root in scan["source_roots"])
        again = flow.get(selection="resume", locations=options_b)
        assert again["workspace_id"] == second["workspace_id"]
        assert again["saved_scan"]["id"] == second["scan_id"]
        assert {str(p): p.read_bytes() for source in (source_a, source_b)
                for p in source.rglob("*") if p.is_file()} == original
    finally:
        service.close()


def test_notes_keep_their_checked_context_and_old_context_cannot_review_current_issues(tmp_path):
    options, user = installation(tmp_path / "sources", "macos")
    service = Service(tmp_path / "managed")
    target = user / "mod/one/common/traits/shared.txt"
    original = target.read_bytes()
    try:
        flow = AssistantContext(service)
        cold = flow.get(locations=options)
        assert cold["saved_scan"] is None and cold["saved_index"] is None
        first = finish(service, flow.request_check(cold["id"]))
        first_notes = flow.remember(cold["id"], notes="The first captured files need discussion.")
        assert first_notes["notes_scan_id"] == first["scan_id"]
        assert first_notes["notes_index_id"] == first["index_id"]
        assert flow.get(selection="resume", locations=options)["conversation"]["applies_to_current_scan"]

        # The fixture edit represents an external update between conversations.
        target.write_bytes(original + b"\nnew_trait = { diplomacy = 3 }\n")
        current = flow.get(locations=options)
        second = finish(service, flow.request_check(current["id"]))
        assert second["scan_id"] != first["scan_id"]
        historical_notes = flow.remember(cold["id"], notes="This explanation concerns the first capture.")
        assert historical_notes["notes_scan_id"] == first["scan_id"]
        assert historical_notes["notes_index_id"] == first["index_id"]
        assert historical_notes["scan_id"] == second["scan_id"]
        resumed = flow.get(selection="resume", locations=options)
        assert resumed["conversation"]["notes"] == "This explanation concerns the first capture."
        assert not resumed["conversation"]["applies_to_current_scan"]
        current_index = service.store.get("agent_index", second["index_id"])
        issue_id = current_index["issues"][0]["id"]
        with pytest.raises(Conflict, match="older check"):
            flow.remember(cold["id"], reviewed_issue_ids=[issue_id])
        fresh_notes = flow.remember(current["id"], notes="This concerns the current capture.",
                                    reviewed_issue_ids=[issue_id])
        assert fresh_notes["notes_scan_id"] == second["scan_id"]
        assert fresh_notes["notes_index_id"] == second["index_id"]
        assert issue_id in fresh_notes["reviewed_issue_ids"]
        assert flow.get(selection="resume", locations=options)["conversation"]["applies_to_current_scan"]
        assert not service.store.list("agent_question")
    finally:
        target.write_bytes(original)
        service.close()


def test_not_ready_check_keeps_missing_mod_preview_bounded(tmp_path, monkeypatch):
    service = Service(tmp_path / "managed")
    try:
        original_workspaces = service.store.list("workspace")
        monkeypatch.setattr(service, "_discover_selection", lambda options: {
            "consistent": False, "complete": False,
            "playsets": [{"id": "ambiguous", "name": "Needs selection", "active": True}],
            "selected_playset_id": "ambiguous", "installation": None, "options": {},
            "configuration_hash": "synthetic-unavailable-selection",
            "mods": [{"owner": f"missing-{number}", "name": f"Missing {number}",
                      "enabled": True, "available": False} for number in range(100)]})
        context = service.agent_request("context", {})
        assert context["state"] == "needs_selection"
        monkeypatch.setattr(service, "_discover_selection", lambda *args: pytest.fail("Check re-read an unresolved selection"))
        blocked = service.agent_request("check", {"context_id": context["id"]})
        assert blocked["state"] == "needs_selection" and "job_id" not in blocked
        for result in (context, blocked["context"]):
            status = result["source_status"]
            assert len(status["missing_enabled_mods"]) == 5
            assert status["missing_enabled_mods_total"] == 100
            assert status["missing_mods_next_offset"] == 5
        page = service.agent_request("missing_mods", {"context_id": context["id"], "offset": 5, "limit": 20})
        assert page["total"] == 100 and page["next_offset"] == 25
        assert [mod["owner"] for mod in page["mods"]] == [f"missing-{number}" for number in range(5, 25)]
        assert page["checked_at"] == context["source_status"]["launcher_checked_at"]
        assert not service.store.list("job") and not service.store.list("scan")
        assert service.store.list("workspace") == original_workspaces
    finally:
        service.close()
