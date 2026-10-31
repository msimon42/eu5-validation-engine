"""Materialized synthetic sources for filesystem and live-browser contracts.

The manifest is an explicit P-level application contract.  It cannot assert a
game observation or grant production applicability.  Loading a directory reads
and verifies its complete declared tree; it never repairs or updates that tree.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

from jsonschema import Draft202012Validator, ValidationError

from .fixtures import load_fixture
from .safety import (
    ManagedFS,
    check_path_collisions,
    hash_source_file,
    read_source_bytes,
    reject_link_components,
    validate_relative_path,
)

MANIFEST_NAME = "case.json"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILES = 4096
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
_HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_OWNER = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"}
_PROFILE_PROPERTIES = {
    "id": {"type": "string", "minLength": 1, "maxLength": 200},
    "kind": {"const": "synthetic"},
    "game_id": {"const": "eu5"},
    "target_platform": {"const": "windows"},
    "revision": {"type": "integer", "minimum": 1},
    "production_export_enabled": {"const": False},
    "conformed_rules": {"const": []},
    "evidence_label": {"const": "P"},
    "families": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    "bare_registration": {"type": ["string", "null"]},
    "mode_order": {"type": "array", "uniqueItems": True, "items": {"enum": [
        "INJECT_OR_CREATE", "REPLACE_OR_CREATE", "TRY_INJECT", "TRY_REPLACE", "INJECT", "REPLACE",
    ]}},
    "readers": {"type": "object", "additionalProperties": {"enum": [
        "scalar_last", "scalar_first", "numeric_sum", "ordered_commands", "append_occurrences",
        "named_members", "map", "single_block_only", "unknown",
    ]}},
    "reference_fields": {"type": "object", "additionalProperties": {"type": "string"}},
    "independent_fields": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    "localization": {"type": "object"},
    "gui": {"type": "object"},
    "rules": {"const": []},
    "target": {"type": "null"},
}
MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "kind", "tier", "id", "title", "profile", "baselines", "playset", "sources", "expected"],
    "properties": {
        "schema_version": {"const": 1},
        "kind": {"const": "synthetic_fixture_directory"},
        "tier": {"const": "contract"},
        "id": {"type": "string", "pattern": "^F[0-9]{2}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "profile": {"type": "object", "additionalProperties": False,
                    "required": ["id", "kind", "revision", "production_export_enabled"],
                    "properties": _PROFILE_PROPERTIES},
        "baselines": {"type": "object", "additionalProperties": {
            "type": "object", "additionalProperties": False,
            "required": ["source_hash", "author_base_hashes"],
            "properties": {"source_hash": _HASH, "author_base_hashes": {
                "type": "object", "additionalProperties": _HASH,
            }},
        }},
        "playset": {"type": "array", "uniqueItems": True, "maxItems": 1000,
                    "items": _OWNER},
        "sources": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["owner", "root", "files"],
            "properties": {
                "owner": _OWNER,
                "root": {"type": "string", "minLength": 1, "maxLength": 200},
                "files": {"type": "array", "maxItems": MAX_FILES, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["path", "sha256", "size"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 32760},
                        "sha256": _HASH,
                        "size": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES},
                    },
                }},
            },
        }},
        "expected": {"type": "object", "additionalProperties": False,
                     "required": ["disposition", "finding_kinds", "assertions"],
                     "properties": {
                         "disposition": {"enum": ["no_repair_needed", "blocked_unknown", "blocked_design", "invalid_input", "repair_expected"]},
                         "finding_kinds": {"type": "array", "items": {"type": "string"}},
                         "assertions": {"type": "array", "items": {"type": "string"}},
                         "effective": {"type": "object"},
                         "effective_before_patch": {"type": "object"},
                         "patch": {"type": ["array", "null"]},
                     }},
    },
}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(path: str) -> str:
    normalized = validate_relative_path(path)
    if normalized != path:
        raise ValueError("fixture paths must use their exact slash-separated spelling")
    if len(path.split("/")) > 64:
        raise ValueError("fixture directory nesting exceeds its budget")
    return normalized


def _validate_manifest(manifest: dict) -> tuple[set[str], set[str]]:
    try:
        Draft202012Validator(MANIFEST_SCHEMA).validate(manifest)
    except ValidationError as exc:
        raise ValueError(f"invalid synthetic fixture manifest: {exc.message}") from exc
    owners, roots, paths = set(), [], [MANIFEST_NAME]
    directories = set()
    total_bytes = 0
    for source in manifest["sources"]:
        owner = source["owner"]
        if owner == "generated_patch" or owner in owners:
            raise ValueError("fixture source owner IDs must be unique; generated_patch is reserved")
        owners.add(owner)
        root = _path(source["root"])
        if len(root.split("/")) != 2 or not root.startswith("sources/"):
            raise ValueError("fixture roots must be direct children of sources/")
        roots.append(root)
        directories.update({"sources", root})
        source_paths = []
        for row in source["files"]:
            relative = _path(row["path"])
            full = root + "/" + relative
            paths.append(full)
            source_paths.append(relative)
            total_bytes += row["size"]
            parent = Path(full).parent
            while parent.as_posix() != ".":
                directories.add(parent.as_posix())
                parent = parent.parent
        check_path_collisions(source_paths)
    if len(paths) - 1 > MAX_FILES or total_bytes > MAX_SOURCE_BYTES:
        raise ValueError("fixture exceeds its file/byte budget")
    if not set(manifest["playset"]) <= owners | {"generated_patch"}:
        raise ValueError("fixture playset references an undeclared owner")
    check_path_collisions(roots)
    check_path_collisions(paths)
    # A file cannot also be a parent directory, including target case aliases.
    if {path.casefold() for path in paths} & {path.casefold() for path in directories}:
        raise ValueError("fixture file/directory paths collide")
    check_path_collisions(sorted(directories))
    return set(paths), directories


def _inventory(root: Path) -> tuple[dict, set[str]]:
    """Enumerate descriptor-anchored paths; all links/nonregular content fail."""
    files, directories = {}, set()
    root_info = root.lstat()
    root_identity = (root_info.st_dev, root_info.st_ino)

    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def inspect(entries, prefix, descend):
        names = []
        for entry in entries:
            relative = prefix + entry.name
            _path(relative)
            names.append(entry.name)
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("fixture contains a link/reparse point")
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
                if len(directories) > MAX_FILES * 8:
                    raise ValueError("fixture directory inventory exceeds its budget")
                descend(entry.name, relative + "/")
            elif stat.S_ISREG(info.st_mode):
                if info.st_size > MAX_FILE_BYTES or len(files) >= MAX_FILES + 1:
                    raise ValueError("fixture inventory exceeds file/byte bounds")
                files[relative] = signature(info)
            else:
                raise ValueError("fixture contains a nonregular file")
        check_path_collisions(names)

    if os.name == "nt":
        def walk(directory, prefix):
            reject_link_components(directory)
            with os.scandir(directory) as entries:
                inspect(entries, prefix, lambda name, child_prefix: walk(directory / name, child_prefix))
        walk(root, "")
    else:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        def walk(descriptor, prefix):
            def descend(name, child_prefix):
                child = os.open(name, flags, dir_fd=descriptor)
                try:
                    walk(child, child_prefix)
                finally:
                    os.close(child)
            with os.scandir(descriptor) as entries:
                inspect(entries, prefix, descend)
        descriptor = os.open(root, flags)
        try:
            if (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) != root_identity:
                raise ValueError("fixture root changed")
            walk(descriptor, "")
        finally:
            os.close(descriptor)
    if (root.lstat().st_dev, root.lstat().st_ino) != root_identity:
        raise ValueError("fixture root changed during inventory")
    return files, directories


def _read_manifest(root: Path) -> tuple[dict, bytes]:
    raw = read_source_bytes(root, MANIFEST_NAME, MAX_MANIFEST_BYTES)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate fixture manifest key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("fixture manifest must be strict UTF-8 JSON") from exc
    return value, raw


def load_fixture_directory(root: Path) -> dict:
    """Read a complete pristine on-disk synthetic contract, without changing it."""
    root = reject_link_components(Path(root))
    if not root.is_dir():
        raise ValueError("fixture directory must be an existing real directory")
    root = root.resolve()
    manifest, raw = _read_manifest(root)
    expected_files, expected_directories = _validate_manifest(manifest)
    before, directories = _inventory(root)
    if set(before) != expected_files or directories != expected_directories:
        raise ValueError("synthetic fixture inventory changed: missing or extra files/directories")
    sources = []
    for source in manifest["sources"]:
        source_root = root.joinpath(*source["root"].split("/"))
        for row in source["files"]:
            # Keep the original fixture root as the opened capability.  Opening
            # each source directory as a fresh root could follow a substituted
            # `sources/` ancestor between inventory and hash verification.
            observed = hash_source_file(root, source["root"] + "/" + row["path"], max_bytes=MAX_FILE_BYTES)
            if observed["sha256"] != row["sha256"] or observed["size"] != row["size"]:
                raise ValueError("synthetic fixture source changed: hash/size precondition failed")
        sources.append({"owner": source["owner"], "path": str(source_root), "manifest": copy.deepcopy(source["files"])})
    after, after_directories = _inventory(root)
    if before != after or directories != after_directories or read_source_bytes(root, MANIFEST_NAME, MAX_MANIFEST_BYTES) != raw:
        raise ValueError("synthetic fixture changed during verification")
    return {"id": manifest["id"], "title": manifest["title"], "tier": "contract",
            "fixture_path": str(root), "manifest_hash": _checksum(raw), "sources": sources,
            "playset": copy.deepcopy(manifest["playset"]), "profile": copy.deepcopy(manifest["profile"]),
            "baselines": copy.deepcopy(manifest["baselines"]), "expected": copy.deepcopy(manifest["expected"])}


def materialize_fixture(identifier: str, destination: Path) -> dict:
    """Create physical sources from exact catalog bytes in a new/empty directory."""
    case = load_fixture(identifier)
    by_owner, payloads = {}, {}
    for item in case["inputs"]:
        owner = item["owner"]
        if not re.fullmatch(_OWNER["pattern"], owner):
            raise ValueError("invalid synthetic source owner")
        root = "sources/" + owner
        relative = _path(item["path"])
        raw = base64.b64decode(item["bytes_base64"], validate=True)
        if base64.b64encode(raw).decode() != item["bytes_base64"] or _checksum(raw) != item["sha256"]:
            raise ValueError("fixture bytes do not match their declared source hash")
        full = root + "/" + relative
        if full in payloads:
            raise ValueError("fixture source paths are duplicated")
        payloads[full] = raw
        source = by_owner.setdefault(owner, {"owner": owner, "root": root, "files": []})
        source["files"].append({"path": relative, "sha256": item["sha256"], "size": len(raw)})
    for owner in case["playset"]:
        if owner != "generated_patch":
            by_owner.setdefault(owner, {"owner": owner, "root": "sources/" + owner, "files": []})
    manifest = {"schema_version": 1, "kind": "synthetic_fixture_directory", "tier": "contract",
                "id": case["id"], "title": case["title"], "profile": copy.deepcopy(case["profile"]),
                "baselines": copy.deepcopy(case["baselines"]), "playset": copy.deepcopy(case["playset"]),
                "sources": list(by_owner.values()), "expected": copy.deepcopy(case["expected"])}
    _validate_manifest(manifest)
    manifest_raw = _canonical(manifest)
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise ValueError("fixture manifest exceeds its byte budget")
    destination = reject_link_components(Path(destination))
    existing = None
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise FileExistsError("fixture destination must be new or empty")
        info = destination.stat()
        existing = (info.st_dev, info.st_ino)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_link_components(destination.parent)
    temporary = destination.parent / ("." + destination.name + ".fixture-" + uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    try:
        output = ManagedFS(temporary, max_bytes=MAX_FILE_BYTES)
        for source in manifest["sources"]:
            # Empty enabled packages remain explicit physical roots.  Opening a
            # managed parent creates only directories, never a marker source.
            with output._parent(source["root"] + "/.ensure-root", create=True):
                pass
        for path, raw in payloads.items():
            output.write_bytes(path, raw, replace=False)
        output.write_bytes(MANIFEST_NAME, manifest_raw, replace=False)
        load_fixture_directory(temporary)
        reject_link_components(destination)
        if destination.exists():
            info = destination.stat()
            if existing != (info.st_dev, info.st_ino) or not destination.is_dir() or any(destination.iterdir()):
                raise FileExistsError("fixture destination changed during materialization")
            destination.rmdir()
        elif existing is not None:
            raise ValueError("fixture destination changed during materialization")
        os.rename(temporary, destination)
        return load_fixture_directory(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
