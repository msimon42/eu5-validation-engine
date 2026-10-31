"""Owned installation generations, failure recovery and release consistency."""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

from backend.agent import install as installer
from backend.agent import release


class FakeCodex:
    def __init__(self, config):
        self.config = config
        self.connections = {"unrelated": {"preserve": True}}
        self.fail_add = None

    def sync(self):
        data = tomllib.loads(self.config.read_text()) if self.config.exists() else {}
        item = data.get("mcp_servers", {}).get(installer.NAME)
        if item is None:
            self.connections.pop(installer.NAME, None)
        else:
            fields = {key: item.get(key) for key in ("command", "args", "env", "cwd", "env_vars")}
            fields.update(type="stdio")
            self.connections[installer.NAME] = {"name": installer.NAME, "transport": fields,
                **{key: item[key] for key in ("enabled", "enabled_tools", "disabled_tools", "startup_timeout_sec", "tool_timeout_sec") if key in item}}

    def save(self):
        import tomlkit
        document = tomlkit.parse(self.config.read_text()) if self.config.exists() else tomlkit.document()
        item = self.connections[installer.NAME]
        server = document.setdefault("mcp_servers", tomlkit.table()).setdefault(installer.NAME, tomlkit.table())
        for key, value in item["transport"].items():
            if key != "type" and value is not None:
                server[key] = value
        for key, value in item.items():
            if key not in {"name", "transport"}:
                server[key] = value
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(tomlkit.dumps(document))
        self.sync()

    def run(self, args, **kwargs):
        operation, name = args[2:4]
        if operation == "get":
            self.sync()
            value = self.connections.get(name)
            return SimpleNamespace(returncode=0 if value else 1,
                stdout=json.dumps(value) if value else "", stderr="" if value else f"No MCP server named '{name}' found.")
        if operation == "remove":
            self.connections.pop(name, None)
        elif operation == "add":
            split = args.index("--")
            env = dict(value.split("=", 1) for value in args[5:split:2])
            value = {"name": name, "transport": {"type": "stdio", "command": args[split + 1],
                "args": args[split + 2:], "env": env or None}}
            failure, self.fail_add = self.fail_add, None
            if failure != "before":
                self.connections[name] = value
            if failure:
                return SimpleNamespace(returncode=1, stdout="", stderr="simulated registration failure")
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    parent = tmp_path / "skills"
    root = tmp_path / "managed"
    files = {"SKILL.md": b"new instructions\n", "agents/openai.yaml": b"new metadata\n",
             "references/operating-guide.md": b"new complete guide\n"}
    info = {"version": "test-v2", "fingerprint": "f" * 64,
        "workflow_files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
        "knowledge_files": {"data/knowledge.json": "a" * 64}, "implementation_files": {"server.py": "b" * 64}}
    fake = FakeCodex(tmp_path / "codex/config.toml")
    monkeypatch.setattr(installer, "workflow_files", lambda: dict(files))
    monkeypatch.setattr(installer, "release_info", lambda: copy.deepcopy(info))
    monkeypatch.setattr(installer.shutil, "which", lambda value: "/fake/codex")
    monkeypatch.setattr(installer.subprocess, "run", fake.run)
    monkeypatch.setattr(installer, "_codex_config_path", lambda: fake.config)
    write_config = installer._write_config

    def write(plan, *, restore=False):
        failure = None if restore else fake.fail_add
        if not restore:
            fake.fail_add = None
        if failure == "before":
            raise ValueError("Codex could not save the CK3 connection settings.")
        write_config(plan, restore=restore)
        fake.sync()
        if failure:
            raise ValueError("Codex could not save the CK3 connection settings.")

    monkeypatch.setattr(installer, "_write_config", write)
    return parent, root, files, info, fake


def old_install(setup):
    parent, root, _, _, fake = setup
    target = parent / "ck3-mod-agent"
    (target / "agents").mkdir(parents=True)
    (target / "references/empty").mkdir(parents=True)
    (target / installer.MARKER).write_bytes(release.OWNER_MARKER)
    (target / "SKILL.md").write_bytes(b"old instructions")
    (target / "agents/openai.yaml").write_bytes(b"old metadata")
    (target / "personal-note.txt").write_bytes(b"keep this unrelated file")
    (target / "personal-note.txt").chmod(0o700)
    fake.connections[installer.NAME] = {"name": installer.NAME,
        "transport": {"type": "stdio", "command": "/old/python", "args": [
            "-m", "backend.cli", "agent-tools", "--data-dir", str(root)], "env": None}}
    fake.save()
    return target


def test_complete_install_and_legacy_upgrade_keep_unrelated_content(setup):
    parent, root, files, info, fake = setup
    target = old_install(setup)
    result = installer.install(root, skill_parent=parent)
    assert result["installed"] and result["fingerprint"] == info["fingerprint"]
    assert all((target / name).read_bytes() == raw for name, raw in files.items())
    assert (target / "personal-note.txt").read_bytes() == b"keep this unrelated file"
    if os.name != "nt":
        assert (target / "personal-note.txt").stat().st_mode & 0o777 == 0o700
    assert (target / "references/empty").is_dir()
    assert fake.connections["unrelated"] == {"preserve": True}
    env = fake.connections[installer.NAME]["transport"]["env"]
    assert env["CK3_MOD_AGENT_EXPECTED_RELEASE"] == info["fingerprint"]
    assert env["CK3_MOD_AGENT_SKILL_PATH"] == str(target)
    assert not (parent / installer.JOURNAL).exists()
    assert installer.install(root, skill_parent=parent)["installed"]


def test_fresh_install_does_not_require_an_existing_skill(setup):
    parent, root, files, _, fake = setup
    result = installer.install(root, skill_parent=parent)
    assert all((Path(result["skill_path"]) / name).read_bytes() == raw for name, raw in files.items())
    config = tomllib.loads(fake.config.read_text())
    server = config["mcp_servers"][installer.NAME]
    assert set(server["tools"]) == set(installer.SAFE_TOOL_APPROVALS)
    assert all(value == {"approval_mode": "approve"} for value in server["tools"].values())
    assert "default_tools_approval_mode" not in server
    assert "approval_policy" not in config
    assert set(result["approved_housekeeping_tools"]) == set(installer.SAFE_TOOL_APPROVALS)


def test_upgrade_preserves_custom_settings_comments_and_explicit_tool_policies(setup):
    parent, root, _, _, fake = setup
    old_install(setup)
    original = fake.config.read_bytes()
    prefix = b'''# user's own settings\nmodel = 'local-model' # keep this comment\ncustom = """a multiline value\n[mcp_servers.not_a_table]\n"""\n\n'''
    suffix = b'''\n# only this user's stricter tool policy applies\n[mcp_servers.ck3_mod_agent.tools.get_context]\napproval_mode = "prompt" # leave as chosen\ncustom_setting = 7\n\n[mcp_servers.ck3_mod_agent.tools.check_playset]\napproval_mode = "writes"\n\n[mcp_servers.ck3_mod_agent.tools.make_changes]\napproval_mode = "prompt"\n\n[mcp_servers.unrelated]\ncommand = "/different/program" # another connection\nargs = [ 'a', 'b' ]\n'''
    original = original.replace(b'command = "/old/python"', b'command = "/old/python"\ntool_timeout_sec = 120\nenabled_tools = ["get_context"]\ncwd = "/custom/directory"\nenv_vars = ["CUSTOM_VARIABLE"]')
    fake.config.write_bytes(prefix + original + suffix)
    result = installer.install(root, skill_parent=parent)
    raw = fake.config.read_bytes()
    assert raw.startswith(prefix)
    policy_bytes, unrelated_bytes = suffix.split(b'[mcp_servers.unrelated]')
    assert policy_bytes in raw
    assert b'[mcp_servers.unrelated]' + unrelated_bytes in raw
    server = tomllib.loads(raw.decode())["mcp_servers"][installer.NAME]
    assert server["tool_timeout_sec"] == 120
    assert server["enabled_tools"] == ["get_context"]
    assert server["cwd"] == "/custom/directory"
    assert server["env_vars"] == ["CUSTOM_VARIABLE"]
    assert server["tools"]["get_context"] == {"approval_mode": "prompt", "custom_setting": 7}
    assert server["tools"]["check_playset"]["approval_mode"] == "writes"
    assert server["tools"]["make_changes"]["approval_mode"] == "prompt"
    assert len(result["approved_housekeeping_tools"]) == len(installer.SAFE_TOOL_APPROVALS) - 2


@pytest.mark.parametrize("default", ["prompt", "writes", "auto"])
def test_explicit_server_policy_does_not_gain_more_permissive_tool_overrides(setup, default):
    parent, root, _, _, fake = setup
    old_install(setup)
    before = fake.config.read_text().replace('[mcp_servers.ck3_mod_agent]',
        f'[mcp_servers.ck3_mod_agent]\ndefault_tools_approval_mode = "{default}"')
    fake.config.write_text(before)
    result = installer.install(root, skill_parent=parent)
    server = tomllib.loads(fake.config.read_text())["mcp_servers"][installer.NAME]
    assert server["default_tools_approval_mode"] == default
    assert "tools" not in server
    assert result["approved_housekeeping_tools"] == []
    assert result["preserved_tool_approval_policies"] == list(installer.SAFE_TOOL_APPROVALS)


def test_new_packaged_reference_does_not_overwrite_unrelated_existing_file(setup):
    parent, root, _, _, _ = setup
    target = old_install(setup)
    local = target / "references/operating-guide.md"
    local.write_bytes(b"the user's own reference")
    with pytest.raises(ValueError, match="unrelated installed file"):
        installer.install(root, skill_parent=parent)
    assert local.read_bytes() == b"the user's own reference"


def test_update_preserves_user_edits_to_previously_installed_workflow(setup):
    parent, root, _, _, _ = setup
    installer.install(root, skill_parent=parent)
    target = parent / "ck3-mod-agent"
    (target / "SKILL.md").write_bytes(b"the user's customized instructions")
    with pytest.raises(ValueError, match="changed outside setup"):
        installer.install(root, skill_parent=parent)
    assert (target / "SKILL.md").read_bytes() == b"the user's customized instructions"


@pytest.mark.parametrize("kind", ["skill", "connector"])
def test_unrelated_named_installation_or_custom_connection_is_not_overwritten(setup, kind):
    parent, root, _, _, fake = setup
    target = old_install(setup)
    if kind == "skill":
        (target / installer.MARKER).unlink()
    elif kind == "connector":
        fake.connections[installer.NAME]["transport"]["args"] = ["unrelated-service"]
        fake.save()
    before = installer._manifest(installer._tree(target))
    connection = copy.deepcopy(fake.connections)
    with pytest.raises(ValueError):
        installer.install(root, skill_parent=parent)
    assert installer._manifest(installer._tree(target)) == before
    assert fake.connections == connection


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_installed_links_are_rejected_without_touching_their_targets(setup, tmp_path, kind):
    parent, root, _, _, _ = setup
    target = old_install(setup)
    original = tmp_path / "original"
    original.write_bytes(b"never alter this")
    installed = target / "personal-note.txt"
    installed.unlink()
    if kind == "symlink":
        installed.symlink_to(original)
    else:
        installed.hardlink_to(original)
    with pytest.raises(ValueError):
        installer.install(root, skill_parent=parent)
    assert original.read_bytes() == b"never alter this"
    assert (target / "SKILL.md").read_bytes() == b"old instructions"


@pytest.mark.parametrize("failure", ["before", "after"])
def test_registration_failure_restores_exact_previous_generation_and_connection(setup, failure):
    parent, root, _, _, fake = setup
    target = old_install(setup)
    previous = installer._manifest(installer._tree(target))
    connection = copy.deepcopy(fake.connections)
    fake.config.write_bytes(b'# user settings\n' + fake.config.read_bytes() + b'\n[mcp_servers.other]\ncommand = "/other" # leave untouched\n')
    config = fake.config.read_bytes()
    fake.fail_add = failure
    with pytest.raises(ValueError, match="could not save"):
        installer.install(root, skill_parent=parent)
    assert installer._manifest(installer._tree(target)) == previous
    assert fake.connections == connection
    assert fake.config.read_bytes() == config
    assert not (parent / installer.JOURNAL).exists()


def test_failed_directory_publication_restores_complete_previous_generation(setup, monkeypatch):
    parent, root, _, _, _ = setup
    target = old_install(setup)
    previous = installer._manifest(installer._tree(target))
    rename = installer.os.rename
    failed = False

    def fail_stage(source, destination):
        nonlocal failed
        if ".stage." in str(source) and not failed:
            failed = True
            raise OSError("simulated publication failure")
        return rename(source, destination)

    monkeypatch.setattr(installer.os, "rename", fail_stage)
    with pytest.raises(OSError, match="publication"):
        installer.install(root, skill_parent=parent)
    assert installer._manifest(installer._tree(target)) == previous
    assert not (parent / installer.JOURNAL).exists()


def test_interrupted_update_recovers_before_next_install(setup, monkeypatch):
    parent, root, files, _, _ = setup
    target = old_install(setup)
    register = installer._register
    monkeypatch.setattr(installer, "_register", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        installer.install(root, skill_parent=parent)
    assert (parent / installer.JOURNAL).is_file()
    monkeypatch.setattr(installer, "_register", register)
    assert installer.install(root, skill_parent=parent)["installed"]
    assert all((target / name).read_bytes() == raw for name, raw in files.items())
    assert (target / "personal-note.txt").read_bytes() == b"keep this unrelated file"
    assert not (parent / installer.JOURNAL).exists()


def test_intervening_edit_is_retained_with_recovery_record(setup, monkeypatch):
    parent, root, _, _, _ = setup
    target = old_install(setup)

    def external_edit(*args):
        (target / "SKILL.md").write_bytes(b"user edited during setup")
        raise ValueError("simulated failure")

    monkeypatch.setattr(installer, "_register", external_edit)
    with pytest.raises(ValueError, match="needs recovery"):
        installer.install(root, skill_parent=parent)
    assert (target / "SKILL.md").read_bytes() == b"user edited during setup"
    assert (parent / installer.JOURNAL).exists()
    assert any(parent.glob(".ck3-mod-agent.backup.*"))


def test_intervening_settings_edit_is_preserved_with_recovery_copies(setup, monkeypatch):
    parent, root, _, _, fake = setup
    old_install(setup)
    register = installer._register
    changed = None

    def external_edit(*args):
        nonlocal changed
        register(*args)
        changed = fake.config.read_bytes() + b'\n# user edited during installation\n'
        fake.config.write_bytes(changed)
        raise ValueError("simulated failure")

    monkeypatch.setattr(installer, "_register", external_edit)
    with pytest.raises(ValueError, match="needs recovery"):
        installer.install(root, skill_parent=parent)
    assert fake.config.read_bytes() == changed
    assert (parent / installer.JOURNAL).exists()
    assert any(parent.glob(".ck3-mod-agent.backup.*"))


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_shared_or_linked_codex_settings_are_not_replaced(setup, tmp_path, kind):
    parent, root, _, _, fake = setup
    target = old_install(setup)
    original = tmp_path / "original-config"
    fake.config.rename(original)
    raw = original.read_bytes()
    if kind == "symlink":
        fake.config.symlink_to(original)
    else:
        fake.config.hardlink_to(original)
    with pytest.raises(ValueError):
        installer.install(root, skill_parent=parent)
    assert original.read_bytes() == raw
    assert (target / "SKILL.md").read_bytes() == b"old instructions"


def test_installed_release_reports_modified_instructions_and_engine_mismatch(setup, monkeypatch):
    parent, root, _, info, _ = setup
    installed = installer.install(root, skill_parent=parent)
    monkeypatch.setattr(release, "release_info", lambda: copy.deepcopy(info))
    target = Path(installed["skill_path"])
    assert release.installation_status(target, info["fingerprint"])["status"] == "ready"
    (target / "SKILL.md").write_bytes(b"changed")
    status = release.installation_status(target, "wrong-release")
    assert status["status"] == "mismatch" and len(status["problems"]) == 2


def test_release_fingerprint_is_location_independent_and_ignores_bytecode(tmp_path, monkeypatch):
    package = tmp_path / "package"
    (package / "data").mkdir(parents=True)
    (package / "data/knowledge.json").write_bytes(b'{"revision":1}')
    (package / "server.py").write_bytes(b"implementation")
    (package / "__pycache__").mkdir()
    (package / "__pycache__/server.pyc").write_bytes(b"bytecode")
    monkeypatch.setattr(release.resources, "files", lambda name: package)
    one, two = tmp_path / "one", tmp_path / "two"
    for path in (one, two):
        (path / "agents").mkdir(parents=True)
        (path / "references").mkdir()
        (path / "SKILL.md").write_bytes(b"workflow")
        (path / "agents/openai.yaml").write_bytes(b"metadata")
        (path / "references/guide.md").write_bytes(b"reference")
    first = release.release_info(workflow_root=one)
    assert first == release.release_info(workflow_root=two)
    (package / "__pycache__/server.pyc").write_bytes(b"different generated bytecode")
    assert release.release_info(workflow_root=one) == first
    (package / "data/knowledge.json").write_bytes(b'{"revision":2}')
    assert release.release_info(workflow_root=one)["fingerprint"] != first["fingerprint"]
