"""Separated VFS selection, operation schedule, ordered bodies and field readers.

Only the explicitly synthetic contract is executable here. Real families stay
symbolic until an archived build-scoped conformance adapter is installed.
"""
from __future__ import annotations

import copy
import json
from pathlib import PurePosixPath

from .formats import windows_key
from .parser import Node, digest

MODE_ORDER = ["INJECT_OR_CREATE", "REPLACE_OR_CREATE", "TRY_INJECT", "TRY_REPLACE", "INJECT", "REPLACE"]
DEFAULT_PROFILE = {"id": "eu5-docs-cutoff-2026-10-26", "kind": "documentation_only",
                   "revision": 1, "families": [], "readers": {}, "independent_fields": [],
                   "production_export_enabled": False, "conformed_rules": [], "evidence_label": "D"}
SYNTHETIC_PROFILE = {"id": "synthetic-contract-v1", "kind": "synthetic", "revision": 1,
                     "families": ["testdb"], "bare_registration": "first_reject_duplicates",
                     "mode_order": MODE_ORDER, "production_export_enabled": False,
                     "conformed_rules": [], "evidence_label": "P",
                     "readers": {"x": "scalar_last", "y": "scalar_last", "ref": "scalar_last",
                                 "effect": "ordered_commands", "items": "append_occurrences", "nested": "unknown"},
                     "reference_fields": {"ref": "same_family"}, "independent_fields": ["x", "y"]}


def normalized_profile(profile: dict | None) -> dict:
    if profile is not None and not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    synthetic = bool(profile and profile.get("kind") == "synthetic")
    result = copy.deepcopy(SYNTHETIC_PROFILE if synthetic else DEFAULT_PROFILE)
    if profile:
        result.update(copy.deepcopy(profile))
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise ValueError("profile id must be nonempty text")
    if not isinstance(result.get("families"), list) or any(not isinstance(f, str) for f in result["families"]):
        raise ValueError("profile family selectors must be an array of strings")
    if not isinstance(result.get("readers"), dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in result["readers"].items()):
        raise ValueError("profile readers must map fields to named policies")
    if not isinstance(result.get("independent_fields", []), list) or any(not isinstance(f, str) for f in result.get("independent_fields", [])):
        raise ValueError("independent fields must be an array of strings")
    order = result.get("mode_order", MODE_ORDER)
    if not isinstance(order, list) or len(order) != 6 or set(order) != set(MODE_ORDER):
        raise ValueError("mode order must contain each of the six known operations once")
    # No input assertion can turn a synthetic fixture or a documentation scenario into conformance.
    result.pop("hash", None)
    result["production_export_enabled"] = False
    result["conformed_rules"] = []
    result["evidence_label"] = "P" if synthetic else "D"
    result["hash"] = digest(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    return result


def contract_family(profile: dict, family: str) -> bool:
    supported = profile.get("kind") == "synthetic" and family in profile.get("families", [])
    if family == "gui":
        supported = supported and isinstance(profile.get("gui"), dict) and profile["gui"].get("duplicate_definition") == "playset_last"
    return supported


def node_value(node: Node):
    if not node.is_block:
        value = node.value
        return value[1:-1] if value and value.startswith('"') and value.endswith('"') else value
    return [node_summary(child) for child in node.children]


def node_summary(node: Node) -> dict:
    return {"kind": node.kind, "key": node.key, "operator": node.operator,
            "value": node.value, "ordinal": node.ordinal, "span": [node.start, node.end],
            "tag": node.tag, "children": [node_summary(child) for child in node.children]}


def read_body(nodes: list[Node] | tuple[Node, ...], profile: dict) -> tuple[dict, str, dict]:
    """Reader policies are explicit per field, never guessed from scalar types."""
    groups: dict[str, list[Node]] = {}
    for node in nodes:
        if node.key is not None:
            groups.setdefault(node.key, []).append(node)
    values, states = {}, {}
    readers = profile.get("readers", {})
    for field, occurrences in groups.items():
        policy = readers.get(field, "unknown")
        state = "known"
        if policy in {"scalar_last", "scalar_first"} and all(not n.is_block for n in occurrences):
            values[field] = node_value(occurrences[-1] if policy == "scalar_last" else occurrences[0])
        elif policy == "numeric_sum" and all(not n.is_block for n in occurrences):
            from decimal import Decimal, InvalidOperation
            try:
                values[field] = str(sum((Decimal(n.value) for n in occurrences), Decimal(0)))
            except (InvalidOperation, TypeError):
                state = "invalid"
                values[field] = {"state": "invalid", "reason": "nonnumeric sum operand"}
        elif policy in {"ordered_commands", "append_occurrences"}:
            values[field] = []
            for node in occurrences:
                for child in node.children if node.is_block else (node,):
                    values[field].append({"key": child.key, "value": node_value(child), "ordinal": child.ordinal})
        elif policy in {"named_members", "map"} and all(n.is_block for n in occurrences):
            merged = {}
            for occurrence in occurrences:
                for child in occurrence.children:
                    if child.key is None or child.is_block:
                        state = "unknown"
                    else:
                        merged[child.key] = node_value(child)
            values[field] = merged if state == "known" else {"state": "unknown", "reason": "unsupported nested member"}
        elif policy == "single_block_only" and len(occurrences) == 1:
            values[field] = node_value(occurrences[0])
        else:
            state = "unknown"
            values[field] = {"state": "unknown", "reason": "unmeasured field reader" if policy == "unknown" else "reader/input mismatch",
                             "occurrences": [node_summary(n) for n in occurrences]}
        states[field] = {"state": state, "policy": policy, "occurrence_count": len(occurrences)}
    overall = "invalid" if any(v["state"] == "invalid" for v in states.values()) else "unknown" if any(v["state"] == "unknown" for v in states.values()) else "known"
    return values, overall, states


def enumeration_key(path: str):
    parts = PurePosixPath(path).parts
    # In each directory, files precede all child directories; ASCII order is explicit.
    return tuple((1, p.encode("utf-8")) for p in parts[:-1]) + ((0, parts[-1].encode("utf-8")),)


def is_base(owner: str) -> bool:
    return owner in {"V", "vanilla", "base"} or owner.startswith("DLC:")


def definition_nodes(document, family):
    """GUI grouping containers do not own the override identity of their children."""
    def gui_nodes(nodes):
        for node in nodes:
            if node.key in {"types", "templates"} and node.is_block:
                yield from gui_nodes(node.children)
            elif node.kind in {"gui_head", "declaration"} and len(node.head) > 1 and node.head[0] in {"type", "template"}:
                yield node
            elif node.is_block and any(child.key == "name" and child.value for child in node.children):
                yield node
    return list(gui_nodes(document.children)) if family == "gui" else list(document.children)


def simulate(files: list[dict], playset: list[str], profile: dict) -> dict:
    rank = {owner: i for i, owner in enumerate(playset)}
    candidates: dict[str, list[dict]] = {}
    findings, active, hidden = [], [], []
    evidence = [profile["id"]]
    for file in files:
        file["active"] = False
        file["shadowed_by"] = None
        owner = file["owner"]
        if owner in rank or is_base(owner):
            candidates.setdefault(windows_key(file["path"]), []).append(file)
    for path_key, group in candidates.items():
        group.sort(key=lambda f: (rank.get(f["owner"], -100), f["owner"], f["path"]))
        winner = group[-1]
        winner["active"] = True
        active.append(winner)
        for loser in group[:-1]:
            loser["shadowed_by"] = winner["id"]
            hidden.append(loser)
        if len(group) > 1:
            equal = len({file["sha256"] for file in group}) == 1
            category = "compatible_overlap" if equal else "load_order_dependent"
            findings.append({"category": category, "kind": "exact_path_shadow", "target": winner["path"],
                             "certainty": "synthetic_contract" if profile.get("kind") == "synthetic" else "conditional",
                             "impact": "equal bytes" if equal else "whole-file contributions hidden",
                             "source_occurrences": [{"file_id": f["id"], "owner": f["owner"], "path": f["path"]} for f in group],
                             "evidence_ids": evidence, "order_sensitive": True, "repairability": "investigate"})
    operations, definitions = [], {}
    for file in sorted(active, key=lambda f: (f["stage"], f["family"], enumeration_key(f["path"]))):
        family, stage = file["family"], file["stage"]
        doc = file.get("document")
        if doc is None or file["kind"] not in {"script", "gui"}:
            continue
        supported = contract_family(profile, family)
        if family == "gui":
            supported = supported and profile.get("gui", {}).get("duplicate_definition") == "playset_last"
        for ordinal, node in enumerate(definition_nodes(doc, family)):
            if node.key is None or not node.is_block:
                continue
            raw_key, mode, name = node.key, "GUI_DEFINE" if family == "gui" and supported else "BARE", node.key
            prefix, sep, rest = raw_key.partition(":")
            if supported and family != "gui" and sep and prefix in MODE_ORDER:
                mode, name = prefix, rest
            key = f"{stage}/{family}/{name}"
            operation = {"id": f"{file['id']}:{node.start}", "key": key, "stage": stage,
                         "family": family, "definition_id": name, "raw_key": raw_key, "mode": mode,
                         "owner": file["owner"], "file_id": file["id"], "path": file["path"],
                         "ordinal": ordinal, "span": [node.start, node.end], "body": node_summary(node),
                         "_nodes": list(node.children), "_node": node, "_file": file,
                         "evidence_ids": evidence, "supported": supported}
            operations.append(operation)
    mode_order = ["BARE"] + list(profile.get("mode_order", MODE_ORDER))
    def order(op):
        if op["family"] == "gui":
            return (op["stage"], op["family"], 0, ((rank.get(op["owner"], -100), op["path"].encode()),), op["ordinal"])
        return (op["stage"], op["family"], mode_order.index(op["mode"]) if op["mode"] in mode_order else 99,
                enumeration_key(op["path"]), op["ordinal"])
    operations.sort(key=order)
    for operation in operations:
        key = operation["key"]
        current = definitions.get(key)
        if not operation["supported"]:
            if current is None:
                current = definitions[key] = {"key": key, "stage": operation["stage"], "family": operation["family"],
                                               "id": operation["definition_id"], "_nodes": [], "operations": [], "transitions": [],
                                               "provenance": [], "state": "unknown", "value": None, "field_states": {}}
            current["operations"].append(operation)
            current["provenance"].append(operation["id"])
            current["transitions"].append({"operation_id": operation["id"], "action": "unknown", "reason": "no conformed family/bare/reader rule"})
            continue
        mode = operation["mode"]
        transition = {"operation_id": operation["id"], "mode": mode, "owner": operation["owner"], "erased": []}
        if current is None and mode in {"INJECT", "REPLACE", "TRY_INJECT", "TRY_REPLACE"}:
            operation["outcome"] = "missing_target" if not mode.startswith("TRY_") else "no_op"
            if not mode.startswith("TRY_"):
                findings.append({"category": "confirmed_incompatibility", "kind": "missing_operation_target", "target": key,
                                 "certainty": "synthetic_contract", "impact": "strict operation target absent", "evidence_ids": evidence,
                                 "source_occurrences": [{"owner": operation["owner"], "file_id": operation["file_id"], "span": operation["span"]}],
                                 "repairability": "blocked_unknown"})
            continue
        if current is None:
            current = definitions[key] = {"key": key, "stage": operation["stage"], "family": operation["family"],
                                           "id": operation["definition_id"], "_nodes": [], "operations": [],
                                           "transitions": [], "provenance": [], "state": "known"}
            action = "create"
        elif mode == "BARE":
            action = "reject_duplicate"
            findings.append({"category": "confirmed_incompatibility", "kind": "duplicate_bare_definition", "target": key,
                             "certainty": "synthetic_contract", "impact": "second creation rejected", "evidence_ids": evidence,
                             "source_occurrences": [{"owner": operation["owner"], "file_id": operation["file_id"], "span": operation["span"]}],
                             "repairability": "blocked_unknown"})
        elif "REPLACE" in mode or mode == "GUI_DEFINE":
            action = "replace"
        else:
            action = "append"
        operation["outcome"] = action
        if action in {"create", "replace"}:
            transition["erased"] = list(current["provenance"])
            current["_nodes"] = list(operation["_nodes"])
            current["provenance"] = [operation["id"]]
        elif action == "append":
            current["_nodes"].extend(operation["_nodes"])
            current["provenance"].append(operation["id"])
        transition["action"] = action
        current["operations"].append(operation)
        current["transitions"].append(transition)
    for definition in definitions.values():
        if definition["state"] != "unknown":
            definition["value"], definition["state"], definition["field_states"] = read_body(definition["_nodes"], profile)
        definition["body"] = [node_summary(n) for n in definition["_nodes"]]
        definition["evidence_ids"] = evidence
        definition["confidence"] = "synthetic_contract" if contract_family(profile, definition["family"]) else "conditional_unknown"
    return {"definitions": list(definitions.values()), "operations": operations,
            "findings": findings, "active": active, "hidden": hidden}


def simulate_localization(files: list[dict], playset: list[str], profile: dict) -> list[dict]:
    """An explicit synthetic localization policy is separate from database modes."""
    groups = {}
    for file in files:
        if not file.get("active") or file["kind"] != "localization":
            continue
        for entry in file.get("entries", []):
            identity = (file["stage"], entry["language"], entry["key"])
            groups.setdefault(identity, []).append((file, entry))
    policy = profile.get("localization", {})
    supported = (contract_family(profile, "localization") and isinstance(policy, dict)
                 and policy.get("ordinary_filename") in {"first", "last"}
                 and policy.get("replacement_filename") in {"first", "last"}
                 and isinstance(policy.get("replace_priority"), bool))
    result = []
    for (stage, language, name), entries in groups.items():
        winner = None
        if supported:
            replacements = [(file, entry) for file, entry in entries if file.get("replace_tier")]
            selected = replacements if replacements and policy["replace_priority"] else entries
            replacement_tier = bool(replacements and policy["replace_priority"])
            direction = policy["replacement_filename"] if replacement_tier else policy["ordinary_filename"]
            paths = sorted({file["path"] for file, _ in selected}, key=enumeration_key)
            chosen_path = paths[0 if direction == "first" else -1]
            winner = max(((file, entry) for file, entry in selected if file["path"] == chosen_path), key=lambda pair: pair[1]["ordinal"])
        key = f"{stage}/localization/{language}:{name}"
        result.append({"key": key, "stage": stage, "family": "localization", "id": f"{language}:{name}",
                       "language": language, "localization_key": name, "state": "known" if supported else "unknown",
                       "value": {"text": winner[1]["value"]} if winner else None,
                       "field_states": {"text": {"state": "known" if supported else "unknown", "policy": "synthetic_localization" if supported else "unmeasured_localization"}},
                       "body": [{"owner": file["owner"], "path": file["path"], **entry} for file, entry in entries],
                       "operations": [], "transitions": [], "provenance": [winner[0]["id"]] if winner else [],
                       "evidence_ids": [profile["id"]], "confidence": "synthetic_contract" if supported else "conditional_unknown"})
    return result
