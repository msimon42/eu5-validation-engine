"""Versioned importer for explicitly structured documentation and opaque dumps.

Unrecognized installation formats are retained with reduced coverage. They do
not silently become built-in definitions through heuristic text matching.
"""
from __future__ import annotations

import base64
import hashlib
import json


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def import_documents(inputs: list[dict], target: dict, *, max_bytes: int = 32 * 1024 * 1024) -> dict:
    target = dict(target.get("build_fingerprint", target))
    if "exe_sha256" in target:
        target["executable_sha256"] = target.pop("exe_sha256")
    if "content_manifest_hash" in target:
        target["content_sha256"] = target.pop("content_manifest_hash")
    if not target.get("executable_sha256") or not target.get("content_sha256"):
        raise ValueError("Documentation import requires executable/content fingerprints")
    documents, vocabulary, unknown = [], [], []
    total = 0
    for item in inputs:
        raw = base64.b64decode(item["bytes_base64"], validate=True)
        total += len(raw)
        if total > max_bytes:
            raise ValueError("Documentation import exceeds the byte budget")
        checksum = _hash(raw)
        record = {"path": item["path"], "sha256": checksum, "bytes_base64": item["bytes_base64"], "status": "opaque"}
        try:
            decoded = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict) and decoded.get("documentation_schema") == 1:
            entries = decoded.get("entries")
            if not isinstance(entries, list):
                raise ValueError("Structured documentation entries must be a list")
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) - {"name", "kind", "scope", "parameters", "description"}:
                    raise ValueError("Unsupported documentation entry")
                if not isinstance(entry.get("name"), str) or entry.get("kind") not in {"effect", "trigger", "scope", "type", "value"}:
                    raise ValueError("Documentation vocabulary requires an explicit name and kind")
                vocabulary.append({**entry, "source_sha256": checksum, "target": target, "certainty": "documented", "evidence_label": "V"})
            record["status"] = "structured"
        else:
            unknown.append({"path": item["path"], "reason": "No qualified importer for this dump format; original bytes retained"})
        documents.append(record)
    manifest = {"importer_version": 1, "target": target, "documents": documents, "vocabulary": vocabulary, "unknown": unknown}
    manifest["hash"] = _hash(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    manifest["coverage"] = {"documents": len(documents), "structured": len(documents) - len(unknown), "unknown": len(unknown)}
    return manifest
