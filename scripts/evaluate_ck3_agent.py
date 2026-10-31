"""Opt-in actual Codex conversations against disposable synthetic CK3 sources.

Usage: uv run python scripts/evaluate_ck3_agent.py create
       uv run python scripts/evaluate_ck3_agent.py run /tmp/... check|resume|candidate
No game executable is created or launched. The caller controls model access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "tests")]


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def create():
    from backend.agent.release import release_info, workflow_files, RECEIPT, OWNER_MARKER
    from backend.app.service import Service
    from test_ck3_service import installation
    from test_ck3_discovery import database

    root = Path(tempfile.mkdtemp(prefix="ck3-codex-v3-")).resolve()
    options, user = installation(root / "sources", "macos")
    steam = Path(options["steam_roots"][0])
    settings = steam / "steamapps/common/Crusader Kings III/launcher/launcher-settings.json"
    settings.write_text(json.dumps({**json.loads(settings.read_text()), "rawVersion": "1.19.0.4"}))
    for name in ("one", "two"):
        descriptor = user / "mod" / f"{name}.mod"
        descriptor.write_text(descriptor.read_text() + 'supported_version="1.18.*"\n')
        localization = user / "mod" / name / "localization/english"
        localization.mkdir(parents=True)
        (localization / "labels_l_english.yml").write_text(f'l_english:\n clever:0 "{name} label"\n')
    registry = user / "mod/ugc_123456.mod"
    registry.write_text('name="Missing scenery"\nremote_file_id="123456"\npath="mod/absent"\n')
    candidate = steam / "steamapps/workshop/content/1158310/123456"
    (candidate / "common/traits").mkdir(parents=True)
    (candidate / "descriptor.mod").write_text('name="Missing scenery"\nremote_file_id="123456"\nsupported_version="1.19.*"\n')
    (candidate / "common/traits/scenery.txt").write_text("scenery = { diplomacy = 1 }\n")
    entries = [(f"mod/{name}.mod", user / "mod" / name, 1, n) for n, name in enumerate(("one", "two"))]
    entries.append(("mod/ugc_123456.mod", user / "mod/absent", 1, 2))
    database(user, entries).close()
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": [e[0] for e in entries]}))
    service = Service(root / "managed")
    try:
        workspace = service.create_workspace({"game_id": "ck3", "target_platform": "macos", "mode": "game",
                                              "name": "Disposable agent evaluation"})
        found = service._discover_ck3(workspace, options, lambda *args: None)
        service._import_ck3(workspace, {"discovery_id": found["discovery_id"]})
    finally:
        service.close()
    skill = root / "skill"
    for name, raw in workflow_files().items():
        target = skill / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (skill / ".mod-engine-owned").write_bytes(OWNER_MARKER)
    (skill / RECEIPT).write_text(json.dumps(release_info()))
    (root / "source-hashes-before.json").write_text(json.dumps(hashes(root / "sources"), indent=2))
    return root


def records(root):
    with sqlite3.connect((root / "managed/workspace.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        return [json.loads(r[0]) | {"record_kind": r[1]} for r in db.execute("SELECT payload,kind FROM records")]


def stop(root):
    from backend.agent.connection import EngineClient
    if not root.name.startswith("ck3-codex-v3-") or not (root / "source-hashes-before.json").is_file():
        raise SystemExit("This is not an owned disposable evaluation root.")
    client = EngineClient(root / "managed")
    try:
        if not client.attach():
            return
        if any(r["record_kind"] == "job" and r.get("state") in {"queued", "running"} for r in records(root)):
            raise SystemExit("An evaluation job is still active; finish it before restarting.")
        endpoint = json.loads((root / "managed/agent/engine.json").read_text())
        os.kill(endpoint["pid"], signal.SIGTERM)
        for _ in range(100):
            if not client.attach():
                return
            time.sleep(.1)
        raise SystemExit("The owned evaluation engine did not stop.")
    finally:
        client.close()


def refresh(root):
    from backend.agent.release import release_info, workflow_files, RECEIPT
    stop(root)
    for name, raw in workflow_files().items():
        target = root / "skill" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (root / "skill" / RECEIPT).write_text(json.dumps(release_info()))


def run(root, lane):
    from backend.agent.release import release_info
    prompts = {
        "check": "Validate my CK3 playset named Fixture active using the connected CK3 assistant. Start by checking what's available and reviewing one concern. Then stop so I can test resuming. Explain it in everyday language. Do not change my mods or launch a game.",
        "resume": "Continue validating my CK3 playset. Finish reviewing every remaining detected concern that can be assessed from the saved files, and record specifically what remains unknown. Explain the result in everyday language. Do not change my mods or launch a game.",
        "candidate": "I need to keep my current game version for my campaign. Inspect the matching copy of Missing scenery that you found as a separate alternative. Keep my actual playset unchanged. Explain the difference and save my version preference.",
    }
    prompt = prompts[lane]
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI is unavailable; no live conversation was run.")
    args = [codex, "exec", "--ephemeral", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--cd", str(root),
            "-c", "mcp_servers.ck3_mod_agent.command=" + json.dumps(sys.executable),
            "-c", "mcp_servers.ck3_mod_agent.cwd=" + json.dumps(str(REPO)),
            "-c", "mcp_servers.ck3_mod_agent.args=" + json.dumps(["-m", "backend.cli", "agent-tools", "--data-dir", str(root / "managed")]),
            "-c", "mcp_servers.ck3_mod_agent.env.CK3_MOD_AGENT_SKILL_PATH=" + json.dumps(str(root / "skill")),
            "-c", "mcp_servers.ck3_mod_agent.env.CK3_MOD_AGENT_EXPECTED_RELEASE=" + json.dumps(release_info()["fingerprint"]),
            "-o", str(root / f"{lane}-answer.txt"), "-"]
    before = records(root)
    started = time.monotonic()
    (root / f"{lane}-request.txt").write_text(prompt)
    with (root / f"{lane}-transcript.jsonl").open("w") as output, (root / f"{lane}-process.log").open("w") as errors:
        process = subprocess.run(args, input=prompt, text=True, stdout=output, stderr=errors, timeout=600, cwd=REPO)
    after = records(root)
    rows = [json.loads(line) for line in (root / f"{lane}-transcript.jsonl").read_text().splitlines()]
    calls = [r["item"] for r in rows if r.get("type") == "item.completed" and r.get("item", {}).get("type") == "mcp_tool_call"]
    def count(rows, kind):
        return sum(r["record_kind"] == kind for r in rows)
    summary = {"lane": lane, "exit_code": process.returncode, "seconds": round(time.monotonic() - started, 2),
               "tools": [c["tool"] for c in calls], "failed_tools": [c["tool"] for c in calls if c.get("status") == "failed"],
               "jobs_before": count(before, "job"), "jobs_after": count(after, "job"),
               "source_bytes_unchanged": hashes(root / "sources") == json.loads((root / "source-hashes-before.json").read_text()),
               "game_runs": 0, "model_override": False, "approval_bypass": False}
    (root / f"{lane}-result.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if process.returncode or not summary["source_bytes_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "run", "refresh", "stop"))
    parser.add_argument("root", type=Path, nargs="?")
    parser.add_argument("lane", choices=("check", "resume", "candidate"), nargs="?")
    args = parser.parse_args()
    if args.action == "create":
        print(create())
    elif args.root and args.action in {"refresh", "stop"}:
        {"refresh": refresh, "stop": stop}[args.action](args.root.resolve())
    elif args.root and args.lane:
        run(args.root.resolve(), args.lane)
    else:
        parser.error("run requires root and lane")
