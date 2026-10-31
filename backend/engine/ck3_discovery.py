"""Read-only CK3 source and launcher-state discovery on macOS and Windows.

Discovery records inspected bytes and serialized selections, never executed game
loading evidence. SQLite is queried only on a private replica: even a read-only
WAL connection can create shared-memory files beside its database.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from .evidence import canonical_bytes
from .parser import parse
from .safety import read_source_bytes, reject_link_components, sha256_bytes, validate_relative_path

APP_ID = "1158310"
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_MODS = 10000


def _scalar(value: str | None) -> str | None:
    if value and len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return value


def _fields(raw: bytes) -> tuple[dict, list]:
    document = parse(raw)
    fields, diagnostics = {}, list(document.diagnostics)
    for node in document.children:
        if node.key is None:
            if node.kind != "opaque":
                # The CST is retained; this projection may not decide how the
                # launcher treats bare descriptor statements.
                diagnostics.append({"code": "descriptor_non_assignment", "span": [node.start, node.end]})
            continue
        if node.operator != "=":
            diagnostics.append({"code": "descriptor_operator", "span": [node.start, node.end]})
            continue
        key = _scalar(node.key)
        value = [_scalar(child.value if child.value is not None else child.key)
                 for child in node.children] if node.is_block else _scalar(node.value)
        fields.setdefault(key, []).append(value)
    return fields, diagnostics


def _vdf_pairs(raw: bytes):
    """Read Valve's adjacent quoted key/value pairs without rewriting VDF."""
    document = parse(raw)
    if document.diagnostics:
        raise ValueError("malformed Valve metadata")

    def pairs(nodes):
        index = 0
        while index < len(nodes):
            node = nodes[index]
            if node.is_block:
                yield from pairs(node.children)
            elif node.kind == "bare" and index + 1 < len(nodes) and nodes[index + 1].kind == "bare":
                yield _scalar(node.value), _scalar(nodes[index + 1].value)
                index += 1
            index += 1
    return list(pairs(document.children))


def _directory(value: Path | str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("an absolute directory is required")
    reject_link_components(path)
    if not path.is_dir():
        raise ValueError("directory is absent")
    return path.absolute()


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _metadata(root: Path, relative: str, kind: str) -> dict:
    limit = MAX_METADATA_BYTES if relative.startswith("launcher-v2.sqlite") else 1024 * 1024
    raw = read_source_bytes(root, relative, limit)
    return {"kind": kind, "path": relative, "source_path": str(root / relative), "size": len(raw),
            "bytes_base64": base64.b64encode(raw).decode(), "sha256": sha256_bytes(raw)}


def _raw(item: dict) -> bytes:
    return base64.b64decode(item["bytes_base64"])


def _database_rows(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Query a bounded private replica, including committed WAL transactions."""
    with tempfile.TemporaryDirectory(prefix="ck3-launcher-read-") as temporary:
        root = Path(temporary)
        for record in records:
            (root / Path(record["path"]).name).write_bytes(_raw(record))
        connection = sqlite3.connect((root / "launcher-v2.sqlite").as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            deadline = time.monotonic() + 5
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("BEGIN")
            playsets = [dict(row) for row in connection.execute(
                "SELECT id,name,isActive FROM playsets LIMIT ?", (MAX_MODS + 1,))]
            mods = [dict(row) for row in connection.execute(
                "SELECT pm.playsetId,pm.enabled,pm.position,m.gameRegistryId,m.dirPath,m.archivePath,"
                "m.status,m.source FROM playsets_mods pm JOIN mods m ON m.id=pm.modId "
                "ORDER BY pm.playsetId,pm.position LIMIT ?", (MAX_MODS + 1,))]
            if len(playsets) > MAX_MODS or len(mods) > MAX_MODS:
                raise ValueError("launcher row budget exceeded")
            for row in playsets:
                if (not isinstance(row["id"], str) or not isinstance(row["name"], str)
                        or row["isActive"] not in (None, 0, 1)):
                    raise ValueError("unsupported launcher playset field types")
            for row in mods:
                if (not isinstance(row["playsetId"], str) or not isinstance(row["gameRegistryId"], str)
                        or type(row["enabled"]) is not int or row["enabled"] not in (0, 1)
                        or any(value is not None and not isinstance(value, str) for key, value in row.items()
                               if key in {"dirPath", "archivePath", "status", "source"})):
                    raise ValueError("unsupported launcher mod field types")
            connection.rollback()
            return playsets, mods
        finally:
            connection.close()


def discover_ck3(*, platform: str | None = None, steam_roots: list[Path | str] | None = None,
                 user_data_path: Path | str | None = None, installation_path: Path | str | None = None,
                 playset_id: str | None = None, root_overrides: dict[str, Path | str] | None = None) -> dict:
    """Inspect CK3 roots without writing originals or inferring active gameplay.

    Explicit installation/user-data selections override defaults. Payload root
    overrides are keyed by registry path, such as ``mod/ugc_123.mod``. Descriptor
    paths otherwise resolve only inside known Steam Workshop/local-mod roots.
    All returned source directories still require immutable snapshot capture.
    """
    platform = platform or ("windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else sys.platform)
    platform = {"darwin": "macos", "win32": "windows"}.get(platform, platform)
    if platform not in {"macos", "windows"}:
        raise ValueError("CK3 discovery supports macos and windows")
    if steam_roots is not None and (not isinstance(steam_roots, list) or len(steam_roots) > 100):
        raise ValueError("Steam roots must be a bounded list")
    if root_overrides is not None and (not isinstance(root_overrides, dict) or len(root_overrides) > MAX_MODS):
        raise ValueError("payload overrides must be a bounded mapping")
    result = {"game_id": "ck3", "platform": platform, "installation": None, "user_data": None,
              "sources": [], "playset": [], "mods": [], "playsets": [], "selected_playset_id": None,
              "diagnostics": [], "metadata_inputs": [], "complete": True, "consistent": True,
              "active_state": "unconfirmed_serialized_selection", "evidence_label": "V",
              "capabilities": {"read_only_discovery": True, "game_launch": False, "playset_writes": False,
                               "validated_promotion": False, "executed_game_evidence": False}}
    diagnostics, metadata = result["diagnostics"], result["metadata_inputs"]

    def issue(code: str, message: str, *, severity: str = "warning", **context):
        diagnostics.append({"code": code, "message": message, "severity": severity, **context})
        if severity == "error":
            result["complete"] = False
        if code in {"metadata_changed", "launcher_state_changed", "launcher_state_unavailable",
                    "unsupported_launcher_database", "invalid_dlc_load"}:
            result["consistent"] = False

    overrides = {}
    for registry, value in (root_overrides or {}).items():
        try:
            registry = validate_relative_path(registry)
            if not registry.startswith("mod/") or not registry.endswith(".mod"):
                raise ValueError("override key must identify a mod descriptor")
            overrides[registry] = _directory(value)
        except (OSError, ValueError) as exc:
            issue("invalid_root_override", str(exc), severity="error", registry_path=registry)
    if steam_roots is None:
        if platform == "macos":
            steam_roots = [Path.home() / "Library/Application Support/Steam"]
        elif os.name == "nt":
            from .runtime import _steam_registry_roots
            steam_roots = _steam_registry_roots()
        else:
            steam_roots = []
            issue("native_defaults_unavailable", "Select Windows Steam and user-data roots explicitly on this host")
    libraries = {}
    for value in steam_roots:
        try:
            root = _directory(value)
            libraries[str(root)] = root
            if (root / "steamapps/libraryfolders.vdf").exists():
                item = _metadata(root, "steamapps/libraryfolders.vdf", "steam_libraries")
                metadata.append(item)
                for key, value in _vdf_pairs(_raw(item)):
                    if key == "path" and value:
                        library = _directory(value)
                        libraries[str(library)] = library
        except (OSError, ValueError) as exc:
            issue("steam_root_unavailable", str(exc), root=str(value))
    installations = []
    for library in libraries.values():
        manifest_path = "steamapps/appmanifest_1158310.acf"
        if not (library / manifest_path).exists():
            continue
        try:
            item = _metadata(library, manifest_path, "steam_manifest")
            metadata.append(item)
            values = dict(_vdf_pairs(_raw(item)))
            if values.get("appid") != APP_ID:
                raise ValueError("Steam manifest does not identify CK3")
            directory = validate_relative_path(values.get("installdir", ""))
            if "/" in directory:
                raise ValueError("Steam install directory must be one component")
            installations.append(_directory(library / "steamapps/common" / directory))
        except (OSError, ValueError) as exc:
            issue("invalid_steam_manifest", str(exc), library=str(library))
    selected_installation = None
    try:
        if installation_path is not None:
            selected_installation = _directory(installation_path)
        elif len(installations) == 1:
            selected_installation = installations[0]
        elif len(installations) > 1:
            issue("ambiguous_installation", "Select one of the discovered CK3 installations", severity="error")
        else:
            issue("installation_not_found", "Select the CK3 installation directory", severity="error")
    except (OSError, ValueError) as exc:
        issue("installation_unavailable", str(exc), severity="error")
    settings = {}
    if selected_installation:
        result["installation"] = {"path": str(selected_installation), "app_id": APP_ID}
        try:
            item = _metadata(selected_installation, "launcher/launcher-settings.json", "launcher_settings")
            metadata.append(item)
            settings = json.loads(_raw(item).decode("utf-8-sig"))
            if not isinstance(settings, dict) or settings.get("gameId") != "ck3":
                raise ValueError("launcher settings do not identify CK3")
            result["installation"]["version_display"] = settings.get("rawVersion", settings.get("version"))
            for field in ("exePath", "dlcPath"):
                value = settings.get(field)
                if isinstance(value, str):
                    candidate = Path(os.path.abspath(selected_installation / "launcher" / value))
                    if not _within(candidate, [selected_installation]):
                        issue("unsafe_launcher_path", "Launcher path escapes the installation", severity="error", field=field)
                    else:
                        reject_link_components(candidate)
                        result["installation"]["executable" if field == "exePath" else "content_root"] = str(candidate)
        except (OSError, ValueError) as exc:
            issue("launcher_settings_unavailable", str(exc), severity="error")
        try:
            content = _directory(selected_installation / "game")
            result["sources"].append({"owner": "V", "path": str(content)})
            result["installation"]["content_root"] = str(content)
        except (OSError, ValueError) as exc:
            issue("vanilla_content_unavailable", str(exc), severity="error")
    user_data = None
    try:
        if user_data_path is not None:
            candidate = user_data_path
        elif isinstance(settings.get("gameDataPath"), str):
            candidate = Path(settings["gameDataPath"]).expanduser()
            if not candidate.is_absolute():
                candidate = selected_installation / "launcher" / candidate
        elif platform == "macos":
            candidate = Path.home() / "Documents/Paradox Interactive/Crusader Kings III"
        elif os.name == "nt":
            from .runtime import windows_documents
            candidate = windows_documents() / "Paradox Interactive/Crusader Kings III"
        else:
            candidate = None
        if candidate is not None:
            user_data = _directory(candidate)
            result["user_data"] = str(user_data)
        else:
            issue("user_data_not_selected", "Select the CK3 user-data directory", severity="error")
    except (OSError, ValueError) as exc:
        issue("user_data_unavailable", str(exc), severity="error")
    if user_data:
        _inspect_launcher(user_data, playset_id, overrides, list(libraries.values()), result, issue)
    # An explicit search boundary, never a request to walk a user's home/drive.
    result["known_search_roots"] = [
        *([{"kind": "local", "path": str(user_data / "mod")}] if user_data else []),
        *[{"kind": "workshop", "path": str(library / "steamapps/workshop/content" / APP_ID)}
          for library in libraries.values()],
        *[{"kind": "explicit_payload", "path": str(path)} for path in overrides.values()],
    ]
    # Re-read every metadata source to reject launcher/Steam/descriptor changes
    # during the combined observation. The caller repeats discovery at import.
    for item in metadata:
        source = Path(item["source_path"])
        try:
            current = read_source_bytes(source.parent, source.name, MAX_METADATA_BYTES)
            if sha256_bytes(current) != item["sha256"]:
                raise ValueError("metadata changed during discovery")
        except (OSError, ValueError) as exc:
            issue("metadata_changed", str(exc), severity="error", path=item["path"])
    result["options"] = {"platform": platform, "steam_roots": [str(path) for path in steam_roots],
                         "user_data_path": str(user_data) if user_data else None,
                         "installation_path": str(selected_installation) if selected_installation else None,
                         "playset_id": playset_id,
                         "root_overrides": {key: str(path) for key, path in overrides.items()}}
    identity = {key: result[key] for key in ("platform", "installation", "user_data", "sources", "playset", "mods",
                                          "playsets", "selected_playset_id", "complete", "consistent")}
    identity["metadata"] = [{key: item[key] for key in ("kind", "path", "source_path", "sha256")} for item in metadata]
    result["metadata_hash"] = result["configuration_hash"] = sha256_bytes(canonical_bytes(identity))
    return result


def _inspect_launcher(root: Path, requested: str | None, overrides: dict, libraries: list[Path],
                      result: dict, issue) -> None:
    metadata = result["metadata_inputs"]
    state = {}
    observed_files = {name: (root / name).exists() for name in
                      ("launcher-v2.sqlite", "launcher-v2.sqlite-wal", "dlc_load.json")}
    for name, exists in observed_files.items():
        if exists:
            try:
                item = _metadata(root, name, "launcher_state")
                metadata.append(item)
                state[name] = item
            except (OSError, ValueError) as exc:
                issue("launcher_state_unavailable", str(exc), severity="error", path=name)
    json_order = None
    if "dlc_load.json" in state:
        try:
            data = json.loads(_raw(state["dlc_load.json"]).decode("utf-8-sig"))
            json_order = data.get("enabled_mods")
            if (not isinstance(json_order, list) or len(json_order) > MAX_MODS
                    or any(not isinstance(path, str) for path in json_order)):
                raise ValueError("enabled_mods must be a bounded array of descriptor paths")
        except (ValueError, AttributeError) as exc:
            json_order = None
            issue("invalid_dlc_load", str(exc), severity="error")
    selected, rows = None, []
    if "launcher-v2.sqlite" in state:
        try:
            playsets, all_rows = _database_rows([item for name, item in state.items() if name.startswith("launcher-v2.sqlite")])
            result["playsets"] = [{"id": row["id"], "name": row["name"], "active": bool(row["isActive"])}
                                   for row in playsets]
            candidates = [row for row in playsets if row["id"] == requested] if requested else [
                row for row in playsets if row["isActive"]]
            if len(candidates) != 1:
                issue("playset_selection_required", "Select one existing playset; active state is absent or ambiguous", severity="error")
            else:
                selected = candidates[0]["id"]
                result["selected_playset_id"] = selected
                rows = [row for row in all_rows if row["playsetId"] == selected]
                positions = [row["position"] for row in rows]
                if any(type(position) is not int for position in positions) or len(set(positions)) != len(positions):
                    issue("ambiguous_playset_order", "Playset positions must be distinct integers", severity="error")
                enabled = [row["gameRegistryId"] for row in rows if row["enabled"]]
                if json_order is not None and candidates[0]["isActive"] and enabled != json_order:
                    issue("launcher_state_mismatch", "Saved active playset and last launch selection differ", severity="error")
        except (sqlite3.Error, ValueError) as exc:
            issue("unsupported_launcher_database", str(exc), severity="error")
    elif requested:
        issue("playset_not_found", "A saved playset was selected but the launcher database is absent", severity="error")
    elif json_order is not None:
        issue("last_launch_only", "Only the serialized last launch selection is available")
        rows = [{"gameRegistryId": registry, "enabled": True, "position": position}
                for position, registry in enumerate(json_order)]
    else:
        issue("launcher_selection_unavailable", "No supported launcher selection is available", severity="error")
    known = {row.get("gameRegistryId") for row in rows}
    mod_root = root / "mod"
    if mod_root.exists():
        try:
            _directory(mod_root)
            descriptors = sorted(mod_root.glob("*.mod"))
            if len(descriptors) > MAX_MODS:
                raise ValueError("local descriptor budget exceeded")
            for path in descriptors:
                registry = "mod/" + path.name
                if registry not in known:
                    rows.append({"gameRegistryId": registry, "enabled": False, "position": None})
        except (OSError, ValueError) as exc:
            issue("local_mod_inventory_unavailable", str(exc), severity="error")
    allowed = [root / "mod", *[library / "steamapps/workshop/content" / APP_ID for library in libraries]]
    seen = set()
    for row in rows:
        registry = row.get("gameRegistryId")
        enabled = bool(row.get("enabled"))
        mod = {"owner": "ck3:" + str(registry), "registry_path": registry, "enabled": enabled,
               "position": row.get("position"), "status": row.get("status"), "path": None,
               "available": False}
        result["mods"].append(mod)
        try:
            if sum(item["size"] for item in metadata) > 128 * 1024 * 1024:
                raise ValueError("combined discovery metadata budget exceeded")
            registry = validate_relative_path(registry)
            if not registry.startswith("mod/") or not registry.endswith(".mod"):
                raise ValueError("registry entry must be a local mod descriptor")
            if registry in seen:
                raise ValueError("duplicate registry entry in playset")
            seen.add(registry)
            item = _metadata(root, registry, "descriptor")
            item["owner"] = mod["owner"]
            metadata.append(item)
            fields, parse_diagnostics = _fields(_raw(item))
            if parse_diagnostics:
                raise ValueError("descriptor has malformed or unsupported syntax")
            mod["descriptor_sha256"] = item["sha256"]
            mod["descriptor"] = fields
            mod["name"] = fields.get("name", [registry])[-1]
            mod["replace_paths"] = fields.get("replace_path", [])
            mod["dependencies"] = [value for group in fields.get("dependencies", []) for value in
                                   (group if isinstance(group, list) else [group])]
            if row.get("archivePath") or fields.get("archive"):
                raise ValueError("archive payloads are inventoried but unsupported for source scanning")
            paths = fields.get("path", [])
            if registry in overrides:
                payload = overrides[registry]
                mod["root_override"] = True
            else:
                if len(paths) != 1 or not isinstance(paths[0], str):
                    raise ValueError("descriptor must declare exactly one path or have an explicit root override")
                raw_path = paths[0]
                if "\\" in raw_path and os.name != "nt":
                    raise ValueError("foreign Windows descriptor path needs an explicit root override")
                payload = Path(raw_path).expanduser()
                if not payload.is_absolute():
                    relative = validate_relative_path(raw_path)
                    payload = root / relative
                payload = Path(os.path.abspath(payload))
                if not _within(payload, allowed):
                    raise ValueError("descriptor payload outside known mod roots needs an explicit root override")
                payload = _directory(payload)
            if row.get("dirPath") and Path(row["dirPath"]) != payload:
                issue("stale_launcher_payload_path", "Launcher payload path differs from descriptor resolution", registry_path=registry)
            mod.update(path=str(payload), available=True)
            if enabled:
                result["sources"].append({"owner": mod["owner"], "path": str(payload)})
                result["playset"].append(mod["owner"])
        except (OSError, ValueError, TypeError) as exc:
            mod["reason"] = str(exc)
            issue("mod_payload_unavailable", str(exc), severity="error" if enabled else "warning", registry_path=registry)
    for name, existed in observed_files.items():
        if (root / name).exists() != existed:
            issue("launcher_state_changed", "Launcher file set changed during discovery", severity="error", path=name)
