"""Real headless process + stdio MCP smoke, confined to a temporary empty library."""
import asyncio
import json
import os
import signal
import sys
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.agent.connection import EngineClient


def stop_owned(endpoint):
    try:
        os.kill(endpoint["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(100):
        try:
            httpx.get(endpoint["url"] + "/api/engine", timeout=.2, trust_env=False)
        except httpx.HTTPError:
            return
        time.sleep(.05)
    raise AssertionError("The owned temporary engine did not stop")


def test_two_connectors_and_stdio_share_one_headless_engine(tmp_path):
    root = tmp_path / "managed"
    one, two = EngineClient(root), EngineClient(root)
    endpoint = None
    try:
        one.ensure()
        endpoint = json.loads((root / "agent/engine.json").read_text())
        two.ensure()
        assert one.url == two.url == endpoint["url"]
        assert one.request("GET", "/api/engine")["id"] == endpoint["id"]
        assert httpx.get(one.url + "/", trust_env=False).status_code == 404
        created = one.command("create_workspace", payload={"game_id": "ck3", "target_platform": "macos",
            "mode": "game", "name": "Empty temporary test"})

        async def run():
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "backend.cli", "agent-tools", "--data-dir", str(root)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {"find_playsets", "list_changes", "ask_about_changes", "undo_selected_changes"} <= {
                        tool.name for tool in tools.tools}
                    result = await session.call_tool("resume_conversation", {"workspace_id": created["workspace_id"]})
                    assert not result.isError
                    assert json.loads(result.content[0].text)["state"] == "ready"
        asyncio.run(run())
        assert json.loads((root / "agent/engine.json").read_text())["id"] == endpoint["id"]
        previous = endpoint["id"]
        stop_owned(endpoint)
        persisted = one.request("GET", "/api/workspaces/" + created["workspace_id"])
        endpoint = json.loads((root / "agent/engine.json").read_text())
        assert endpoint["id"] != previous
        assert persisted["workspace"]["id"] == created["workspace_id"]
        assert two.agent("session", workspace_id=created["workspace_id"])["state"] == "ready"
    finally:
        one.close()
        two.close()
        if endpoint:
            stop_owned(endpoint)
