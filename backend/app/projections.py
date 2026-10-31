"""Bounded display projections; validation always uses complete stored records."""
from __future__ import annotations

import base64
import copy
import json


def discovery_projection(record: dict) -> dict:
    """Display metadata without returning SQLite/descriptor source bytes."""
    result = {key: value for key, value in record.items() if key != "metadata_inputs"} | {
        "metadata_inputs": [{key: value for key, value in item.items() if key != "bytes_base64"}
                            for item in record.get("metadata_inputs", [])]}
    totals = {key: len(value) for key, value in result.items() if isinstance(value, list)}
    return bounded(result) | {"display_totals": totals, "display_truncated": any(total > 500 for total in totals.values())}


def bounded(value, depth=0):
    """Bound display strings/collections; complete records remain authoritative."""
    if isinstance(value, str):
        return value if len(value) <= 8192 else value[:8192] + "… [display truncated]"
    if depth > 12:
        return "[nested display omitted]"
    if isinstance(value, list):
        return [bounded(item, depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        return {key: bounded(item, depth + 1) for key, item in list(value.items())[:500]}
    return value


def compact(row: dict) -> dict:
    if len(json.dumps(row)) < 256 * 1024:
        return row
    return bounded({key: value for key, value in row.items() if key not in {
        "body", "occurrences", "children", "source_definitions", "entries", "data", "metadata"
    }}) | {"display_truncated": True}


def scan_projection(record: dict, offset=0, limit=100) -> dict:
    analysis = record["analysis"]
    profile = analysis.get("profile")
    game_id = record.get("game_id") or (profile.get("game_id") if isinstance(profile, dict) else None)
    view = {**analysis}
    totals = {}
    for key in ["files", "definitions", "source_definitions", "findings", "obligations", "package_metadata"]:
        rows = analysis.get(key, [])
        if key == "findings" and game_id == "ck3":
            # This is display order only. Keep stored findings, identities,
            # certainty and complete preservation obligations unchanged.
            rows = sorted(_ck3_discovery_display(rows, analysis), key=_ck3_finding_priority)
        totals[key] = len(rows)
        view[key] = [compact(row) for row in rows[offset:offset + limit]]
    view["graphs"] = {name: [compact(edge) for edge in edges[offset:offset + limit]] for name, edges in analysis.get("graphs", {}).items()}
    view["pagination"] = {"offset": offset, "limit": limit, "totals": totals, "has_more": any(total > offset + limit for total in totals.values())}
    selected = {(file["owner"], file["path"]) for file in view["files"]}
    inputs = []
    for item in record["inputs"]:
        if (item["owner"], item["path"]) not in selected:
            continue
        result = dict(item)
        if len(result.get("bytes_base64", "")) > 10924:
            raw = base64.b64decode(result["bytes_base64"], validate=True)
            result.update(bytes_base64=base64.b64encode(raw[:8192]).decode(), preview_only=True, total_size=len(raw))
        inputs.append(result)
    metadata = [{key: value for key, value in item.items() if key != "bytes_base64"}
                for item in record.get("package_metadata", [])[offset:offset + limit]]
    return {**record, "analysis": view, "inputs": inputs, "package_metadata": metadata}


def _ck3_discovery_display(findings: list[dict], analysis: dict) -> list[dict]:
    """Enrich legacy rows only when retained diagnostic order proves the pairing."""
    discovery = analysis.get("discovery", {})
    diagnostics = discovery.get("diagnostics", [])
    discovery_rows = [(index, row) for index, row in enumerate(findings) if row.get("coverage") == "discovery"]
    paired = (len(discovery_rows) == len(diagnostics) and all(
        row.get("kind") == diagnostic.get("code", "discovery_unknown")
        for (_, row), diagnostic in zip(discovery_rows, diagnostics, strict=False)))
    result = [{**row, "display_key": f"{row.get('id', 'finding')}:{index}"} for index, row in enumerate(findings)]
    if paired:
        from backend.engine.ck3_diagnostics import discovery_diagnostic_details
        for ordinal, ((index, row), diagnostic) in enumerate(zip(discovery_rows, diagnostics, strict=True)):
            if row.get("diagnostic_provenance"):
                continue
            details = discovery_diagnostic_details(diagnostic, discovery, ordinal, analysis.get("package_metadata", []))
            # Stored IDs, targets, messages and references remain authoritative.
            result[index].update(display_title=details["title"], display_target=details["target"],
                                 display_message=details["message"], diagnostic=details["diagnostic"],
                                 diagnostic_provenance=details["diagnostic_provenance"], severity=details["severity"])
    return result


def _ck3_finding_priority(finding: dict) -> int:
    kind = str(finding.get("kind", ""))
    if finding.get("coverage") == "discovery" or kind in {
        "playset_owner_unavailable", "invalid_input", "schema_source_changed",
        "missing_dependency", "disabled_dependency", "ambiguous_dependency", "dependency_cycle",
    }:
        return 0
    if kind in {"portability", "windows_path_alias"}:
        return 1
    if kind in {"overlapping_path", "duplicate_definition", "localization_overlap", "replace_path_scope", "replace_path_unresolved"}:
        return 2
    if kind in {"parse_diagnostic", "descriptor_diagnostic", "ambiguous_package_descriptor"}:
        return 3
    if kind.startswith("schema_") or kind in {"literal_reference_advisory", "reference_coverage_unknown", "symbol_coverage_unknown"}:
        return 5
    return 4


def candidate_projection(record: dict) -> dict:
    result = copy.deepcopy(record)
    result["inputs"] = [{key: item[key] for key in ["owner", "path", "sha256", "opaque_blob"] if key in item} for item in result.get("inputs", [])]
    for key in ["before", "after"]:
        result["plan"].pop(key, None)
    for key in ["beforeprediction", "afterprediction"]:
        if isinstance(result["plan"].get(key), list):
            result["plan"][key] = [compact(row) for row in result["plan"][key][:100]]
    if result.get("validation", {}).get("effective"):
        effective = result["validation"]["effective"]
        result["validation"]["effective"] = {"summary": effective.get("summary"), "coverage": effective.get("coverage"), "definitions": [compact(row) for row in effective.get("definitions", [])[:100]]}
    return result
