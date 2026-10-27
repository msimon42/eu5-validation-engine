import json

import pytest

from backend.engine.investigator import Investigator


def call(name, arguments, identifier="call-1"):
    return {"role": "assistant", "tool_calls": [{"id": identifier, "type": "function",
             "function": {"name": name, "arguments": json.dumps(arguments) if isinstance(arguments, dict) else arguments}}]}


def test_replay_bounded_search_and_repeated_call_id_is_idempotent():
    executed = []
    runner = Investigator({"search_sources": lambda arguments: executed.append(arguments) or {"hits": ["definition-1"]}})
    reply = call("search_sources", {"query": "item", "limit": 2})
    result = runner.run([{"role": "user", "content": "Investigate item"}],
                        replay=[reply, reply, {"role": "assistant", "content": "Requires a concrete design choice."}])
    assert result["status"] == "completed"
    assert result["trusted"] is False
    assert result["usage"]["tool_calls"] == 1
    assert len(executed) == 1


@pytest.mark.parametrize("reply", [call("shell", {"command": "delete"}),
                                  call("search_sources", '{"query":'),
                                  call("search_sources", '{"query":"x","query":"y"}'),
                                  call("search_sources", {"query": "x", "path": "/private"}),
                                  call("propose_structural_edit", {"operations": [{"waivers": ["B"]}]}),
                                  {"content": '{"proposal":{"waivers":["A"]}}'}])
def test_untrusted_model_cannot_escape_local_capabilities(reply):
    executed = []
    tools = {"search_sources": lambda arguments: executed.append(arguments),
             "propose_structural_edit": lambda arguments: executed.append(arguments)}
    result = Investigator(tools).run([], replay=[reply])
    assert result["status"] == "blocked"
    assert result["proposal"] is None
    assert not executed


def test_entire_batch_validates_before_any_mutation():
    executed = []
    first = call("propose_structural_edit", {"operations": []})
    first["tool_calls"].append(call("shell", {}, "bad")["tool_calls"][0])
    result = Investigator({"propose_structural_edit": lambda arguments: executed.append(arguments)}).run([], replay=[first])
    assert result["status"] == "blocked"
    assert not executed


def test_same_batch_conflicting_ids_and_total_budget_reject_before_execution():
    executed = []
    first = call("search_sources", {"query": "a"})
    first["tool_calls"].append(call("search_sources", {"query": "b"})["tool_calls"][0])
    tools = {"search_sources": lambda arguments: executed.append(arguments)}
    assert Investigator(tools).run([], replay=[first])["status"] == "blocked"
    assert not executed
    assert Investigator(tools, {"max_tool_calls": 0}).run([], replay=[call("search_sources", {"query": "a"})])["status"] == "blocked"
    assert not executed


def test_source_exclusions_and_credentials_absent_from_transcripts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-supersecret")
    result = Investigator({"read_spans": lambda _: {"source_path": "private/mod.txt", "text": "NEVER_TRANSMIT"}},
                          excluded_patterns=["private/*", "private-excerpt"]).run(
        [{"role": "user", "content": "private-excerpt sk-or-v1-supersecret"}],
        replay=[call("read_spans", {"document_id": "doc-1"}), {"content": "Done sk-or-v1-supersecret"}])
    encoded = json.dumps(result)
    assert result["status"] == "completed"
    assert "supersecret" not in encoded and "NEVER_TRANSMIT" not in encoded and "private-excerpt" not in encoded
    assert result["transcript"][1]["result"] == {"excluded": True}


def test_provider_network_disabled_until_capabilities_and_policy_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-private")
    def forbidden(*args, **kwargs):
        raise AssertionError("network must remain disabled")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    result = Investigator({}).run([], config={"model": "example/model", "allow_live": True})
    assert result["status"] == "blocked"
    assert "policy" in result["error"]


def test_model_cannot_mark_unsupported_final_proposal_trusted():
    result = Investigator({}).run([], replay=[{"content": '{"proposal":{"rationale":"Investigate","requested_decisions":["Choose target"]}}'}])
    assert result["status"] == "completed" and result["trusted"] is False
    assert result["proposal"]["requested_decisions"] == ["Choose target"]


def test_result_budget_and_tool_error_are_precise_without_leaking_exception_text():
    result = Investigator({"search_sources": lambda _: "x" * 100}, {"max_result_bytes": 10}).run(
        [], replay=[call("search_sources", {"query": "x"})])
    assert result["status"] == "blocked" and "byte budget" in result["error"]
    def rejected(_):
        raise ValueError("PRIVATE SOURCE BODY")
    result = Investigator({"search_sources": rejected}).run(
        [], replay=[call("search_sources", {"query": "x"}), {"content": "Need more evidence."}])
    assert "PRIVATE SOURCE BODY" not in json.dumps(result)
    assert result["transcript"][1]["result"]["error"] == "ValueError"
