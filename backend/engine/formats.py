"""Family dispatch and dedicated localization/metadata views. No YAML serializer."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import PurePosixPath

from .parser import parse, digest

STAGES = {"loading_screen", "main_menu", "in_game"}
BINARY_EXTENSIONS = {".dds", ".png", ".jpg", ".jpeg", ".mesh", ".ogg", ".wav", ".ttf", ".otf", ".zip"}
DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def validate_virtual_path(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise ValueError("invalid virtual path")
    if path.startswith(("/", "\\")) or "\\" in path or ":" in path or "\x00" in path:
        raise ValueError("absolute, drive, stream or ambiguous separator path")
    parts = path.split("/")
    if any(p in {"", ".", ".."} or any(ord(c) < 32 for c in p) for p in parts):
        raise ValueError("path traversal or empty component")
    if any(DEVICE.match(p.rstrip(" .")) for p in parts):
        raise ValueError("Windows device name")
    return path


def path_risks(path: str) -> list[str]:
    risks = []
    if any(p.endswith((".", " ")) for p in path.split("/")):
        risks.append("windows_trailing_dot_or_space")
    if unicodedata.normalize("NFC", path) != path:
        risks.append("unicode_normalization_review")
    if any(ord(c) > 127 for c in path):
        risks.append("non_ascii_order_unmeasured")
    return risks


def windows_key(path: str) -> str:
    # Preserve original Unicode spelling: normalization is not an established alias rule.
    return "/".join(part.rstrip(" .").casefold() for part in path.split("/"))


def classify(path: str) -> dict:
    parts = path.split("/")
    stage = parts[0] if parts[0] in STAGES else "package"
    ext = PurePosixPath(path).suffix.lower()
    if path == ".metadata/metadata.json":
        kind, family = "metadata", "metadata"
    elif ext in BINARY_EXTENSIONS:
        kind, family = "opaque", "asset"
    elif "localization" in parts and ext == ".yml":
        kind, family = "localization", "localization"
    elif ext == ".gui":
        kind, family = "gui", "gui"
    elif "events" in parts and ext == ".txt":
        kind, family = "script", "events"
    elif "setup" in parts and ext == ".txt":
        index = parts.index("setup")
        kind, family = "script", "setup/" + (parts[index + 1] if len(parts) > index + 1 else "unknown")
    elif "common" in parts and ext == ".txt":
        index = parts.index("common")
        kind, family = "script", parts[index + 1] if len(parts) > index + 1 else "unknown"
    else:
        kind, family = "opaque", "unknown"
    return {"kind": kind, "family": family, "stage": stage}


def parse_localization(raw: bytes, path: str = "") -> dict:
    doc = parse(raw)
    diagnostics = list(doc.diagnostics) if doc.encoding != "utf-8" else []
    entries = []
    language = None
    offset = len(doc.bom)
    if doc.encoding != "utf-8":
        return {"document": doc, "entries": [], "language": None, "diagnostics": diagnostics}
    text = raw[offset:].decode("utf-8")
    counts = {}
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        stripped = body.strip()
        if not stripped or stripped.startswith("#"):
            offset += len(line.encode("utf-8"))
            continue
        header = re.fullmatch(r"l_([A-Za-z_]+):(?:\s*#.*)?", stripped)
        if header:
            if language is not None:
                diagnostics.append({"code": "duplicate_language_header", "span": [offset, offset + len(body.encode())]})
            language = header.group(1)
        else:
            match = re.match(r'^\s*([^\s:#]+):([0-9]*)\s+("(?:[^"\\]|\\.)*")\s*(?:#.*)?$', body)
            if not match:
                diagnostics.append({"code": "invalid_localization_entry", "span": [offset, offset + len(body.encode())]})
            elif language is None:
                diagnostics.append({"code": "missing_language_header", "span": [offset, offset + len(body.encode())]})
            else:
                key, revision, value = match.groups()
                ordinal = counts.get(key, 0)
                counts[key] = ordinal + 1
                entries.append({"key": key, "language": language, "revision": revision,
                                "raw_value": value, "value": value[1:-1], "ordinal": ordinal,
                                "span": [offset, offset + len(body.encode())],
                                "value_span": [offset + len(body[:match.start(3)].encode()),
                                               offset + len(body[:match.end(3)].encode())]})
        offset += len(line.encode("utf-8"))
    if language is None:
        diagnostics.append({"code": "missing_language_header", "span": [0, len(raw)]})
    expected = re.search(r"_l_([A-Za-z_]+)\.yml$", path)
    if expected and language and expected.group(1) != language:
        diagnostics.append({"code": "language_filename_mismatch", "span": [0, len(raw)]})
    return {"document": doc, "entries": entries, "language": language, "diagnostics": diagnostics,
            "bom_present": bool(doc.bom), "replace_tier": "/replace/" in path}


def parse_metadata(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("metadata must be an object")
        diagnostics = []
        for field in ("id", "name", "version", "supported_game_version"):
            if field in data and not isinstance(data[field], str):
                diagnostics.append({"code": "invalid_metadata_field", "field": field, "span": [0, len(raw)]})
        if "relationships" in data and not isinstance(data["relationships"], list):
            diagnostics.append({"code": "invalid_metadata_relationships", "span": [0, len(raw)]})
        return {"data": data, "diagnostics": diagnostics}
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return {"data": None, "diagnostics": [{"code": "invalid_metadata", "message": str(exc)[:200], "span": [0, len(raw)]}]}


def parse_family(raw: bytes, path: str) -> dict:
    info = classify(path)
    if info["kind"] == "localization":
        return {**info, **parse_localization(raw, path)}
    if info["kind"] == "metadata":
        return {**info, **parse_metadata(raw)}
    if info["kind"] in {"script", "gui"}:
        from .parsing_cache import parse_cached
        doc = parse_cached(raw, dialect=info["kind"])
        diagnostics = list(doc.diagnostics)
        if info["family"] in {"setup/countries", "setup/templates"} and not doc.bom:
            diagnostics.append({"code": "documented_bom_required", "severity": "warning", "span": [0, 0]})
        if info["family"] == "setup/start" and doc.bom:
            diagnostics.append({"code": "documented_bom_forbidden", "severity": "warning", "span": [0, len(doc.bom)]})
        return {**info, "document": doc, "diagnostics": diagnostics}
    return {**info, "sha256": digest(raw), "diagnostics": [], "opaque": True}
