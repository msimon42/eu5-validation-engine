"""Read-only Windows discovery and evidence-oriented controlled probe harness.

No guessed CLI validator, playset writer, or synthetic-to-game execution bridge
is provided. Actual launching is disabled unless a backend explicitly supplies
the selected target and enables this worker.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Callable

from .evidence import canonical_bytes, validate_fingerprint
from .safety import ManagedFS, ManagedLock, hash_source_file, read_source_bytes, sha256_bytes


RECIPES = frozenset({"baseline", "individual", "stack", "repaired_stack", "loading_probe",
                     "log_sample", "manual_observation"})


def windows_documents() -> Path:
    if os.name != "nt":
        raise ValueError("Windows known-folder discovery is unavailable on this host")
    import uuid as uuid_module
    from ctypes import wintypes
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
    raw = uuid_module.UUID("fdd39ad0-238f-46af-adb4-6c85480369c7").bytes_le
    folder = GUID.from_buffer_copy(raw)
    pointer = ctypes.c_wchar_p()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    call = shell.SHGetKnownFolderPath
    call.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                     ctypes.POINTER(ctypes.c_wchar_p)]
    call.restype = ctypes.c_long
    if call(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) != 0:
        raise ValueError("Windows Documents known folder could not be resolved")
    try:
        return Path(pointer.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))


def _steam_registry_roots() -> list[Path]:
    if os.name != "nt":
        return []
    import winreg
    roots = []
    locations = [(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")]
    for hive, name, field in locations:
        try:
            with winreg.OpenKey(hive, name) as key:
                value, _ = winreg.QueryValueEx(key, field)
                roots.append(Path(value))
        except OSError:
            pass
    return roots


def discover(steam_roots: list[Path] | None = None, documents: Path | None = None) -> dict:
    """Inspect selected/registered roots without changing any game files."""
    native = os.name == "nt"
    roots = list(steam_roots) if steam_roots is not None else _steam_registry_roots()
    documents_path = Path(documents) if documents is not None else windows_documents() if native else None
    libraries: dict[str, Path] = {}
    diagnostics = []
    for raw in roots:
        root = Path(raw).absolute()
        libraries[str(root).casefold()] = root
        try:
            data = read_source_bytes(root, "steamapps/libraryfolders.vdf", 4 * 1024 * 1024)
        except (ValueError, OSError) as exc:
            diagnostics.append({"root": str(root), "reason": str(exc)})
            continue
        try:
            text = data.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            diagnostics.append({"root": str(root), "reason": "library manifest has unsupported encoding"})
            continue
        # A bounded read-only extractor for Valve quoted paths, not a serializer.
        for match in re.finditer(r'"path"\s*"((?:\\.|[^"\\])*)"', text):
            value = match.group(1).replace("\\\\", "\\").replace('\\"', '"')
            path = Path(value)
            if not path.is_absolute():
                diagnostics.append({"root": str(root), "reason": "relative Steam library ignored"})
                continue
            libraries[str(path).casefold()] = path
    inventories = []
    for library in libraries.values():
        game = library / "steamapps" / "common" / "Europa Universalis V"
        workshop = library / "steamapps" / "workshop" / "content"
        inventories.append({"library": str(library), "game_candidate": str(game),
                            "game_present": game.is_dir(), "workshop_content_root": str(workshop),
                            "workshop_present": workshop.is_dir(),
                            "identity_confirmed": False})
    user_data = documents_path / "Paradox Interactive" / "Europa Universalis V" if documents_path else None
    return {"platform": "windows" if native else "unsupported",
            "native_available": native, "synthetic_inspection": not native and bool(roots or documents),
            "libraries": inventories, "documents": str(documents_path) if documents_path else None,
            "user_data_candidate": str(user_data) if user_data else None,
            "user_data_present": bool(user_data and user_data.is_dir()),
            "playset_adapter": "read_only_unqualified", "active_state": "unknown",
            "diagnostics": diagnostics,
            "reason": None if native else "Native Windows discovery/game execution is unavailable on this host"}


def compare_logs(baseline: str, current: str) -> dict:
    """Compare exact diagnostic lines as multisets, retaining meaningful values."""
    before = Counter(line for line in baseline.splitlines() if line.strip())
    after = Counter(line for line in current.splitlines() if line.strip())
    changes = []
    for line in sorted(before.keys() | after.keys()):
        if before[line] != after[line]:
            changes.append({"message": line, "fingerprint": sha256_bytes(line.encode()),
                            "baseline_count": before[line], "current_count": after[line],
                            "delta": after[line] - before[line], "severity": "unknown"})
    return {"changes": changes, "baseline_lines": sum(before.values()),
            "current_lines": sum(after.values()), "normalization": "exact_lines_v1",
            "interpretation": "log differences do not prove loading or behavior preservation"}


def fingerprint_installation(executable: Path, *, content_roots: list[Path] | None = None,
                             docs_roots: list[Path] | None = None,
                             dlc_roots: list[Path] | None = None,
                             max_files: int = 2_000_000) -> dict:
    """Capture selected installed bytes; accepts any build/version without guesses.

    Missing generated docs and unknown DLC enabled state are recorded explicitly.
    No version string selects rules or grants production capabilities.
    """
    executable = Path(executable).absolute()
    exe = hash_source_file(executable.parent, executable.name)
    diagnostics, manifests = [], {}

    def inventory(root: Path) -> list[tuple]:
        result = []
        if not root.exists():
            return result
        if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("fingerprint root cannot be a link/reparse point")
        stack = [root]
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    relative = Path(entry.path).relative_to(root).as_posix()
                    if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise ValueError(f"link/reparse content retained as unsupported: {relative}")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        result.append((relative, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                                       info.st_dev, info.st_ino))
                        if len(result) > max_files:
                            raise ValueError("installation fingerprint file budget exceeded")
        return sorted(result)

    groups = {"content": content_roots if content_roots is not None else [executable.parent],
              "docs": docs_roots or [], "dlc": dlc_roots or []}
    fingerprints = {"executable_sha256": exe["sha256"]}
    for kind, roots in groups.items():
        records = []
        for number, raw_root in enumerate(roots):
            root = Path(raw_root).absolute()
            record = {"root_id": number, "root": str(root), "present": root.is_dir(), "files": []}
            try:
                before = inventory(root)
                for relative, *_ in before:
                    record["files"].append(hash_source_file(root, relative))
                if inventory(root) != before:
                    raise ValueError("installation inventory changed during capture")
            except (OSError, ValueError) as exc:
                diagnostics.append({"kind": kind, "root": str(root), "reason": str(exc)})
            records.append(record)
        manifests[kind] = records
        # Local paths are provenance; hashes depend on ordered source identities
        # and relative bytes, not one machine's drive letters.
        portable = [{key: value for key, value in record.items() if key != "root"} for record in records]
        fingerprints[f"{kind}_sha256"] = sha256_bytes(canonical_bytes(portable))
    return {"executable": str(executable), "executable_sha256": exe["sha256"],
            "build_fingerprint": fingerprints, "manifests": manifests,
            "complete": not diagnostics, "diagnostics": diagnostics,
            "documentation_available": any(record["files"] for record in manifests["docs"]),
            "dlc_enabled_state": "unconfirmed", "version_policy": "captured_bytes_no_version_whitelist"}


class RuntimeWorker:
    def __init__(self, root: Path, *, target: dict | None = None,
                 observer: Callable[[dict], dict] | None = None,
                 launcher: Callable[[list[str]], object] | None = None,
                 launch_enabled: bool = False):
        self.fs = ManagedFS(root)
        self.root = self.fs.root
        self.target = dict(target or {})
        if target is None and (self.root / "target.json").exists():
            self.target = json.loads(self.fs.read_bytes("target.json"))
        self.observer, self.launcher = observer, launcher
        self.launch_enabled = launch_enabled
        self.fs.write_bytes(".locks/owner", b"one runtime worker\n")

    def status(self) -> dict:
        available = os.name == "nt"
        return {"platform": "windows" if available else "unsupported", "available": available,
                "launch_enabled": available and self.launch_enabled,
                "target_configured": bool(self.target), "active_state": "unknown",
                "playset_writes": False, "headless_validator": "not_established",
                "reason": None if available else "Windows runtime probes are unavailable on this host"}

    def discover(self, **kwargs) -> dict:
        return discover(**kwargs)

    def configure_target(self, selection: dict) -> dict:
        allowed = {"executable", "content_roots", "docs_roots", "dlc_roots", "log_root", "version_display"}
        if not isinstance(selection, dict) or not set(selection) <= allowed:
            raise ValueError("target selection contains unsupported capabilities")
        executable = Path(selection.get("executable", ""))
        if not executable.is_absolute():
            raise ValueError("select an absolute installed executable")
        roots = {name: [Path(path) for path in selection[name]] for name in
                 ("content_roots", "docs_roots", "dlc_roots") if name in selection}
        if any(not path.is_absolute() for values in roots.values() for path in values):
            raise ValueError("selected fingerprint roots must be absolute")
        sources = [executable.parent, *(path for values in roots.values() for path in values)]
        if any(self.root == source.resolve() or self.root in source.resolve().parents or
               source.resolve() in self.root.parents for source in sources):
            raise ValueError("runtime state and selected installation sources cannot overlap")
        captured = fingerprint_installation(executable, **roots)
        self.target = {**selection, **captured}
        self.fs.write_bytes("target.json", canonical_bytes(self.target))
        return self.target

    def _target_command(self, recipe: dict) -> list[str]:
        if not self.launch_enabled or os.name != "nt":
            raise ValueError("actual Windows launching has not been enabled")
        executable = Path(self.target.get("executable", ""))
        if not executable.is_absolute() or executable.suffix.lower() != ".exe":
            raise ValueError("selected absolute Windows executable required")
        data = read_source_bytes(executable.parent, executable.name, 512 * 1024 * 1024)
        if sha256_bytes(data) != self.target.get("executable_sha256"):
            raise ValueError("selected executable fingerprint changed")
        fingerprint = validate_fingerprint(self.target.get("build_fingerprint"))
        if fingerprint["executable_sha256"] != self.target["executable_sha256"]:
            raise ValueError("captured executable fingerprint is inconsistent")
        arguments = recipe.get("arguments", ["-debug_mode"])
        if arguments != [] and arguments != ["-debug_mode"]:
            raise ValueError("unqualified command-line flags are forbidden")
        return [str(executable), *arguments]

    def run_recipe(self, recipe: dict) -> dict:
        if not isinstance(recipe, dict) or recipe.get("kind") not in RECIPES:
            raise ValueError("unknown controlled probe recipe")
        allowed = {"id", "kind", "experiment_id", "stage", "expected_playset_hash",
                   "expected_sentinel", "launch", "arguments", "timeout_seconds", "log_names"}
        if not set(recipe) <= allowed:
            raise ValueError("probe arguments exceed recipe capability")
        timeout = recipe.get("timeout_seconds", 60)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 600:
            raise ValueError("probe timeout is outside bounds")
        identifier = f"run-{uuid.uuid4().hex}"
        record = {"id": identifier, "recipe": recipe, "platform": "windows" if os.name == "nt" else "unsupported",
                  "executed": False, "outcome": "not_run", "cold_start": False,
                  "active_state_confirmed": False, "raw_logs": [], "milestones": [],
                  "source_changes": [], "playset_writes": False}
        if os.name != "nt":
            record["reason"] = "Windows game execution unavailable; no runtime observation was made"
            self.fs.write_bytes(f"runs/{identifier}/record.json", canonical_bytes(record))
            return record
        with ManagedLock(self.fs.resolve(".locks/runtime.lock")):
            process = None
            started = time.monotonic()
            try:
                before = self.observer({"phase": "before", "recipe": recipe}) if self.observer else {}
                record["active_before"] = before
                if (not before.get("confirmed") or not recipe.get("expected_playset_hash") or
                        before.get("playset_hash") != recipe["expected_playset_hash"]):
                    raise ValueError("actual active playset/order is not confirmed")
                if recipe.get("launch"):
                    if self.target.get("complete") is False:
                        raise ValueError("selected installation fingerprint capture is incomplete")
                    if before.get("game_closed") is not True:
                        raise ValueError("a cold start requires observed absence of the game process")
                    if before.get("build_fingerprint") != self.target.get("build_fingerprint"):
                        raise ValueError("fresh target fingerprints were not confirmed")
                    command = self._target_command(recipe)
                    process = self.launcher(command) if self.launcher else subprocess.Popen(
                        command, cwd=str(Path(command[0]).parent), shell=False,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    record["command"] = command
                    record["executed"] = True
                    record["cold_start"] = True
                observation = self.observer({"phase": "observe", "recipe": recipe,
                                             "deadline_seconds": timeout}) if self.observer else {}
                if time.monotonic() - started > timeout:
                    raise ValueError("bounded runtime observation timed out")
                after = self.observer({"phase": "after", "recipe": recipe}) if self.observer else {}
                record["active_after"] = after
                record["observation"] = observation
                if (not after.get("confirmed") or after.get("playset_hash") != recipe["expected_playset_hash"] or
                        not observation.get("direct_observation") or
                        not observation.get("sentinel_confirmed") or not recipe.get("expected_sentinel") or
                        observation.get("sentinel") != recipe["expected_sentinel"] or
                        after.get("build_fingerprint") != self.target.get("build_fingerprint")):
                    raise ValueError("direct sentinel observation or active state is missing/changed")
                record["active_state_confirmed"] = True
                record["milestones"] = observation.get("milestones", [])
                assertions = observation.get("assertions", [])
                record["assertions"] = assertions
                record["outcome"] = ("passed_with_scope" if record["executed"] and assertions and
                                     all(item.get("outcome") == "pass" for item in assertions) and
                                     observation.get("negative_control") else "inconclusive")
                if not record["executed"]:
                    record["reason"] = "manual observation captured; cold-start execution was not established"
                record["build_fingerprint"] = self.target.get("build_fingerprint")
                # Archive, never clear or rewrite the user's logs.
                log_root = self.target.get("log_root")
                for name in recipe.get("log_names", []):
                    if not log_root:
                        raise ValueError("selected log root is unavailable")
                    raw = read_source_bytes(Path(log_root), name)
                    output = f"runs/{identifier}/logs/{name}"
                    self.fs.write_bytes(output, raw, replace=False)
                    record["raw_logs"].append({"path": output, "sha256": sha256_bytes(raw), "size": len(raw)})
            except Exception as exc:
                record["outcome"] = "inconclusive" if record["executed"] else "not_run"
                record["reason"] = str(exc)
                # A crashed load can disable mods; always collect post-failure state.
                if self.observer:
                    try:
                        record["active_after_failure"] = self.observer({"phase": "after_failure", "recipe": recipe})
                    except Exception:
                        record["active_after_failure"] = {"confirmed": False}
            finally:
                if process is not None and getattr(process, "poll", lambda: None)() is None:
                    try:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    except Exception as exc:
                        record["shutdown_error"] = type(exc).__name__
                        record["outcome"] = "inconclusive"
                record["elapsed_seconds"] = round(time.monotonic() - started, 6)
                self.fs.write_bytes(f"runs/{identifier}/record.json", canonical_bytes(record))
        return record
