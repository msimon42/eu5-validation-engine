import json

from backend.app.service import Service
from backend.engine.parser import parse, digest


def prepare(service):
    workspace = service.store.list("workspace")[0]
    scan = service._scan(workspace, {"fixture_id": "F03"}, lambda *args: None)
    workspace = service.store.get("workspace", workspace["id"])
    return workspace, service.store.get("scan", scan["scan_id"])


def tool_call(name, args, identifier="read"):
    return {"role": "assistant", "tool_calls": [{"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_default_replay_uses_actual_bounded_evidence_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = Service(tmp_path)
    workspace, scan = prepare(service)
    result = service._investigate(workspace, {"scan_id": scan["id"], "mode": "replay"}, lambda *args: None)
    assert result["status"] == "completed"
    assert result["mode"] == "offline_replay"
    assert result["usage"]["tool_calls"] == 1
    assert result["trusted"] is False
    service.close()


def test_excluded_sources_do_not_leak_through_derived_definition_values(tmp_path):
    service = Service(tmp_path)
    workspace, scan = prepare(service)
    policy = service.inference_policy()
    policy.pop("key_configured")
    policy["excluded_patterns"] = ["in_game/common/testdb/10.txt"]
    service.store.put("configuration", {"id": "inference-policy", "policy": policy})
    replay = [tool_call("get_effective_definition", {"definition_id": "in_game/testdb/item"}), {"content": "Review remains conditional"}]
    result = service._investigate(workspace, {"scan_id": scan["id"], "replay": replay}, lambda *args: None)
    tools = [entry for entry in result["transcript"] if entry["type"] == "tool"]
    assert tools[0]["result"] == [{"id": "in_game/testdb/item", "excluded": True}]
    service.close()


def test_proposal_can_only_edit_exact_staged_scalar_then_must_revalidate(tmp_path):
    import base64
    service = Service(tmp_path)
    workspace, scan = prepare(service)
    stage = service._stage(workspace, {"scan_id": scan["id"]}, lambda *args: None)
    candidate = service.store.get("candidate", stage["candidate_id"])
    raw = base64.b64decode(candidate["plan"]["files"][0]["bytes_base64"])
    doc = parse(raw)
    node = next(node for node in doc.children[0].children if node.key == "x")
    args = {"candidate_id": candidate["id"], "read_set": candidate["plan"]["read_set"], "write_set": candidate["plan"]["write_set"],
        "operations": [{"kind": "ReplaceScalar", "document_hash": doc.sha256, "start": node.value_start, "end": node.value_end,
            "old_hash": digest(raw[node.value_start:node.value_end]), "ordinal": node.ordinal, "replacement_base64": base64.b64encode(b"1").decode()}],
        "rationale": "Deliberately suppress A to exercise local preservation rejection"}
    result = service._investigate(workspace, {"scan_id": scan["id"], "replay": [tool_call("propose_structural_edit", args), {"content": "Untrusted proposal staged for checking"}]}, lambda *args: None)
    proposal = next(entry for entry in result["transcript"] if entry["type"] == "tool")["result"]
    assert proposal["requires_local_validation"]
    validation = service._validate(workspace, {"candidate_id": proposal["candidate_id"]}, lambda *args: None)
    assert validation["status"] == "blocked"
    assert not validation["validation"]["experimental_eligible"]
    service.close()
