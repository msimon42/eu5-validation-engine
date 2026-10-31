"""Mac isolation qualification, separate from mod behavior or repair approval.

Preparing a probe never launches CK3. The operator must obtain explicit consent
before start_probe. Output creation and a clean log are not gameplay evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from backend.app.store import digest, uid
from backend.engine.safety import hash_source_file, reject_link_components


def policy_for(profile: Path, normal_data: Path):
    profile, normal_data = profile.absolute(), normal_data.absolute()
    if profile == normal_data or profile.is_relative_to(normal_data) or normal_data.is_relative_to(profile):
        raise ValueError("Test data and normal game data must be separate.")
    # The candidate userdir option is not trusted for isolation. The OS policy
    # denies ALL original writes even if CK3 ignores that option entirely.
    return '\n'.join(['(version 1)', '(allow default)', '(deny file-write*)',
        f'(allow file-write* (subpath {json.dumps(str(profile))}))',
        f'(deny file-read* (subpath {json.dumps(str(normal_data))}))', '(deny network*)', ''])


def normal_inventory(root):
    root = reject_link_components(Path(root))
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError("Normal game data contains a link; its isolation must be resolved before testing.")
        for name in sorted(files):
            path = Path(current) / name
            info = path.stat()
            result.append([path.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns, info.st_ino])
    return sorted(result)


def prepare_probe(store, discovery):
    if discovery.get("target_platform", discovery.get("platform")) != "macos" or sys.platform != "darwin":
        raise ValueError("This test setup currently requires its separate Mac qualification. Windows was not tested.")
    installation = discovery["installation"]
    executable = reject_link_components(Path(installation["executable"]))
    options = discovery.get("options", {})
    normal = options.get("user_data_path") or discovery.get("user_data")
    if not normal:
        raise ValueError("The normal game-data folder must be identified before making a test setup.")
    normal = reject_link_components(Path(normal))
    identifier = uid("isolation")
    prefix = "agent/tests/" + identifier
    for path, raw in [("profile/dlc_load.json", b'{"enabled_mods":[],"disabled_dlcs":[]}\n'),
                      ("profile/tmp/.keep", b""), ("profile/cache/.keep", b"")]:
        store.fs.write_bytes(prefix + "/" + path, raw, replace=False)
    profile = store.fs.resolve(prefix + "/profile")
    policy = policy_for(profile, normal).encode()
    store.fs.write_bytes(prefix + "/isolation.sb", policy, replace=False)
    checksum = hash_source_file(executable.parent, executable.name, native_paths=True)
    record = {"id": identifier, "workspace_id": discovery["workspace_id"], "game_id": "ck3",
        "target_platform": "macos", "state": "prepared", "game_launched": False,
        "executable": str(executable), "executable_sha256": checksum["sha256"],
        "content_root": installation["content_root"], "normal_data": str(normal), "prefix": prefix,
        "profile": str(profile), "policy_sha256": digest(policy), "normal_before": normal_inventory(normal),
        "argv": [str(executable), "-userdir=" + str(profile), "-gdpr-compliant"],
        "argument_status": "Candidate inspected in the installed binary, not executed or qualified.",
        "gameplay_outcome": "not_run", "mods_enabled": [], "network": "denied",
        "purpose": "Establish a separate game-data setup before testing any mod change."}
    store.fs.write_bytes(prefix + "/plan.json", json.dumps(record, indent=2).encode(), replace=False)
    return store.put("agent_isolation", record)


def check_os_boundary(store, record):
    """Negative control writes only disposable managed locations, never originals."""
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("The Mac process isolation tool is unavailable.")
    policy = store.fs.resolve(record["prefix"] + "/isolation.sb")
    if digest(store.fs.read_bytes(record["prefix"] + "/isolation.sb")) != record["policy_sha256"]:
        raise ValueError("The test isolation settings changed.")
    allowed = Path(record["profile"]) / "boundary-allowed"
    forbidden = store.root / record["prefix"] / "boundary-forbidden"
    program = ('from pathlib import Path\n'
        f'Path({str(allowed)!r}).write_text("probe")\n'
        'try:\n'
        f' Path({str(forbidden)!r}).write_text("must be denied")\n'
        'except PermissionError:\n print("write boundary enforced")\n'
        'else:\n raise SystemExit("write escaped test profile")\n')
    result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(policy), sys.executable, "-c", program],
        cwd=record["profile"], capture_output=True, timeout=30, check=False)
    if result.returncode != 0 or result.stdout.strip() != b"write boundary enforced" or forbidden.exists():
        raise ValueError("The process write boundary was not established. CK3 was not launched.")
    return {"executed": True, "kind": "os_write_boundary", "game_launched": False,
            "negative_control": "A write outside the private profile was denied.",
            "positive_control": "A write inside the private profile succeeded."}


def start_probe(store, identifier):
    """Operator entry point, called only after explicit approval of this probe."""
    record = store.get("agent_isolation", identifier)
    if record["state"] != "prepared":
        raise ValueError("This isolation probe was already started or changed.")
    executable = Path(record["executable"])
    if hash_source_file(executable.parent, executable.name, native_paths=True)["sha256"] != record["executable_sha256"]:
        raise ValueError("The game executable changed. Prepare a fresh test.")
    if normal_inventory(record["normal_data"]) != record["normal_before"]:
        raise ValueError("Normal game data changed after the test was prepared.")
    running = subprocess.run(["/bin/ps", "-axo", "comm="], capture_output=True, check=True).stdout.decode()
    if any(line.strip() == str(executable) for line in running.splitlines()):
        raise ValueError("CK3 is already running. It was not interrupted and a second game was not launched.")
    boundary = check_os_boundary(store, record)
    log_path = record["prefix"] + "/profile/process.log"
    store.fs.write_bytes(log_path, b"", replace=False)
    env = dict(os.environ)
    env.update(TMPDIR=record["profile"] + "/tmp", XDG_CACHE_HOME=record["profile"] + "/cache")
    with store.fs._parent(log_path) as (parent, name):
        descriptor = os.open(name, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
        with os.fdopen(descriptor, "ab") as log:
            process = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(store.fs.resolve(record["prefix"] + "/isolation.sb")),
                *record["argv"]], cwd=str(executable.parents[3]), env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    identity = process_identity(process.pid)
    return store.put("agent_isolation", {**record, "state": "running" if identity else "exited", "game_launched": True,
        "pid": process.pid, "process_identity": identity, "started_at": time.time(), "boundary_check": boundary})


def process_identity(pid):
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                            capture_output=True, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def probe_status(store, identifier):
    record = store.get("agent_isolation", identifier)
    profile = Path(record["profile"])
    created = [path.relative_to(profile).as_posix() for path in profile.rglob("*") if path.is_file()]
    unchanged = normal_inventory(record["normal_data"]) == record["normal_before"]
    return {"id": identifier, "state": record["state"], "game_launched": record["game_launched"],
        "created_files": created, "normal_data_metadata_unchanged": unchanged,
        "gameplay_outcome": "not_run", "qualification": "requires_direct_observation",
        "message": "Files created in the private profile do not establish that a mod feature works."}


def stop_probe(store, identifier):
    record = store.get("agent_isolation", identifier)
    if record["state"] != "running":
        return record
    # The process group belongs to this exact test, not another running game.
    identity = process_identity(record["pid"])
    if identity is None:
        return store.put("agent_isolation", {**record, "state": "exited", "finished_at": time.time()})
    if not record.get("process_identity") or identity != record["process_identity"] or os.getpgid(record["pid"]) != record["pid"]:
        raise ValueError("The test process identity changed; it was not stopped.")
    os.killpg(record["pid"], signal.SIGTERM)
    status = probe_status(store, identifier)
    return store.put("agent_isolation", {**record, "state": "stopped", "finished_at": time.time(),
        "normal_data_metadata_unchanged": status["normal_data_metadata_unchanged"], "gameplay_outcome": "not_run"})
