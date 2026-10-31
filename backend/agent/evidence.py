"""Bounded concern evidence: byte observations, never inferred game winners."""
from __future__ import annotations

import base64
from difflib import SequenceMatcher
import json

from backend.app.store import Conflict, canonical, digest
from backend.engine.ck3 import _base

EVIDENCE_VERSION = "ck3-concern-evidence-1"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 64 * 1024
MAX_READ_BYTES = 24 * 1024 * 1024
MAX_COMPARISON_BYTES = 128 * 1024
MAX_COMPARISON_LINES = 2000


def _token(data):
    return base64.urlsafe_b64encode(canonical(data)).decode().rstrip("=")


def _decode(value):
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError
        return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Use the continuation returned by the evidence package.") from exc


def _slice(view, source, occurrence):
    raw, reason = view.raw(source)
    if reason:
        return None, None, reason
    start, end = occurrence.get("span") or [0, len(raw)]
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(raw):
        raise Conflict("A captured contribution has an invalid byte span.")
    return raw[start:end], [start, end], None


def _comparison(view, left, right):
    left_source = view.by_path[(left["owner"], left["path"])]
    right_source = view.by_path[(right["owner"], right["path"])]
    identity = {"left": {"source_id": left_source["source_id"], "span": left.get("span")},
                "right": {"source_id": right_source["source_id"], "span": right.get("span")}}
    a, _, reason_a = _slice(view, left_source, left)
    b, _, reason_b = _slice(view, right_source, right)
    if reason_a or reason_b:
        return {**identity, "status": "unavailable", "reason": reason_a or reason_b}
    equal = a == b
    token_a, token_b = left.get("token_sha256"), right.get("token_sha256")
    result = {**identity, "byte_relation": "identical" if equal else "different",
              "token_relation": "identical" if token_a and token_a == token_b else
                                "different" if token_a and token_b else "unsupported_or_uncompared",
              "game_selected_winner": "unknown", "historical_common_ancestor": "not_established"}
    if equal:
        return {**result, "status": "complete_byte_comparison", "changes": []}
    if len(a) + len(b) > MAX_COMPARISON_BYTES:
        return {**result, "status": "ordered_comparison_unfinished", "reason": "comparison_byte_limit",
                "follow_up": "Read the exact contribution spans in bounded source excerpts."}
    lines_a, lines_b = a.splitlines(keepends=True), b.splitlines(keepends=True)
    if len(lines_a) + len(lines_b) > MAX_COMPARISON_LINES:
        return {**result, "status": "ordered_comparison_unfinished", "reason": "comparison_line_limit"}
    # autojunk bounds matching work on repetitive script without making semantic
    # claims. Hunks are an ordered textual comparison, not a merge instruction.
    matcher = SequenceMatcher(None, lines_a, lines_b, autojunk=True)
    changes = []
    operations = [operation for operation in matcher.get_opcodes() if operation[0] != "equal"]
    for tag, a_start, a_end, b_start, b_end in operations[:16]:
        before, after = b"".join(lines_a[a_start:a_end]), b"".join(lines_b[b_start:b_end])
        changes.append({"kind": tag, "left_lines": [a_start, a_end], "right_lines": [b_start, b_end],
                        "before": before[:512].decode("utf-8", errors="backslashreplace"),
                        "after": after[:512].decode("utf-8", errors="backslashreplace"),
                        "text_truncated": len(before) > 512 or len(after) > 512})
    return {**result, "status": "ordered_text_comparison", "changes": changes,
            "total_hunks": len(operations), "hunks_truncated": len(operations) > 16,
            "meaning": "Ordered text differences. Repeated statements retain their order; no safe combination is implied."}


def _knowledge(issues):
    from .knowledge import read_knowledge, search_knowledge
    selected = ["files-and-definitions", "evidence-and-limits"]
    for issue in issues:
        parts = issue.get("target", "").split("/")
        query = parts[1].replace("_", " ") if len(parts) > 2 and parts[0] == "game" else "localization" if issue["kind"] == "localization_overlap" else "assets"
        matches = search_knowledge(query, limit=1)["entries"]
        selected.extend(entry["id"] for entry in matches)
    entries = []
    for identifier in dict.fromkeys(selected):
        if len(entries) == 4:
            break
        entry = read_knowledge(identifier)
        entries.append({"entry_id": identifier, "revision": entry["revision"],
                        "library_sha256": entry["library_sha256"], "title": entry["title"],
                        "summary": entry["summary"], "claims": entry["claims"][:2], "sources": entry["sources"],
                        "coverage": "Summary and first two claims. Use read_knowledge for the complete reference.",
                        "continuation": {"tool": "read_knowledge", "entry_id": identifier},
                        "runtime_qualified": False})
    return entries


def concern_evidence(api, workspace_id, index_id, concern_id, offset=0, limit=4, continuation=None):
    from .context import capabilities
    from .investigation import _Snapshot, REFERENCE_LIMITATION, MAX_FILE_BYTES
    from .projection import _identity
    from .reviews import build_concerns
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("Choose a page of one to eight findings.")
    view = _Snapshot(api.service, workspace_id, index_id)
    concern = next((item for item in build_concerns(view.index) if item["id"] == concern_id), None)
    if concern is None:
        raise ValueError("That concern does not belong to this saved scan.")
    by_id = {issue["id"]: issue for issue in view.index["issues"]}
    issues = [by_id[identifier] for identifier in concern["issue_ids"]]
    identity = digest(canonical([_identity(api.service, workspace_id, index_id), concern_id,
                                 view.patterns, EVIDENCE_VERSION]))
    unit_offset = 0
    if continuation:
        cursor = _decode(continuation)
        if (not isinstance(cursor, dict) or cursor.get("identity") != identity or
                cursor.get("version") != EVIDENCE_VERSION):
            raise Conflict("This evidence continuation belongs to different inputs or source permissions. Start again.")
        offset, limit, unit_offset = (cursor.get(key) for key in ("offset", "limit", "unit_offset"))
        if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8 or
                type(unit_offset) is not int or unit_offset < 0):
            raise ValueError("The evidence continuation is invalid.")
    if offset > len(issues):
        raise ValueError("The requested finding page is outside this concern.")
    selected = issues[offset:offset + limit]
    units, issue_summaries, source_index = [], [], view.by_path
    for issue in selected:
        sources = [source_index.get((item["owner"], item["path"])) for item in issue["sources"]]
        if any(source is None for source in sources):
            raise Conflict("A saved finding refers to an unavailable source identity.")
        excluded = any(view.excluded(source) for source in sources)
        if excluded:
            issue_summaries.append({"issue_id": issue["id"], "excluded": True})
            continue
        issue_summaries.append({"issue_id": issue["id"], **{key: issue.get(key) for key in
            ("kind", "target", "comparison", "what_is_known", "what_is_unknown", "current_game_comparison")},
            "contribution_count": len(sources)})
        for occurrence in issue["sources"]:
            units.append(("contribution", issue, occurrence))
    owners = {mod["owner"] for issue in selected for mod in issue["mods"]}
    descriptors = [source for source in view.files if source["owner"] in owners and not view.excluded(source) and
                   (source["origin"] == "launcher_descriptor" or source["path"] == "descriptor.mod")]
    units.extend(("descriptor", None, source) for source in descriptors)
    if unit_offset > len(units):
        raise ValueError("The evidence continuation is outside this page.")
    knowledge = _knowledge([issue for issue, summary in zip(selected, issue_summaries, strict=True)
                            if not summary.get("excluded")])
    package = {**view.context(), "version": EVIDENCE_VERSION, "concern_id": concern_id,
               "topic": concern["topic"], "findings": issue_summaries, "finding_total": len(issues),
               "offset": offset, "limit": limit, "contributions": [], "descriptors": [], "comparisons": [],
               "knowledge": knowledge, "related": [], "evidence_refs": [],
               "capabilities": capabilities(), "missing_mods": len(view.index.get("unavailable_mods", [])),
               "coverage": {"source_bytes": 0, "source_byte_limit": MAX_SOURCE_BYTES, "gaps": [],
                            "game_behavior": "not_tested", "references": REFERENCE_LIMITATION},
               "continuation": None, "next_offset": None}
    # Related definitions have their own bounded cursor, retained explicitly.
    for issue, summary in zip(selected, issue_summaries, strict=True):
        if summary.get("excluded") or issue["kind"] != "duplicate_definition":
            continue
        related = api._related(view, issue["target"], 0, 3)
        package["related"].append({"issue_id": issue["id"], **related,
            "continuation": {"tool": "related_definitions", "target": issue["target"],
                             "offset": related["next_offset"]} if related.get("next_offset") is not None else None})
    position = unit_offset
    source_bytes = 0
    read_bytes = 0
    read_keys = set()
    while position < len(units):
        kind, issue, occurrence = units[position]
        source = source_index[(occurrence["owner"], occurrence["path"])] if issue else occurrence
        checksum = source["sha256"]
        # Bound file reads before touching their bytes; one oversized file gets
        # an explicit gap rather than an endless non-advancing continuation.
        size = source["size"] if type(source["size"]) is int and 0 <= source["size"] <= MAX_FILE_BYTES else 0
        if checksum not in read_keys and read_bytes + size > MAX_READ_BYTES:
            break
        raw, span, reason = _slice(view, source, occurrence if issue else {})
        if checksum not in read_keys:
            read_keys.add(checksum)
            read_bytes += size
        item = {"source": view.public(source), "issue_id": issue["id"] if issue else None,
                "status": "unavailable" if reason else "available"}
        comparisons = []
        if reason:
            item["reason"] = reason
        else:
            count = min(len(raw), 8192)
            if source_bytes + count > MAX_SOURCE_BYTES:
                break
            item.update(span=[span[0], span[0] + count], contribution_span=span,
                        text=raw[:count].decode("utf-8", errors="backslashreplace"),
                        continuation={"tool": "read_source", "source_id": source["source_id"],
                                      "offset": span[0] + count, "end": span[1]} if count < len(raw) else None)
            if issue:
                others = issue["sources"]
                anchors = [entry for entry in others if _base(entry["owner"])][:1]
                anchors += [entry for entry in others if not _base(entry["owner"])][:1]
                for anchor in anchors:
                    if anchor == occurrence:
                        continue
                    anchor_source = source_index[(anchor["owner"], anchor["path"])]
                    anchor_size = anchor_source["size"]
                    if (type(anchor_size) is not int or
                            anchor_source["sha256"] not in read_keys and read_bytes + anchor_size > MAX_READ_BYTES):
                        comparisons.append({"issue_id": issue["id"], "status": "ordered_comparison_unfinished",
                                            "reason": "request_read_budget"})
                        continue
                    if anchor_source["sha256"] not in read_keys:
                        read_bytes += anchor_size
                        read_keys.add(anchor_source["sha256"])
                    comparisons.append({"issue_id": issue["id"], **_comparison(view, anchor, occurrence)})
        destination = "contributions" if issue else "descriptors"
        package[destination].append(item)
        package["comparisons"].extend(comparisons)
        reference = {"source_id": source["source_id"], "sha256": source["sha256"], "span": item.get("span")}
        if not reason:
            package["evidence_refs"].append(reference)
        if len(canonical(package)) > MAX_RESPONSE_BYTES - 4096:
            package[destination].pop()
            if comparisons:
                del package["comparisons"][-len(comparisons):]
            if not reason:
                package["evidence_refs"].pop()
            break
        position += 1
        source_bytes += len(raw[:8192]) if raw is not None else 0
    package["evidence_refs"].extend({"issue_id": item["issue_id"]} for item in issue_summaries if not item.get("excluded"))
    package["evidence_refs"].extend({key: entry[key] for key in ("entry_id", "revision", "library_sha256")}
                                    for entry in knowledge)
    package["coverage"].update(source_bytes=source_bytes, verified_file_bytes=read_bytes,
                               units_total=len(units), units_returned=[unit_offset, position],
                               findings_on_page=len(selected), excluded_findings=sum(bool(i.get("excluded")) for i in issue_summaries))
    if position < len(units):
        if position == unit_offset:
            raise ValueError("A single evidence item exceeds the response limit. Use individual source tools.")
        cursor = {"offset": offset, "limit": limit, "unit_offset": position}
    elif offset + len(selected) < len(issues):
        package["next_offset"] = offset + len(selected)
        cursor = {"offset": package["next_offset"], "limit": limit, "unit_offset": 0}
    else:
        cursor = None
    if cursor:
        package["continuation"] = _token({"version": EVIDENCE_VERSION, "identity": identity, **cursor})
    for item in package["contributions"] + package["descriptors"]:
        if item.get("continuation") or item["status"] != "available":
            package["coverage"]["gaps"].append({"source_id": item["source"]["source_id"],
                "reason": item.get("reason", "Source excerpt is incomplete; follow its byte continuation.")})
    package["coverage"]["all_findings_packaged"] = offset == 0 and unit_offset == 0 and cursor is None
    package["coverage"]["package_exhausted"] = cursor is None
    package["coverage"]["complete_source_text_on_page"] = (
        not package["coverage"]["gaps"] and not package["coverage"]["excluded_findings"] and
        unit_offset == 0 and position == len(units))
    if len(canonical(package)) > MAX_RESPONSE_BYTES:
        raise ValueError("Evidence metadata exceeds the response limit; inspect the findings individually.")
    return package
