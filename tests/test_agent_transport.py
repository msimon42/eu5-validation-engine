"""Actual MCP calls and native elicitation responses against an isolated real engine."""
import asyncio
import base64
import json

from fastapi.testclient import TestClient
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from backend.agent.server import build_server
from backend.app.main import create_app
from test_agent_workflow import setup as setup, proposal


class LocalClient:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def agent(self, operation, **payload):
        return self.request("POST", "/api/agent", json={"operation": operation, "payload": payload})

    def connector_key(self):
        from backend.agent.approvals import signing_key
        return signing_key(self.client.app.state.service.store)


def test_headless_api_has_no_dashboard_and_strict_approval_input(tmp_path):
    with TestClient(create_app(tmp_path / "managed", testing=True, frontend=False)) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/engine").json()["headless"]
        response = client.post("/api/agent", json={"operation": "status"})
        assert response.status_code == 403
        client.headers["X-Session-Token"] = client.get("/api/bootstrap").json()["session_token"]
        assert client.post("/api/agent", json={"operation": "status"}).json()["interface"] == "codex"
        assert client.post("/api/agent", json={"operation": "apply", "payload": {
            "workspace_id": "x", "proposal_id": "x", "approved": True}}).status_code == 422


def test_native_choice_reaches_engine_but_model_cannot_supply_approval(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup, b'call_ally_interaction = { effect = { first = yes second = yes } }')
    asked = []

    class Client:
        def agent(self, operation, **payload):
            return service.agent_request(operation, payload)

        def connector_key(self):
            from backend.agent.approvals import signing_key
            return signing_key(service.store)

    async def answer_from_user(context, params):
        asked.append(params)
        # Actual SDK client response channel, not a tool argument from the model.
        options = params.requestedSchema["properties"]["choice"]["enum"]
        assert "Prepare the proposed combined version" in options
        assert all("keep_" not in option for option in options)
        return types.ElicitResult(action="accept", content={"choice": options[0]})

    async def run():
        server = build_server(Client())
        async with create_connected_server_and_client_session(server, elicitation_callback=answer_from_user) as session:
            tools = await session.list_tools()
            approval = next(tool for tool in tools.tools if tool.name == "ask_about_changes")
            assert set(approval.inputSchema["properties"]) == {"workspace_id", "proposal_id"}
            result = await session.call_tool("ask_about_changes", {
                "workspace_id": workspace["id"], "proposal_id": draft["id"]})
            assert not result.isError, result
            assert json.loads(result.content[0].text)["state"] == "approved"
            refused = await session.call_tool("enable_selected_changes", {
                "workspace_id": workspace["id"], "proposal_id": draft["id"]})
            assert not json.loads(refused.content[0].text)["enabled"]
            unrun = await session.call_tool("test_selected_changes", {
                "workspace_id": workspace["id"], "proposal_id": draft["id"]})
            assert json.loads(unrun.content[0].text)["outcome"] == "not_run"
    asyncio.run(run())
    assert len(asked) == 1
    assert flow.proposal(workspace["id"], draft["id"])["selected_option"] == "test_combined"


def test_missing_user_prompt_support_never_approves(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup)

    class Client:
        def agent(self, operation, **payload):
            return service.agent_request(operation, payload)

    async def run():
        async with create_connected_server_and_client_session(build_server(Client())) as session:
            result = await session.call_tool("ask_about_changes", {
                "workspace_id": workspace["id"], "proposal_id": draft["id"]})
            assert result.isError
    asyncio.run(run())
    assert flow.proposal(workspace["id"], draft["id"])["state"] == "awaiting_choice"


def test_unrelated_combined_bytes_rejected_by_real_command_schema(tmp_path):
    with TestClient(create_app(tmp_path / "managed", testing=True, frontend=False)) as client:
        client.headers["X-Session-Token"] = client.get("/api/bootstrap").json()["session_token"]
        result = client.post("/api/commands", json={"command": "agent_prepare", "workspace_id": "x",
            "idempotency_key": "bad-options", "payload": {"index_id": "x", "issue_id": "x",
                "combined_base64": base64.b64encode(b"other={}").decode(), "write_path": "/original"}})
        assert result.status_code == 422


def test_mismatched_loaded_engine_blocks_preparation_and_user_prompt(setup):
    service, _, workspace, *_ = setup
    draft = proposal(setup)
    service.agent_release = {**service.agent_release, "fingerprint": "old-loaded-engine"}
    asked = []

    class Client:
        def agent(self, operation, **payload):
            return service.agent_request(operation, payload)

        def command(self, *args, **kwargs):
            raise AssertionError("Mismatched connector must not prepare files")

    async def answer_from_user(context, params):
        asked.append(params)
        return types.ElicitResult(action="decline")

    async def run():
        async with create_connected_server_and_client_session(
                build_server(Client()), elicitation_callback=answer_from_user) as session:
            for name, arguments in [
                ("prepare_call_allies_choices", {"workspace_id": workspace["id"],
                    "index_id": draft["index_id"], "issue_id": draft["issue_id"]}),
                ("ask_about_changes", {"workspace_id": workspace["id"], "proposal_id": draft["id"]}),
                ("make_selected_files", {"workspace_id": workspace["id"], "proposal_id": draft["id"]}),
            ]:
                result = await session.call_tool(name, arguments)
                assert result.isError and "same installed update" in result.content[0].text
    asyncio.run(run())
    assert not asked
    assert not service.store.list("agent_question")


def test_tool_annotations_distinguish_reads_from_managed_writes():
    async def run():
        async with create_connected_server_and_client_session(build_server(object())) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert len(tools) == 33
            assert tools["get_context"].inputSchema["properties"]["selection"]["enum"] == ["current", "resume"]
            assert tools["get_concern_evidence"].inputSchema["properties"]["limit"]["maximum"] == 4
            assert "needs_game_test" in tools["record_concern_review"].inputSchema["properties"]["state"]["enum"]
            for name in ("read_source", "search_knowledge", "investigate_change", "get_progress",
                         "read_sources", "list_concerns", "get_concern_evidence", "get_investigation_report"):
                assert tools[name].annotations.readOnlyHint
            for name in ("get_context", "check_playset", "remember_progress", "make_selected_files",
                         "record_concern_review", "find_missing_mod_candidates", "inspect_mod_candidate", "set_version_preference"):
                assert not tools[name].annotations.readOnlyHint
            assert all(tool.annotations.openWorldHint is False for tool in tools.values())
    asyncio.run(run())


def test_update_during_native_choice_requires_fresh_review(setup):
    service, flow, workspace, *_ = setup
    draft = proposal(setup)

    class Client:
        def agent(self, operation, **payload):
            return service.agent_request(operation, payload)

        def connector_key(self):
            raise AssertionError("An answer from a mismatched release must not be signed")

    async def answer_after_update(context, params):
        service.agent_release = {**service.agent_release, "fingerprint": "updated-while-user-was-reading"}
        choices = params.requestedSchema["properties"]["choice"]["enum"]
        return types.ElicitResult(action="accept", content={"choice": choices[0]})

    async def run():
        async with create_connected_server_and_client_session(
                build_server(Client()), elicitation_callback=answer_after_update) as session:
            result = await session.call_tool("ask_about_changes", {
                "workspace_id": workspace["id"], "proposal_id": draft["id"]})
            assert result.isError and "same installed update" in result.content[0].text
    asyncio.run(run())
    assert flow.proposal(workspace["id"], draft["id"])["state"] == "awaiting_choice"
    assert all(question["state"] == "pending" for question in service.store.list("agent_question"))


def test_empty_path_query_lists_sources_but_empty_text_is_rejected(setup):
    service, _, workspace, index_id, _ = setup

    class Client:
        def agent(self, operation, **payload):
            return service.agent_request(operation, payload)

    async def run():
        async with create_connected_server_and_client_session(build_server(Client())) as session:
            args = {"workspace_id": workspace["id"], "index_id": index_id, "query": "", "kind": "path"}
            result = await session.call_tool("search_sources", args)
            assert not result.isError, result
            page = json.loads(result.content[0].text)
            assert page["total"] >= 4 and page["results"]
            refused = await session.call_tool("search_sources", {**args, "kind": "text"})
            assert refused.isError and "nonempty" in refused.content[0].text
    asyncio.run(run())
