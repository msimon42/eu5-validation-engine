"""Concern accounting tests use captured synthetic sources only."""
import copy

import pytest

from backend.agent.investigation import _Snapshot
from backend.agent.knowledge import read_knowledge
from backend.agent.reviews import CONCERN_VERSION, MAX_CONCERN_ISSUES, ReviewWorkflow, build_concerns
from backend.agent.workflow import AgentWorkflow
from backend.app.service import Service
from backend.app.store import Conflict
from test_agent_investigation import captured as captured


def sample_issue(number, *, target="game/character_interaction/call_ally_interaction", path="common/character_interactions/war.txt",
                 kind="duplicate_definition", comparison="different", internal=False, metadata=False):
    owners = ("one",) if internal else ("one", "two")
    return {"id": f"issue_{number}", "kind": kind, "target": target,
            "comparison": comparison, "internal": internal, "metadata_only": metadata,
            "mods": [{"owner": owner, "name": owner.title()} for owner in owners],
            "sources": [{"owner": owner, "path": path, "sha256": "a" * 64} for owner in owners],
            "what_is_known": "The saved content differs." if comparison == "different" else "The compared content is identical.",
            "language": "english" if kind == "localization_overlap" else None}


def target_concern(captured):
    service, _, workspace, index_id, _ = captured
    flow = ReviewWorkflow(service)
    concern = next(row for row in flow.list_concerns(workspace["id"], index_id)["concerns"]
                   if row["topic"] == "Wars, diplomacy, and allies")
    return flow, workspace["id"], index_id, concern


def references_for(captured, concern):
    service, _, workspace, index_id, _ = captured
    view = _Snapshot(service, workspace["id"], index_id)
    source_pairs = {(source["owner"], source["path"]) for issue in view.index["issues"]
                    if issue["id"] in concern["issue_ids"] for source in issue["sources"]}
    references = [{"issue_id": identifier} for identifier in concern["issue_ids"]]
    references += [{"source_id": source["source_id"], "sha256": source["sha256"], "span": [0, source["size"]]}
                   for source in view.files if (source["owner"], source["path"]) in source_pairs]
    return references


def test_all_findings_partitioned_stably_and_topic_links_do_not_hide_duplicates():
    issues = [sample_issue(number, target=f"game/character_interaction/marriage_{number}") for number in range(43)]
    issues += [sample_issue(100, target="common/character_interactions/war.txt", kind="overlapping_path"),
               sample_issue(101, target="game/localization/english:shirt", path="localization/english/shirts.yml",
                            kind="localization_overlap", internal=True),
               sample_issue(102, target="readme.md", path="readme.md", kind="overlapping_path", metadata=True),
               sample_issue(103, target="gfx/pic.dds", path="gfx/pic.dds", kind="overlapping_path", comparison="identical")]
    index = {"id": "index_one", "issues": issues}
    concerns = build_concerns(index)
    ids = [identifier for concern in concerns for identifier in concern["issue_ids"]]
    assert set(ids) == {issue["id"] for issue in issues} and len(ids) == len(issues)
    assert max(concern["raw_finding_count"] for concern in concerns) == MAX_CONCERN_ISSUES
    assert any(concern["internal"] for concern in concerns)
    assert concerns[-1]["priority"] == 5
    marriage = [concern for concern in concerns if concern["topic"] == "Marriage, romance, and family"]
    assert len(marriage) == 3 and sum(item["raw_finding_count"] for item in marriage) == 44
    assert all(concern["related_concern_ids"] for concern in marriage)
    assert build_concerns({**index, "issues": list(reversed(issues))}) == concerns


def test_review_requires_complete_source_coverage_and_preserves_interpretation(captured):
    flow, workspace, index, concern = target_concern(captured)
    refs = references_for(captured, concern)
    with pytest.raises(ValueError, match="every finding"):
        flow.record_concern_review(workspace, index, concern["id"], "explained_from_files", explanation="Read it.")
    with pytest.raises(ValueError, match="every differing contribution"):
        flow.record_concern_review(workspace, index, concern["id"], "explained_from_files", explanation="Read it.",
                                   evidence_refs=[ref for ref in refs if "issue_id" in ref])
    result = flow.record_concern_review(workspace, index, concern["id"], "explained_from_files",
        explanation="One copy keeps the base action and the other calls a helper.",
        player_impact="The helper's behavior still needs investigation.", evidence_refs=refs,
        uncertainties=["The selected game behavior is untested."])
    review = result["review"]
    assert review["reviewer"] == "agent" and review["game_observations"] == []
    assert not review["approval"] and not review["grants_repair_capability"]
    assert review["revision"] == 1
    report = flow.get_investigation_report(workspace, index, limit=1)
    assert report["summary"]["raw_findings"] == sum(report["summary"]["raw_finding_counts"].values())
    assert report["summary"]["gameplay_compatibility"] == "not_established"
    assert report["summary"]["counts"]["explained_from_files"] >= 1


def test_review_revision_conflict_rolls_back_history_and_pending_is_not_complete(captured):
    flow, workspace, index, concern = target_concern(captured)
    first = flow.record_concern_review(workspace, index, concern["id"], "in_progress", explanation="Reading the sources.")
    assert not first["summary"]["accounted_for"]
    with pytest.raises(Conflict, match="Record changed"):
        flow.record_concern_review(workspace, index, concern["id"], "pending", expected_revision=0)
    assert captured[0].store.list("agent_concern_review_history", workspace) == []
    second = flow.record_concern_review(workspace, index, concern["id"], "pending", expected_revision=1)
    assert second["review"]["revision"] == 2
    assert len(captured[0].store.list("agent_concern_review_history", workspace)) == 1


def test_unresolved_disposition_needs_specific_reason_and_complete_issue_accounting(captured):
    flow, workspace, index, concern = target_concern(captured)
    refs = references_for(captured, concern)
    kwargs = {"explanation": "A helper's behavior is unknown.", "evidence_refs": refs,
              "uncertainties": ["Its runtime interaction has not been observed."], "next_step": "Inspect the helper and relevant documentation."}
    with pytest.raises(ValueError, match="missing information"):
        flow.record_concern_review(workspace, index, concern["id"], "blocked_by_missing_information", **kwargs)
    with pytest.raises(ValueError, match="unfinished reading"):
        flow.record_concern_review(workspace, index, concern["id"], "blocked_by_missing_information",
                                   unresolved_reason="ran_out_of_time", **kwargs)
    with pytest.raises(ValueError, match="unfinished reading"):
        flow.record_concern_review(workspace, index, concern["id"], "needs_game_test",
            **{**kwargs, "evidence_refs": [{"issue_id": identifier} for identifier in concern["issue_ids"]]})
    result = flow.record_concern_review(workspace, index, concern["id"], "needs_game_test", **kwargs)
    assert result["review"]["unresolved_reason"] == "unknown_game_behavior"
    with pytest.raises(ValueError, match="concrete question"):
        flow.record_concern_review(workspace, index, concern["id"], "needs_user_choice", expected_revision=1, **kwargs)
    result = flow.record_concern_review(workspace, index, concern["id"], "needs_user_choice", expected_revision=1,
        user_question="Which version of the ally interaction do you want to preserve?", **kwargs)
    assert result["review"]["state"] == "needs_user_choice" and not result["review"]["approval"]


def test_invalid_foreign_and_partial_source_references_rejected(captured):
    flow, workspace, index, concern = target_concern(captured)
    refs = references_for(captured, concern)
    invalid = copy.deepcopy(refs)
    next(ref for ref in invalid if "source_id" in ref)["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="exact captured hash"):
        flow.record_concern_review(workspace, index, concern["id"], "in_progress", evidence_refs=invalid)
    with pytest.raises(ValueError, match="does not belong"):
        flow.record_concern_review(workspace, index, concern["id"], "in_progress", evidence_refs=[{"issue_id": "other"}])
    invalid = copy.deepcopy(refs)
    next(ref for ref in invalid if "source_id" in ref)["span"][1] = 1
    with pytest.raises(ValueError, match="every differing contribution"):
        flow.record_concern_review(workspace, index, concern["id"], "explained_from_files", explanation="Incomplete reading.", evidence_refs=invalid)


def test_knowledge_revision_is_pinned_and_current_exclusions_redact_saved_explanations(captured, monkeypatch):
    flow, workspace, index, concern = target_concern(captured)
    knowledge = read_knowledge("files-and-definitions")
    ref = {"entry_id": knowledge["id"], "revision": knowledge["revision"], "library_sha256": knowledge["library_sha256"]}
    with pytest.raises(Conflict, match="reference revision changed"):
        flow.record_concern_review(workspace, index, concern["id"], "in_progress", evidence_refs=[{**ref, "revision": "old"}])
    flow.record_concern_review(workspace, index, concern["id"], "in_progress", explanation="PRIVATE_CAPTURE_TEXT", evidence_refs=[ref])
    service = captured[0]
    original_policy = service.inference_policy()
    monkeypatch.setattr(service, "inference_policy", lambda: {**original_policy, "excluded_patterns": ["common/character_interactions/*"]})
    assert flow.context_summary(workspace, index)["state"] == "needs_report_refresh"
    report = flow.get_investigation_report(workspace, index)
    assert "PRIVATE_CAPTURE_TEXT" not in str(report)
    row = next(row for row in report["concerns"] if row["id"] == concern["id"])
    assert row["excluded"] and row["review"]["state"] == "blocked_by_missing_information"
    assert row["review"]["unresolved_reason"] == "excluded_content"
    assert row["issue_ids"] == []


def test_legacy_markers_do_not_complete_reviews_and_context_summary_is_header_only(captured, monkeypatch):
    flow, workspace, index, concern = target_concern(captured)
    service = captured[0]
    session = service.store.list("agent_session", workspace, limit=1)[0]
    service.store.put("agent_session", {**session, "notes": "We looked at this before.", "reviewed_issue_ids": concern["issue_ids"]})
    report = flow.get_investigation_report(workspace, index)
    assert report["legacy_notes"] == {"present": True, "counts_as_completed_review": False}
    assert next(row for row in report["concerns"] if row["id"] == concern["id"])["review"]["state"] == "pending"
    original = service.store.get

    def guarded(kind, identifier):
        assert kind not in {"scan", "agent_index", "agent_review_summary"}
        return original(kind, identifier)

    monkeypatch.setattr(service.store, "get", guarded)
    monkeypatch.setattr(service.store.fs, "read_bytes", lambda *args, **kwargs: pytest.fail("Context read a source body"))
    context = flow.context_summary(workspace, index)
    assert context["state"] == "ready" and context["next_unfinished"]


def test_unchanged_resume_keeps_reviews_and_new_scan_does_not_transfer_them(captured):
    flow, workspace, index, concern = target_concern(captured)
    flow.record_concern_review(workspace, index, concern["id"], "in_progress", explanation="Continue here.")
    assert ReviewWorkflow(captured[0]).list_concerns(workspace, index, state="in_progress")["total"] == 1
    service = captured[0]
    current = service.store.get("workspace", workspace)
    service.store.put("workspace", {**current, "generation": "different_scan"})
    with pytest.raises(Conflict):
        flow.record_concern_review(workspace, index, concern["id"], "pending", expected_revision=1)
    assert flow.context_summary(workspace, index)["state"] == "needs_report_refresh"
    assert service.store.list("agent_concern_review", workspace)[0]["explanation"] == "Continue here."


def test_all_pages_and_all_outcomes_reconcile(captured):
    flow, workspace, index, _ = target_concern(captured)
    concerns = flow.list_concerns(workspace, index)["concerns"]
    for concern in concerns:
        if concern["review"]["state"] == "explained_from_files":
            continue
        flow.record_concern_review(workspace, index, concern["id"], "blocked_by_missing_information",
            explanation="The precise runtime selection rule is unavailable.",
            evidence_refs=references_for(captured, concern),
            uncertainties=["The result in CK3 remains unobserved."], next_step="Retain this as unresolved until scoped evidence exists.",
            unresolved_reason="unknown_game_behavior")
    offset, returned = 0, []
    while True:
        report = flow.get_investigation_report(workspace, index, offset=offset, limit=1)
        returned.extend(report["concerns"])
        if report["next_offset"] is None:
            break
        offset = report["next_offset"]
    assert len(returned) == report["total"] == len(concerns)
    assert report["summary"]["accounted_for"] and report["summary"]["next_unfinished"] is None
    assert report["summary"]["counts"]["blocked_by_missing_information"] > 0
    assert report["summary"]["gameplay_compatibility"] == "not_established"
    assert report["summary"]["concern_version"] == CONCERN_VERSION


def test_identical_content_is_only_a_narrow_engine_observation(captured):
    service, _, workspace, index_id, _ = captured
    index = service.store.get("agent_index", index_id)
    for issue in index["issues"]:
        issue["comparison"] = "identical"
    service.store.put("agent_index", index)
    report = ReviewWorkflow(service).get_investigation_report(workspace["id"], index_id)
    assert report["summary"]["accounted_for"]
    assert all(row["review"]["reviewer"] == "engine" for row in report["concerns"])
    assert all("does not establish" in row["review"]["explanation"] for row in report["concerns"])
    assert service.store.list("agent_concern_review", workspace["id"]) == []
    assert report["summary"]["game_runs"] == 0


def test_saved_blob_tampering_is_not_accepted_as_review_evidence(captured):
    flow, workspace, index, concern = target_concern(captured)
    references = references_for(captured, concern)
    source = next(ref for ref in references if "source_id" in ref)
    checksum = source["sha256"]
    service = captured[0]
    relative = f"blobs/sha256/{checksum[:2]}/{checksum}"
    original = service.store.fs.read_bytes(relative)
    service.store.fs.write_bytes(relative, b"x" * len(original))
    with pytest.raises(Conflict, match="saved source copy changed"):
        flow.record_concern_review(workspace, index, concern["id"], "in_progress", evidence_refs=references)
    assert service.store.list("agent_concern_review", workspace) == []


def test_source_change_during_review_rejects_save(captured, monkeypatch):
    flow, workspace, index, concern = target_concern(captured)
    original = flow._evidence

    def change_after_validation(*args):
        result = original(*args)
        current = captured[0].store.get("workspace", workspace)
        captured[0].store.put("workspace", {**current, "generation": "new_scan"})
        return result

    monkeypatch.setattr(flow, "_evidence", change_after_validation)
    with pytest.raises(Conflict, match="changed while saving"):
        flow.record_concern_review(workspace, index, concern["id"], "in_progress")
    assert captured[0].store.list("agent_concern_review", workspace) == []


def test_alternative_report_never_claims_launcher_selection(captured):
    flow, workspace, index, _ = target_concern(captured)
    service = captured[0]
    current = service.store.get("workspace", workspace)
    service.store.put("workspace", {**current, "inspection_scope": {"kind": "alternative_candidate", "candidate_id": "synthetic_candidate"},
                                    "inspection_missing_mods": [{"owner": "missing", "name": "Still missing", "reason": "Absent"}]})
    report = flow.get_investigation_report(workspace, index)
    assert report["inspection_scope"]["kind"] == "alternative_candidate"
    assert "not the launcher-selected files" in report["narrative"]
    assert report["missing_mod_count"] == 1 and report["missing_mods"][0]["name"] == "Still missing"


def test_unknown_future_review_format_is_not_silently_accepted(captured):
    flow, workspace, index, concern = target_concern(captured)
    result = flow.record_concern_review(workspace, index, concern["id"], "in_progress")
    captured[0].store.put("agent_concern_review", {**result["review"], "format": "future-review-format"})
    with pytest.raises(Conflict, match="unsupported format"):
        flow.get_investigation_report(workspace, index)


def test_real_unsupported_asset_gap_can_be_accounted_for_without_readable_text(tmp_path):
    source_root = tmp_path / "sources"
    originals = {"one": b"DDS \x00\xfffirst", "two": b"DDS \x00\xffsecond"}
    for owner, raw in originals.items():
        asset = source_root / owner / "gfx/shared.dds"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(raw)
    service = Service(tmp_path / "managed")
    try:
        workspace = service.create_workspace({"name": "Synthetic unsupported sources", "game_id": "ck3",
            "target_platform": "macos", "mode": "game",
            "sources": [{"owner": owner, "path": str(source_root / owner)} for owner in originals]})
        scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
        workspace = service.store.get("workspace", workspace["id"])
        index_id = AgentWorkflow(service).index(workspace, {"scan_id": scan_id}, lambda *args: None)["index_id"]
        flow = ReviewWorkflow(service)
        concern = flow.list_concerns(workspace["id"], index_id)["concerns"][0]
        kwargs = {"explanation": "The supplied pictures differ, and this tool cannot inspect their visual content.",
                  "uncertainties": ["What each picture looks like remains uninspected."],
                  "next_step": "Retain the unsupported visual comparison as an explicit limitation.",
                  "evidence_refs": [{"issue_id": identifier} for identifier in concern["issue_ids"]]}
        with pytest.raises(ValueError, match="matching engine-observed source gap"):
            flow.record_concern_review(workspace["id"], index_id, concern["id"], "blocked_by_missing_information",
                                       unresolved_reason="missing_source", **kwargs)
        with pytest.raises(ValueError, match="unreadable contributions"):
            flow.record_concern_review(workspace["id"], index_id, concern["id"], "needs_game_test", **kwargs)
        result = flow.record_concern_review(workspace["id"], index_id, concern["id"], "blocked_by_missing_information",
                                            unresolved_reason="unsupported_content", **kwargs)
        assert result["summary"]["accounted_for"]
        assert all(gap["reason"] == "unsupported_content" for gap in result["review"]["engine_gaps"])
        assert result["review"]["game_observations"] == []
    finally:
        service.close()
    assert {owner: (source_root / owner / "gfx/shared.dds").read_bytes() for owner in originals} == originals


def test_claimed_missing_information_without_engine_gap_is_rejected(captured):
    flow, workspace, index, concern = target_concern(captured)
    with pytest.raises(ValueError, match="matching engine-observed source gap"):
        flow.record_concern_review(workspace, index, concern["id"], "blocked_by_missing_information",
            explanation="An unsupported file is claimed without evidence.",
            uncertainties=["This is not an established gap."], next_step="Inspect the actual captured sources.",
            evidence_refs=references_for(captured, concern), unresolved_reason="unsupported_content")


def test_missing_mod_pages_remain_bound_to_capture_and_have_separate_cursor(captured):
    flow, workspace, index, _ = target_concern(captured)
    service = captured[0]
    saved = service.store.get("agent_index", index)
    unavailable = [{"owner": f"missing_{number}", "name": f"Captured missing {number}", "reason": "Absent"}
                   for number in range(45)]
    service.store.put("agent_index", {**saved, "unavailable_mods": unavailable})
    first = flow.get_investigation_report(workspace, index, offset=1, limit=1)
    assert first["missing_mods"] == unavailable[:20]
    assert first["missing_mods_scope"] == "saved_capture"
    assert first["missing_mods_tool"] == "get_investigation_report"
    assert first["missing_mods_total"] == first["missing_mod_count"] == 45
    second = flow.get_investigation_report(**first["missing_mods_continuation"])
    assert second["missing_mods"] == unavailable[20:40]
    assert second["offset"] == first["offset"] == 1
    assert second["concerns"] == first["concerns"]
    third = flow.get_investigation_report(**second["missing_mods_continuation"])
    assert third["missing_mods"] == unavailable[40:]
    assert third["missing_mods_continuation"] is None and third["missing_mods_next_offset"] is None
    with pytest.raises(ValueError, match="valid page"):
        flow.get_investigation_report(workspace, index, missing_offset=-1)


@pytest.mark.parametrize("method", ["list_concerns", "get_investigation_report"])
def test_policy_change_during_review_response_returns_no_saved_prose(captured, monkeypatch, method):
    flow, workspace, index, concern = target_concern(captured)
    service = captured[0]
    saved = flow.record_concern_review(workspace, index, concern["id"], "in_progress", explanation="PRIVATE_SAVED_PROSE")
    original_rows = flow._rows
    original_policy = service.inference_policy()
    policy = dict(original_policy)
    monkeypatch.setattr(service, "inference_policy", lambda: policy)

    def change_after_rows(view):
        result = original_rows(view)
        policy["excluded_patterns"] = ["common/character_interactions/*"]
        return result

    monkeypatch.setattr(flow, "_rows", change_after_rows)
    with pytest.raises(Conflict, match="Source permissions changed"):
        getattr(flow, method)(workspace, index)
    summary = service.store.get("agent_review_summary", saved["summary"]["id"])
    assert summary["policy_hash"] == saved["review"]["policy_hash"]
    context = flow.context_summary(workspace, index)
    assert context["state"] == "needs_report_refresh"
    assert "PRIVATE_SAVED_PROSE" not in str(context)
