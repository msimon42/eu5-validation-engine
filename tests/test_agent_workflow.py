"""Synthetic real-engine conversations; none execute CK3 or qualify a game rule."""
import base64
import copy

import pytest

from backend.agent.approvals import sign, signing_key
from backend.agent.workflow import AgentWorkflow
from backend.app.service import Service
from backend.app.store import Conflict


@pytest.fixture
def setup(tmp_path, request):
    sources = tmp_path / "originals"
    one, two = sources / "one", sources / "two"
    for root in (one, two):
        (root / "common/character_interactions").mkdir(parents=True)
        (root / "localization/english").mkdir(parents=True)
    (one / "descriptor.mod").write_bytes(b'name="Unofficial Patch"\n')
    (two / "descriptor.mod").write_bytes(b'name="More Interactive Vassals"\n')
    for root, raw in [(one, b'call_ally_interaction = { effect = { first = yes } }\r\n'),
                      (two, b'call_ally_interaction = { effect = { second = yes } }\n')]:
        (root / "common/character_interactions/actions.txt").write_bytes(raw)
    (one / "localization/english/one_l_english.yml").write_bytes(b'\xef\xbb\xbfl_english:\n label:0 "First"\n repeated:0 "Old"\n repeated:0 "New"\n')
    (two / "localization/english/two_l_english.yml").write_bytes(b'\xef\xbb\xbfl_english:\n label:0 "Second"\n')
    if getattr(request, "param", False):
        (one / "common/character_interactions/also.txt").write_bytes(b'call_ally_interaction = { other = yes }\n')
    before = {str(p): p.read_bytes() for p in sources.rglob("*") if p.is_file()}
    service = Service(tmp_path / "managed")
    workspace = service.create_workspace({"game_id": "ck3", "mode": "game", "target_platform": "macos",
        "name": "Conversation", "sources": [{"owner": "one", "path": str(one)}, {"owner": "two", "path": str(two)}]})
    # Synthetic installation label only; no discovery or version is represented as a real game.
    workspace = service.store.put("workspace", {**workspace, "ck3_selection": {"installation": {"version_display": "synthetic"}}})
    scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
    workspace = service.store.get("workspace", workspace["id"])
    flow = AgentWorkflow(service)
    index_id = flow.index(workspace, {"scan_id": scan_id}, lambda *args: None)["index_id"]
    yield service, flow, workspace, index_id, sources
    assert {str(p): p.read_bytes() for p in sources.rglob("*") if p.is_file()} == before
    service.close()


def proposal(setup, combined=None):
    service, flow, workspace, index_id, _ = setup
    issue = next(item for item in service.store.get("agent_index", index_id)["issues"]
                 if item["target"].endswith("/call_ally_interaction"))
    return flow.prepare(workspace, {"index_id": index_id, "issue_id": issue["id"],
        "combined_base64": base64.b64encode(combined).decode() if combined else None}, lambda *args: None)


def answer(setup, proposal_id, purpose="choose", selection=None, action="accept"):
    service, flow, workspace, *_ = setup
    question = flow.challenge(workspace["id"], proposal_id, purpose)
    value = {"question_id": question["id"], "nonce": question["nonce"],
        "proposal_hash": question["proposal_hash"], "action": action, "choice": selection}
    return flow.answer(value, sign(signing_key(service.store), value))


def test_complete_index_pages_localization_and_resume(setup):
    service, flow, workspace, index_id, _ = setup
    result = flow.issues(workspace["id"], index_id, limit=1)
    assert result["total"] >= 3 and len(result["issues"]) == 1 and result["next_offset"] == 1
    located = flow.issues(workspace["id"], index_id, query="label")
    assert located["total"] == 1 and located["issues"][0]["comparison"] == "different"
    internal = flow.issues(workspace["id"], index_id, query="repeated", include_internal=True)
    assert internal["total"] == 1 and internal["issues"][0]["internal"]
    assert flow.session(workspace["id"])["index_id"] == index_id
    issue_id = located["issues"][0]["id"]
    excerpt = flow.inspect(workspace["id"], index_id, issue_id, 0, 0, 2)["excerpt"]
    assert len(excerpt["text"].encode()) <= 2 and excerpt["next_offset"]
    with pytest.raises(ValueError):
        flow.issues(workspace["id"], index_id, limit=101)


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_multiple_versions_in_one_mod_require_review_instead_of_silent_selection(setup):
    with pytest.raises(ValueError, match="several versions"):
        proposal(setup)


def test_user_choice_prepares_inactive_fix_and_undo_retains_recovery(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup, b'call_ally_interaction = { effect = { first = yes second = yes } }\n')
    with pytest.raises(ValueError, match="choose"):
        flow.apply(workspace["id"], draft["id"])
    selected = answer(setup, draft["id"], selection="test_combined")
    assert selected["state"] == "approved"
    applied = flow.apply(workspace["id"], draft["id"])
    assert applied["state"] == "prepared" and not applied["enabled"]
    assert flow.apply(workspace["id"], draft["id"]) == applied
    saved = service.store.get("agent_proposal", draft["id"])
    raw_files = [service.store.fs.read_bytes(saved["applied_path"] + "/" + file["path"]) for file in saved["files"]]
    assert any(b"first = yes second = yes" in raw for raw in raw_files)
    with pytest.raises(ValueError, match="ask"):
        flow.test(workspace["id"], draft["id"])
    answer(setup, draft["id"], "test", selection="yes")
    assert flow.test(workspace["id"], draft["id"])["outcome"] == "not_run"
    answer(setup, draft["id"], "enable", selection="yes")
    with pytest.raises(ValueError, match="not passed"):
        flow.enable(workspace["id"], draft["id"])
    answer(setup, draft["id"], "undo", selection="yes")
    assert flow.undo(workspace["id"], draft["id"])["state"] == "undone"
    assert all(service.store.fs.resolve(saved["applied_path"] + "/" + file["path"]).is_file() for file in saved["files"])


def test_older_choices_need_review_but_prepared_files_can_still_be_retired(setup):
    from backend.agent.workflow import content_hash
    service, flow, workspace, *_ = setup
    draft = proposal(setup)
    answer(setup, draft["id"], selection=draft["options"][0]["id"])
    flow.apply(workspace["id"], draft["id"])
    saved = service.store.get("agent_proposal", draft["id"])
    # Represent an intact artifact created before the choice wording update.
    saved["repair_version"] = "call-allies-draft-1"
    saved["content_hash"] = content_hash(saved)
    service.store.put("agent_proposal", saved)
    assert flow.proposal(workspace["id"], saved["id"])["requires_fresh_choices"]
    with pytest.raises(Conflict, match="fresh choices"):
        flow.challenge(workspace["id"], saved["id"], "choose")
    with pytest.raises(Conflict, match="review fresh choices"):
        flow.apply(workspace["id"], saved["id"])
    answer(setup, saved["id"], "undo", selection="yes")
    assert flow.undo(workspace["id"], saved["id"])["state"] == "undone"
    assert all(service.store.fs.resolve(saved["applied_path"] + "/" + file["path"]).is_file() for file in saved["files"])


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_or_cancel_never_creates_change_files(setup, action):
    _, flow, workspace, *_ = setup
    draft = proposal(setup)
    assert answer(setup, draft["id"], action=action)["state"] == "declined"
    with pytest.raises(ValueError):
        flow.apply(workspace["id"], draft["id"])


def test_model_cannot_forge_approval_or_reuse_it_for_other_content(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup)
    question = flow.challenge(workspace["id"], draft["id"])
    value = {"question_id": question["id"], "nonce": question["nonce"], "proposal_hash": question["proposal_hash"],
             "action": "accept", "choice": draft["options"][0]["id"]}
    with pytest.raises(ValueError, match="Approval"):
        flow.answer(value, "0" * 64)
    signed = sign(signing_key(service.store), value)
    flow.answer(value, signed)
    assert flow.answer(value, signed)["state"] == "approved"
    changed = copy.deepcopy(value)
    changed["choice"] = draft["options"][1]["id"]
    with pytest.raises(Conflict):
        flow.answer(changed, sign(signing_key(service.store), changed))
    record = service.store.get("agent_proposal", draft["id"])
    record["options"][0]["label"] = "Unapproved new choice"
    service.store.put("agent_proposal", record)
    with pytest.raises(Conflict, match="changed"):
        flow.apply(workspace["id"], draft["id"])


def test_stale_source_refuses_even_after_user_approval(setup):
    _, flow, workspace, _, sources = setup
    draft = proposal(setup)
    answer(setup, draft["id"], selection=draft["options"][0]["id"])
    path = sources / "one/common/character_interactions/actions.txt"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"# external update\n")
        with pytest.raises(Conflict, match="changed"):
            flow.apply(workspace["id"], draft["id"])
    finally:
        path.write_bytes(original)


def test_cross_workspace_and_unrelated_replacement_rejected(setup):
    service, flow, workspace, index_id, _ = setup
    other = service.create_workspace({"game_id": "ck3", "mode": "game", "target_platform": "macos"})
    with pytest.raises(ValueError):
        flow.issues(other["id"], index_id)
    with pytest.raises(ValueError, match="Only one"):
        proposal(setup, b'call_ally_interaction = {}\nother_action = {}')
    assert workspace["game_id"] == "ck3"


def test_undo_refuses_intervening_file_edit(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup)
    answer(setup, draft["id"], selection=draft["options"][0]["id"])
    flow.apply(workspace["id"], draft["id"])
    saved = service.store.get("agent_proposal", draft["id"])
    target = saved["applied_path"] + "/" + saved["files"][0]["path"]
    service.store.fs.write_bytes(target, b"user edit")
    answer(setup, draft["id"], "undo", selection="yes")
    with pytest.raises(Conflict):
        flow.undo(workspace["id"], draft["id"])
