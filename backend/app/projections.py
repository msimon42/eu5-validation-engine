"""Bounded display projections; validation always uses complete stored records."""
from __future__ import annotations

import base64
import copy
import json


def compact(row: dict) -> dict:
    if len(json.dumps(row)) < 256 * 1024:
        return row
    return {key: value for key, value in row.items() if key not in {"body", "occurrences", "children", "source_definitions"}} | {"display_truncated": True}


def scan_projection(record: dict, offset=0, limit=100) -> dict:
    analysis = record["analysis"]
    view = {**analysis}
    totals = {}
    for key in ["files", "definitions", "source_definitions", "findings", "obligations"]:
        rows = analysis.get(key, [])
        totals[key] = len(rows)
        view[key] = [compact(row) for row in rows[offset:offset + limit]]
    view["graphs"] = {name: edges[offset:offset + limit] for name, edges in analysis.get("graphs", {}).items()}
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
    return {**record, "analysis": view, "inputs": inputs}


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
