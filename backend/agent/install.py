"""Publish a complete owned workflow generation and recover interrupted setup."""
from __future__ import annotations

import hashlib
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib

from backend.engine.safety import ManagedFS, ManagedLock, read_source_bytes, reject_link_components
from .release import OWNER_MARKER, RECEIPT, release_info, workflow_files

NAME = "ck3_mod_agent"
JOURNAL = ".ck3-mod-agent.install.json"
MARKER = ".mod-engine-owned"
SAFE_TOOL_APPROVALS = (
    "get_context", "list_missing_mods", "check_playset", "remember_progress", "search_knowledge",
    "read_knowledge", "search_sources", "read_source", "related_definitions", "investigate_change",
    "find_playsets", "use_playset", "scan_playset", "get_progress", "cancel_work", "examine_changes",
    "list_changes", "inspect_change", "resume_conversation",
    "read_sources", "list_concerns", "get_concern_evidence", "record_concern_review",
    "get_investigation_report", "find_missing_mod_candidates", "inspect_mod_candidate", "set_version_preference",
)


def _codex_config_path():
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"


def _config_bytes(path):
    path = reject_link_components(Path(path).absolute())
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Codex settings must be an unshared regular file; they were left untouched.")
    return read_source_bytes(path.parent, path.name, max_bytes=4 * 1024 * 1024, native_paths=True)


def _config_plan(connector, previous):
    """Preserve all other TOML while adding narrow defaults only where absent."""
    import tomlkit
    path = reject_link_components(_codex_config_path().absolute())
    before = _config_bytes(path)
    text = (before or b"").decode("utf-8")
    document = tomlkit.parse(text)
    if tomlkit.dumps(document) != text:
        raise ValueError("Codex settings cannot be edited without preserving their formatting.")
    decoded = tomllib.loads(text)
    local = decoded.get("mcp_servers", {}).get(NAME)
    if local is not None:
        local_transport = {key: local.get(key) for key in ("command", "args", "env", "cwd", "env_vars")}
        local_transport["type"] = "stdio" if "command" in local else "http"
        if _transport({"transport": local_transport}) != _transport(previous):
            raise ValueError("The active CK3 connection comes from different settings; the user configuration was left untouched.")
    elif previous is not None:
        raise ValueError("The active CK3 connection is not owned by this user configuration; it was left untouched.")
    servers = document.setdefault("mcp_servers", tomlkit.table())
    server = servers.setdefault(NAME, tomlkit.table())
    transport = _transport(connector)
    server["command"], server["args"] = transport["command"], transport["args"]
    environment = server.setdefault("env", tomlkit.table())
    for key, value in transport["env"].items():
        environment[key] = value
    added, preserved = [], []
    default = server.get("default_tools_approval_mode")
    if default is None or default == "approve":
        tool_settings = server.setdefault("tools", tomlkit.table())
        for name in SAFE_TOOL_APPROVALS:
            settings = tool_settings.setdefault(name, tomlkit.table())
            if "approval_mode" in settings:
                preserved.append(name)
            else:
                settings["approval_mode"] = "approve"
                added.append(name)
    else:
        preserved = list(SAFE_TOOL_APPROVALS)
    after = tomlkit.dumps(document).encode("utf-8")
    parsed = tomllib.loads(after.decode("utf-8"))
    expected = copy.deepcopy(decoded)
    wanted = expected.setdefault("mcp_servers", {}).setdefault(NAME, {})
    wanted.update(command=transport["command"], args=transport["args"])
    wanted.setdefault("env", {}).update(transport["env"])
    for name in added:
        wanted.setdefault("tools", {}).setdefault(name, {})["approval_mode"] = "approve"
    if parsed != expected:
        raise ValueError("The proposed settings update changes unrelated values; it was refused.")
    return {"path": str(path), "before": base64.b64encode(before).decode() if before is not None else None,
            "after": base64.b64encode(after).decode(), "before_sha256": _hash(before) if before is not None else None,
            "after_sha256": _hash(after), "added_tool_policies": added, "preserved_tool_policies": preserved}


def _config_value(plan, key):
    raw = base64.b64decode(plan[key], validate=True) if plan[key] is not None else None
    if (_hash(raw) if raw is not None else None) != plan[key + "_sha256"]:
        raise ValueError("The settings recovery record changed; no settings were written.")
    return raw


def _write_config(plan, *, restore=False):
    path = reject_link_components(Path(plan["path"]))
    expected, replacement = (_config_value(plan, key) for key in (("after", "before") if restore else ("before", "after")))
    if _config_bytes(path) != expected:
        raise ValueError("Codex settings changed during installation; intervening edits were preserved.")
    if replacement is None:
        path.unlink()
    else:
        ManagedFS(path.parent, max_bytes=4 * 1024 * 1024).write_bytes(path.name, replacement)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _tree(root):
    """Read a bounded, link-free generation before copying or replacing it."""
    files, directories, modes, total = {}, [], {}, 0
    if not root.exists():
        return files, directories, modes
    reject_link_components(root)
    modes["."] = stat.S_IMODE(root.stat().st_mode)
    for path in sorted(root.rglob("*")):
        reject_link_components(path)
        info = path.stat()
        name = path.relative_to(root).as_posix()
        modes[name] = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            directories.append(name)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            raw = read_source_bytes(root, name, max_bytes=4 * 1024 * 1024, native_paths=True)
            total += len(raw)
            files[name] = raw
        else:
            raise ValueError("The installed workflow contains a link or unsupported file; it was left untouched.")
        if len(files) + len(directories) > 1000 or total > 16 * 1024 * 1024:
            raise ValueError("The existing workflow is too large for a safe automatic update.")
    return files, directories, modes


def _manifest(tree):
    files, directories, modes = tree
    return {"files": {name: _hash(raw) for name, raw in files.items()}, "directories": directories, "modes": modes}


def _previous_owned(files):
    if RECEIPT not in files:
        return {"SKILL.md": None, "agents/openai.yaml": None}
    try:
        owned = json.loads(files[RECEIPT])["workflow_files"]
        if not isinstance(owned, dict):
            raise ValueError
        for name, checksum in owned.items():
            if not (name in {"SKILL.md", "agents/openai.yaml"} or name.startswith("references/")):
                raise ValueError
            if name not in files or _hash(files[name]) != checksum:
                raise ValueError
        return owned
    except (ValueError, TypeError, KeyError):
        raise ValueError("Installed instructions were changed outside setup. They were preserved; restore or save those edits before updating.") from None


def _connector(executable):
    result = subprocess.run([executable, "mcp", "get", NAME, "--json"], capture_output=True, text=True, check=False)
    if result.returncode:
        if "No MCP server named" in result.stderr and NAME in result.stderr:
            return None
        raise ValueError("Codex connection settings could not be inspected; nothing was replaced.")
    try:
        value = json.loads(result.stdout)
        if value.get("name") != NAME or not isinstance(value.get("transport"), dict):
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise ValueError("Codex returned unreadable connection settings; nothing was replaced.") from exc


def _transport(value):
    if value is None:
        return None
    transport = value["transport"]
    return {"type": transport.get("type"), "command": transport.get("command"),
            "args": transport.get("args") or [], "env": transport.get("env") or {},
            "cwd": transport.get("cwd"), "env_vars": transport.get("env_vars") or []}


def _check_owned_connector(previous, owned):
    if previous is None:
        return
    transport = _transport(previous)
    args = transport["args"]
    if (not owned or transport["type"] != "stdio" or len(args) != 5 or
            args[:4] != ["-m", "backend.cli", "agent-tools", "--data-dir"] or
            not Path(args[4]).is_absolute() or not Path(transport["command"]).is_absolute()):
        raise ValueError("A different connection already uses the CK3 assistant's name; it was left untouched.")


def _register(executable, value, config_update=None):
    if config_update is not None:
        _write_config(config_update)
        return
    if value is None:
        result = subprocess.run([executable, "mcp", "remove", NAME], capture_output=True, text=True, check=False)
    else:
        transport = _transport(value)
        args = [executable, "mcp", "add", NAME]
        for key, val in sorted(transport["env"].items()):
            args.extend(["--env", key + "=" + val])
        args.extend(["--", transport["command"], *transport["args"]])
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Codex could not save the CK3 connection settings.")


def _generation_path(parent, name, kind):
    if (not isinstance(name, str) or Path(name).name != name or
            not name.startswith(".ck3-mod-agent." + kind + ".")):
        raise ValueError("The setup recovery record has an invalid generation path.")
    return reject_link_components(parent / name)


def _remove_generation(path, expected):
    if path.exists():
        if _manifest(_tree(path)) != expected:
            raise ValueError("An installation generation changed outside setup; its files were preserved.")
        shutil.rmtree(path)


def _recover(parent, executable):
    fs = ManagedFS(parent)
    if not fs.resolve(JOURNAL).exists():
        return
    record = json.loads(fs.read_bytes(JOURNAL))
    if record.get("format") != "ck3-install-1":
        raise ValueError("The setup recovery record is not recognized.")
    target = parent / "ck3-mod-agent"
    stage = _generation_path(parent, record["stage"], "stage")
    backup = _generation_path(parent, record["backup"], "backup")
    current = _connector(executable)
    config_update = record.get("config_update")
    if config_update:
        current_config = _config_bytes(Path(config_update["path"]))
        if current_config not in (_config_value(config_update, "before"), _config_value(config_update, "after")):
            raise ValueError("Codex settings changed during setup. Recovery preserved those edits.")
    if _transport(current) not in (_transport(record["previous_connector"]), _transport(record["connector"])):
        raise ValueError("The CK3 connection changed during setup. Recovery left it untouched.")
    if record.get("phase") == "complete":
        if _manifest(_tree(target)) != record["new_manifest"] or _transport(current) != _transport(record["connector"]):
            raise ValueError("The completed installation changed before cleanup; its recovery copies were preserved.")
        if config_update and current_config != _config_value(config_update, "after"):
            raise ValueError("The completed tool settings changed before cleanup; recovery copies were preserved.")
    else:
        if config_update and current_config == _config_value(config_update, "after"):
            _write_config(config_update, restore=True)
        elif not config_update and _transport(current) != _transport(record["previous_connector"]):
            _register(executable, record["previous_connector"])
        if backup.exists():
            if _manifest(_tree(backup)) != record["old_manifest"]:
                raise ValueError("The previous workflow changed during setup; its files were preserved.")
            if target.exists():
                _remove_generation(target, record["new_manifest"])
            os.rename(backup, target)
        elif not record["had_previous"] and target.exists():
            _remove_generation(target, record["new_manifest"])
        elif record["had_previous"] and _manifest(_tree(target)) != record["old_manifest"]:
            raise ValueError("The previous workflow cannot be restored automatically; recovery files were preserved.")
    _remove_generation(stage, record["new_manifest"])
    _remove_generation(backup, record["old_manifest"])
    fs.resolve(JOURNAL).unlink()


def install(data_dir, *, codex="codex", skill_parent=None):
    root = reject_link_components(Path(data_dir).absolute())
    executable = shutil.which(codex)
    if not executable:
        raise ValueError("Codex could not be found. No workflow or connection settings were changed.")
    shipped = workflow_files()
    release = release_info()
    if {name: _hash(raw) for name, raw in shipped.items()} != release["workflow_files"]:
        raise ValueError("The packaged instructions changed during setup; try again after the update finishes.")
    if not release["knowledge_files"]:
        raise ValueError("The packaged CK3 reference library is missing. Reinstall the assistant package.")
    parent = Path(skill_parent) if skill_parent else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    parent = reject_link_components(parent.absolute())
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / ".ck3-mod-agent.install.lock"
    if lock.exists() and (not lock.is_file() or lock.stat().st_nlink != 1):
        raise ValueError("The installation lock is unsafe; nothing was changed.")
    with ManagedLock(lock):
        _recover(parent, executable)
        target = reject_link_components(parent / "ck3-mod-agent")
        old_tree = _tree(target)
        old_files, directories, modes = old_tree
        owned = old_files.get(MARKER) == OWNER_MARKER
        if target.exists() and not owned:
            raise ValueError("An existing skill with this name is not owned by this installer; it was left untouched.")
        previous = _connector(executable)
        _check_owned_connector(previous, owned)
        env = dict((_transport(previous) or {}).get("env", {}))
        env.update(CK3_MOD_AGENT_EXPECTED_RELEASE=release["fingerprint"], CK3_MOD_AGENT_SKILL_PATH=str(target))
        connector = copy.deepcopy(previous) if previous else {"name": NAME, "transport": {"type": "stdio"}}
        connector["transport"].update(command=sys.executable,
            args=["-m", "backend.cli", "agent-tools", "--data-dir", str(root)], env=env)
        config_update = _config_plan(connector, previous)
        receipt = {**release, "data_dir": str(root), "connector": connector}
        files = dict(old_files)
        previous_owned = _previous_owned(old_files)
        if any(name in old_files and name not in previous_owned for name in shipped):
            raise ValueError("A new workflow file would replace an unrelated installed file; it was left untouched.")
        for name in previous_owned:
            files.pop(name, None)
        files.update(shipped)
        files.update({MARKER: OWNER_MARKER, RECEIPT: (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()})
        stage = Path(tempfile.mkdtemp(prefix=".ck3-mod-agent.stage.", dir=parent))
        backup = parent / stage.name.replace(".stage.", ".backup.", 1)
        staged_fs = ManagedFS(stage)
        fs = ManagedFS(parent)
        try:
            for directory in directories:
                staged_fs.resolve(directory).mkdir(parents=True, exist_ok=True)
            for name, raw in files.items():
                staged_fs.write_bytes(name, raw, replace=False)
            for name in old_files.keys() - previous_owned.keys() - {MARKER, RECEIPT}:
                os.chmod(staged_fs.resolve(name), modes[name])
            for name in sorted(directories, key=lambda name: name.count("/"), reverse=True):
                os.chmod(staged_fs.resolve(name), modes[name])
            if "." in modes:
                os.chmod(stage, modes["."])
            record = {"format": "ck3-install-1", "phase": "prepared", "stage": stage.name,
                "backup": backup.name, "had_previous": target.exists(), "previous_connector": previous,
                "connector": connector, "config_update": config_update,
                "old_manifest": _manifest(old_tree), "new_manifest": _manifest(_tree(stage))}
            fs.write_bytes(JOURNAL, json.dumps(record).encode(), replace=False)
            if _manifest(_tree(target)) != record["old_manifest"] or _transport(_connector(executable)) != _transport(previous):
                raise ValueError("The existing setup changed during installation; it was not overwritten.")
            if target.exists():
                os.rename(target, backup)
            os.rename(stage, target)
            _register(executable, connector, config_update)
            if _transport(_connector(executable)) != _transport(connector):
                raise ValueError("Codex did not retain the requested CK3 connection settings.")
            fs.write_bytes(JOURNAL, json.dumps({**record, "phase": "complete"}).encode())
            _recover(parent, executable)
        except Exception:
            if fs.resolve(JOURNAL).exists():
                try:
                    _recover(parent, executable)
                except Exception:
                    raise ValueError("Assistant setup needs recovery. Existing files and recovery copies were retained; run setup again after resolving external changes.") from None
            elif stage.exists():
                shutil.rmtree(stage)
            raise
    return {"installed": True, "skill_path": str(target), "data_dir": str(root),
            "version": release["version"], "fingerprint": release["fingerprint"],
            "approved_housekeeping_tools": config_update["added_tool_policies"],
            "preserved_tool_approval_policies": config_update["preserved_tool_policies"],
            "message": "The CK3 assistant and references are installed together. Reconnect its tools to load this release; saved investigations are retained."}
