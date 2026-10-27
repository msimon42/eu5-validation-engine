"""Deterministic snapshot analysis. Unknown semantics remain explicit and local."""
from __future__ import annotations

import base64
import binascii
import copy
import json
import re
from collections import defaultdict

from .formats import parse_family, validate_virtual_path, path_risks, windows_key, classify
from .loading import normalized_profile, simulate, read_body, node_summary, is_base, contract_family, MODE_ORDER, definition_nodes
from .parser import digest


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not k.startswith("_") and k != "document"}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    return value


def finding(category, kind, target, message, **kwargs):
    return {"category": category, "kind": kind, "target": target, "message": message,
            "impact": kwargs.pop("impact", message), "certainty": kwargs.pop("certainty", "static"),
            "coverage": kwargs.pop("coverage", "static_contract"), "source_occurrences": kwargs.pop("source_occurrences", []),
            "evidence_ids": kwargs.pop("evidence_ids", []), "lost_obligation_ids": kwargs.pop("lost_obligation_ids", []),
            "runtime_requirements": kwargs.pop("runtime_requirements", []),
            "repairability": kwargs.pop("repairability", "investigate"), **kwargs}


def decode_inputs(inputs):
    files, issues, seen = [], [], set()
    if not isinstance(inputs, list) or len(inputs) > 200_000:
        raise ValueError("inputs must be a bounded array")
    total_bytes = 0
    for index, item in enumerate(inputs):
        try:
            if not isinstance(item, dict) or not isinstance(item.get("owner"), str) or not item["owner"]:
                raise ValueError("input owner missing")
            path = validate_virtual_path(item["path"])
            opaque = item.get("opaque_blob")
            if opaque is not None:
                if (not isinstance(opaque, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(opaque.get("sha256", "")))
                        or type(opaque.get("size")) is not int or not 0 <= opaque["size"] <= 2 ** 42
                        or item.get("sha256") != opaque["sha256"]):
                    raise ValueError("Invalid immutable opaque blob reference")
                identity = (item["owner"], path)
                if identity in seen:
                    raise ValueError("duplicate owner/path input")
                seen.add(identity)
                file_id = digest(json.dumps([item["owner"], path, opaque["sha256"]], ensure_ascii=False).encode())[:24]
                files.append({**classify(path), "id": file_id, "owner": item["owner"], "path": path,
                    "sha256": opaque["sha256"], "size": opaque["size"], "_raw": b"", "kind": "opaque",
                    "opaque_blob": opaque, "opaque": True, "diagnostics": [], "risks": path_risks(path)})
                continue
            if not isinstance(item.get("bytes_base64"), str):
                raise ValueError("bytes_base64 must be text")
            raw = base64.b64decode(item["bytes_base64"], validate=True)
            if base64.b64encode(raw).decode() != item["bytes_base64"]:
                raise ValueError("noncanonical base64")
            total_bytes += len(raw)
            if len(raw) > 8_000_000 or total_bytes > 128_000_000:
                raise ValueError("snapshot byte budget exceeded")
            identity = (item["owner"], path)
            if identity in seen:
                raise ValueError("duplicate owner/path input")
            seen.add(identity)
            file_hash = digest(raw)
            if item.get("sha256") is not None and item["sha256"] != file_hash:
                raise ValueError("declared input hash mismatch")
            family = parse_family(raw, path)
            file_id = digest(json.dumps([item["owner"], path, file_hash], ensure_ascii=False).encode())[:24]
            file = {"id": file_id, "owner": item["owner"], "path": path, "sha256": file_hash,
                    "size": len(raw), "_raw": raw, **family, "risks": path_risks(path)}
            files.append(file)
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            issues.append(finding("confirmed_incompatibility", "invalid_input", str(index), str(exc), repairability="invalid_input"))
    return files, issues


def source_records(files, playset, profile):
    records = []
    enabled = set(playset)
    for file in files:
        if file["owner"] not in enabled and not is_base(file["owner"]):
            continue
        if not file.get("document") or file["kind"] not in {"script", "gui"}:
            continue
        for node in definition_nodes(file["document"], file["family"]):
            if not node.key or not node.is_block:
                continue
            prefix, sep, rest = node.key.partition(":")
            mode = prefix if sep and prefix in MODE_ORDER and contract_family(profile, file["family"]) else "BARE"
            name = rest if mode != "BARE" else node.key
            key = f"{file['stage']}/{file['family']}/{name}"
            value, state, field_states = read_body(node.children, profile)
            records.append({"key": key, "owner": file["owner"], "file_id": file["id"], "path": file["path"],
                            "sha256": file["sha256"], "span": [node.start, node.end], "mode": mode,
                            "value": value, "state": state, "field_states": field_states, "active": file["active"],
                            "_nodes": list(node.children), "_node": node, "_file": file})
    return records


def baseline_for(key, records, baselines):
    entry = (baselines or {}).get(key, (baselines or {}).get(key.split("/", 1)[1]))
    if not isinstance(entry, dict):
        return None, None
    expected = entry.get("source_hash") or entry.get("sha256")
    matches = [r for r in records if r["key"] == key and r["sha256"] == expected and is_base(r["owner"])]
    if len(matches) != 1:
        return None, entry
    return matches[0], entry


def _leaves(nodes, path=()):
    result = {}
    counts = defaultdict(int)
    for node in nodes:
        if node.key is None:
            continue
        ordinal = counts[node.key]
        counts[node.key] += 1
        node_path = path + (f"{node.key}#{ordinal}",)
        if node.is_block:
            result.update(_leaves(node.children, node_path))
        else:
            result["/".join(node_path)] = node.value
    return result


def _shape(nodes):
    return [(n.key, n.operator, _shape(n.children) if n.is_block else None) for n in nodes]


def build_obligations(records, definitions, baselines, profile):
    obligations, findings = [], []
    defs = {d["key"]: d for d in definitions}
    by_key = defaultdict(list)
    for record in records:
        by_key[record["key"]].append(record)
    for key, group in by_key.items():
        mod_records = [r for r in group if not is_base(r["owner"]) and r["owner"] != "generated_patch"]
        base, entry = baseline_for(key, records, baselines)
        any_base = next((r for r in group if is_base(r["owner"])), None)
        effective = defs.get(key)
        exact_owners = (entry or {}).get("author_base_hashes", {})
        per_target = []
        for record in mod_records:
            ancestry = bool(base and exact_owners.get(record["owner"]) == base["sha256"])
            known_family = contract_family(profile, record["_file"]["family"])
            comparison_base = base or any_base
            expected = dict(record["value"])
            if comparison_base and record["mode"] in {"BARE", "REPLACE", "REPLACE_OR_CREATE", "TRY_REPLACE"}:
                for absent_field in comparison_base["value"].keys() - expected.keys():
                    expected[absent_field] = None
            leaves = _leaves(record["_nodes"])
            for field, value in expected.items():
                policy = profile.get("readers", {}).get(field, "unknown")
                if comparison_base and value == comparison_base["value"].get(field) and record["mode"] != "INJECT":
                    continue
                is_absence = field not in record["value"]
                is_unknown = record["field_states"].get(field, {}).get("state") != "known" and not (is_absence and policy in {"scalar_last", "scalar_first", "ordered_commands", "append_occurrences", "named_members", "map"})
                candidates = [(field, value, None, None)]
                if policy in {"named_members", "map"} and isinstance(value, dict) and not is_unknown:
                    previous = comparison_base["value"].get(field, {}) if comparison_base else {}
                    candidates = [(field, member_value, None, member_key) for member_key, member_value in value.items()
                                  if member_value != previous.get(member_key)]
                if policy == "ordered_commands" and comparison_base and _shape(record["_nodes"]) == _shape(comparison_base["_nodes"]):
                    old_leaves = _leaves(comparison_base["_nodes"])
                    candidates = [(field, leaf_value, leaf_path, None) for leaf_path, leaf_value in leaves.items()
                                  if leaf_path.startswith(field + "#") and leaf_value != old_leaves.get(leaf_path)]
                for top_field, desired, leaf_path, member_key in candidates:
                    supported = known_family and not is_unknown and (ancestry or comparison_base is None and record["mode"] == "BARE")
                    actual = effective.get("value", {}).get(top_field) if effective and effective.get("value") else None
                    if member_key is not None:
                        actual = actual.get(member_key) if isinstance(actual, dict) else None
                    if leaf_path:
                        actual = _leaves(effective.get("_nodes", [])).get(leaf_path) if effective else None
                    state = "satisfied" if supported and actual == desired else "violated" if supported else "unknown"
                    identity = [key, record["owner"], record["file_id"], record["span"], top_field, leaf_path, member_key, desired]
                    obligation = {"id": "obl-" + digest(json.dumps(identity, sort_keys=True).encode())[:20],
                                  "target": key, "definition_key": key, "owner": record["owner"], "field": top_field, "leaf_path": leaf_path, "member_key": member_key,
                                  "expected": desired, "expected_value": desired, "actual": actual, "state": state, "required": True,
                                  "kind": "field_absence" if is_absence else "ordered_occurrence_value" if leaf_path else "exact_value",
                                  "ancestry": "pinned_common_ancestor" if ancestry else "new_definition" if comparison_base is None else "unknown",
                                  "baseline_hash": base["sha256"] if ancestry else None,
                                  "source_occurrence": {"file_id": record["file_id"], "span": record["span"], "owner": record["owner"]},
                                  "evidence_ids": [profile["id"]], "observability": "synthetic_field" if known_family else "runtime_required"}
                    per_target.append(obligation)
                    obligations.append(obligation)
        # An entire shadowed definition may vanish even if no supported reader understands it.
        for record in mod_records:
            if not record["active"] and record["key"] not in defs:
                identity = [record["file_id"], record["span"], "whole_definition"]
                obligations.append({"id": "obl-" + digest(json.dumps(identity).encode())[:20], "target": key,
                                    "owner": record["owner"], "field": None, "state": "violated" if contract_family(profile, record["_file"]["family"]) else "unknown",
                                    "required": True, "kind": "definition_presence", "expected": True, "actual": False,
                                    "source_occurrence": {"file_id": record["file_id"], "span": record["span"]}, "evidence_ids": [profile["id"]]})
        if len({r["owner"] for r in mod_records}) < 2:
            continue
        contradictory = []
        keyed = defaultdict(list)
        for obligation in per_target:
            keyed[(obligation["field"], obligation["leaf_path"], obligation.get("member_key"))].append(obligation)
        for same_field in keyed.values():
            exact = [o for o in same_field if o["ancestry"] == "pinned_common_ancestor" and o["state"] != "unknown"]
            if len({json.dumps(o["expected"], sort_keys=True) for o in exact}) > 1:
                contradictory.extend(exact)
        if contradictory:
            findings.append(finding("confirmed_incompatibility", "contradictory_intents", key,
                                    "Competing exact-value obligations require a design choice.", certainty="synthetic_contract",
                                    lost_obligation_ids=[o["id"] for o in contradictory], repairability="blocked_design",
                                    alternatives=[{"owner": o["owner"], "field": o["field"], "value": o["expected"]} for o in contradictory]))
        elif per_target and all(o["ancestry"] == "pinned_common_ancestor" and o["state"] != "unknown" for o in per_target):
            findings.append(finding("compatible_overlap", "independent_intents", key,
                                    "Pinned source deltas can be compared under the synthetic reader.", certainty="synthetic_contract",
                                    lost_obligation_ids=[o["id"] for o in per_target if o["state"] != "satisfied"],
                                    repairability="mechanical" if all(o["field"] in profile.get("independent_fields", []) or o["leaf_path"] for o in per_target) else "decision_required"))
        else:
            # Equal whole replacements do not require ancestry to conclude their bytes agree.
            values = [r["value"] for r in mod_records]
            equal = bool(values) and all(v == values[0] for v in values)
            findings.append(finding("compatible_overlap" if equal else "potential_incompatibility",
                                    "identical_overrides" if equal else "unproven_ancestry_or_reader", key,
                                    "Equal replacement bodies retain both source owners." if equal else "Exact ancestry or field-reader prerequisites are missing.",
                                    repairability="no_repair_needed" if equal else "blocked_unknown"))
    return obligations, findings


def package_findings(files, playset):
    metadata = {f["owner"]: f.get("data") for f in files if f["kind"] == "metadata" and f.get("data")}
    identities, edges, findings = defaultdict(list), [], []
    for owner, data in metadata.items():
        identity = data.get("id", owner)
        identities[identity if isinstance(identity, str) else owner].append(owner)
    for identity, owners in identities.items():
        if len(owners) > 1:
            findings.append(finding("potential_incompatibility", "duplicate_package_id", str(identity), "Metadata identity is not unique.", owners=owners))
    for owner, data in metadata.items():
        if owner not in playset:
            continue
        relationships = data.get("relationships", [])
        for dependency in relationships if isinstance(relationships, list) else []:
            if not isinstance(dependency, dict) or dependency.get("rel_type") != "dependency":
                continue
            target = dependency.get("id")
            if not isinstance(target, str):
                findings.append(finding("potential_incompatibility", "invalid_dependency_identity", owner, "Dependency id must be text."))
                continue
            candidates = identities.get(target, [])
            enabled = [o for o in candidates if o in playset or is_base(o)]
            edges.append({"source": owner, "target": str(target), "certainty": "declared", "kind": "requires", "owners": candidates})
            if not enabled:
                findings.append(finding("confirmed_incompatibility", "missing_dependency" if not candidates else "disabled_dependency", owner,
                                        f"Required package {target!r} is absent from the enabled set.", repairability="blocked_unknown"))
            elif dependency.get("version"):
                # Matching is intentionally narrow; prerelease/range semantics remain unknown.
                for candidate in enabled:
                    actual = str(metadata[candidate].get("version", ""))
                    required = str(dependency["version"])
                    prefix = required[:-1] if required.endswith("*") else None
                    match = actual.startswith(prefix) if prefix is not None else actual == required
                    if not match:
                        findings.append(finding("potential_incompatibility", "dependency_version", owner,
                                                f"Declared version {required!r} does not match {actual!r}; enforcement is unconfirmed."))
    adjacency = defaultdict(set)
    for edge in edges:
        adjacency[edge["source"]].update(edge["owners"])
    def reaches(start, node, seen):
        if node in seen:
            return False
        seen.add(node)
        return any(child == start or reaches(start, child, seen) for child in adjacency[node])
    for owner in sorted(adjacency):
        if reaches(owner, owner, set()):
            findings.append(finding("potential_incompatibility", "dependency_cycle", owner,
                                    "Presence dependency cycle; this is not a proven strict-order contradiction."))
    return findings, edges


def analyze(inputs: list[dict], playset: list[str], profile: dict | None = None,
            baselines: dict | None = None) -> dict:
    if not isinstance(playset, list) or any(not isinstance(o, str) for o in playset) or len(playset) != len(set(playset)):
        raise ValueError("playset must be an ordered list of unique owner IDs")
    profile = normalized_profile(profile)
    files, findings = decode_inputs(inputs)
    simulation = simulate(files, playset, profile)
    findings.extend(simulation["findings"])
    from .loading import simulate_localization
    definitions = simulation["definitions"] + simulate_localization(files, playset, profile)
    records = source_records(files, playset, profile)
    obligations, intent_findings = build_obligations(records, definitions, baselines, profile)
    findings.extend(intent_findings)
    package_issues, package_edges = package_findings(files, playset)
    findings.extend(package_issues)
    definition_edges, behavior_edges = [], []
    available = {d["key"] for d in definitions}
    path_spellings = defaultdict(set)
    for file in files:
        path_spellings[windows_key(file["path"])].add(file["path"])
    for file in files:
        for diagnostic in file.get("diagnostics", []):
            findings.append(finding("confirmed_incompatibility" if diagnostic.get("severity") != "warning" else "potential_incompatibility",
                                    "parse_diagnostic", file["path"], diagnostic["code"],
                                    source_occurrences=[{"file_id": file["id"], "span": diagnostic.get("span")}],
                                    repairability="blocked_unknown"))
        for risk in file["risks"]:
            findings.append(finding("potential_incompatibility", "portability", file["path"], risk))
        if len(path_spellings[windows_key(file["path"])]) > 1:
            findings.append(finding("potential_incompatibility", "windows_path_alias", file["path"], "Distinct source spellings share a Windows comparison key."))
    for definition in definitions:
        nodes = definition.get("_nodes", [])
        for node in nodes:
            if node.key in profile.get("reference_fields", {}) and node.value:
                expression = node.value.strip('"')
                dynamic = any(c in expression for c in "$[]@")
                target = f"{definition['stage']}/{definition['family']}/{expression}"
                edge = {"source": definition["key"], "target": target if not dynamic else None,
                        "expression": expression, "certainty": "dynamic" if dynamic else "literal", "span": [node.start, node.end],
                        "resolved": None if dynamic else target in available, "evidence_ids": [profile["id"]]}
                definition_edges.append(edge)
                if not dynamic and target not in available:
                    findings.append(finding("confirmed_incompatibility", "missing_reference", definition["key"],
                                            f"Literal reference {expression!r} has no active definition.", repairability="blocked_unknown"))
                if dynamic:
                    findings.append(finding("potential_incompatibility", "dynamic_reference", definition["key"],
                                            "Dynamic reference remains unresolved."))
            for descendant in node.walk():
                if descendant.key and any(descendant.key.startswith(prefix) for prefix in ("var:", "global_var:", "local_var:")):
                    behavior_edges.append({"source": definition["key"], "kind": "variable_access", "expression": descendant.key,
                                           "certainty": "unknown", "span": [descendant.start, descendant.end]})
                if descendant.key and descendant.key in {"add_reward", "add_gold"}:
                    behavior_edges.append({"source": definition["key"], "kind": "effect", "expression": descendant.key,
                                           "value": descendant.value, "certainty": "syntactic", "span": [descendant.start, descendant.end]})
    rewards = [edge for edge in behavior_edges if edge["kind"] == "effect"]
    if len(rewards) > 1:
        findings.append(finding("semantic_gameplay_conflict", "shared_reward_effects", "behavior/rewards",
                                "Multiple reward effects survive; execution counts and intended balance need observations.",
                                runtime_requirements=["observe callback reachability and reward counts"], repairability="blocked_design"))
    # Separate localization/GUI and opaque payload analysis from synthetic script rules.
    locale_effective = {d["key"]: d for d in definitions if d["family"] == "localization"}
    for file in files:
        if file["kind"] != "localization" or is_base(file["owner"]) or file["owner"] == "generated_patch" or file["owner"] not in playset:
            continue
        for entry in file.get("entries", []):
            key = f"{file['stage']}/localization/{entry['language']}:{entry['key']}"
            effective = locale_effective.get(key)
            actual = effective.get("value", {}).get("text") if effective and effective.get("value") else None
            known = effective and effective["state"] == "known"
            identity = [file["id"], entry["span"], key, "text"]
            obligations.append({"id": "obl-" + digest(json.dumps(identity).encode())[:20], "target": key,
                                "definition_key": key, "owner": file["owner"], "field": "text", "leaf_path": None,
                                "expected": entry["value"], "expected_value": entry["value"], "actual": actual,
                                "state": "satisfied" if known and actual == entry["value"] else "violated" if known else "unknown",
                                "required": True, "kind": "exact_label", "ancestry": "explicit_label", "baseline_hash": None,
                                "source_occurrence": {"file_id": file["id"], "span": entry["span"], "owner": file["owner"]},
                                "evidence_ids": [profile["id"]], "observability": "synthetic_localization" if known else "runtime_required"})
    locale_groups = defaultdict(list)
    asset_groups = defaultdict(list)
    for file in files:
        if file["kind"] == "localization":
            for entry in file.get("entries", []):
                locale_groups[(file["stage"], entry["language"], entry["key"])].append((file, entry))
        if file["kind"] == "opaque" and file["family"] == "asset":
            asset_groups[windows_key(file["path"])].append(file)
    for identity, entries in locale_groups.items():
        enabled = [(file, entry) for file, entry in entries if file["owner"] in playset or is_base(file["owner"])]
        if len({entry["raw_value"] for _, entry in enabled}) > 1:
            findings.append(finding("confirmed_incompatibility", "localization_labels", f"{identity[0]}/localization/{identity[1]}:{identity[2]}",
                                    "Competing exact labels require a user choice; loader precedence remains unconfirmed.", repairability="blocked_design"))
    for path, group in asset_groups.items():
        enabled = [f for f in group if f["owner"] in playset or is_base(f["owner"])]
        if len(enabled) > 1 and len({f["sha256"] for f in enabled}) > 1:
            findings.append(finding("potential_incompatibility", "asset_payload_conflict", path,
                                    "Unequal opaque payloads need a design decision or format-aware composition.", repairability="blocked_design"))
    for file in files:
        if file["kind"] != "opaque" or is_base(file["owner"]) or file["owner"] == "generated_patch" or file["owner"] not in playset:
            continue
        winner = next((candidate for candidate in files if candidate["active"] and windows_key(candidate["path"]) == windows_key(file["path"])), None)
        known_bytes = file["family"] == "asset"
        equal = winner is not None and winner["sha256"] == file["sha256"]
        obligations.append({"id": "obl-" + digest(json.dumps([file["id"], "opaque_payload"]).encode())[:20],
                            "target": "resource/" + file["path"], "definition_key": "resource/" + file["path"],
                            "owner": file["owner"], "field": "payload", "expected": file["sha256"], "expected_value": file["sha256"],
                            "actual": winner["sha256"] if winner else None, "required": True, "kind": "opaque_payload",
                            "state": "satisfied" if known_bytes and equal else "violated" if known_bytes else "unknown",
                            "source_occurrence": {"file_id": file["id"], "span": [0, file["size"]]},
                            "evidence_ids": [profile["id"]], "observability": "byte_hash_only" if known_bytes else "unsupported_family"})
    unknown_files = [f["id"] for f in files if f["kind"] == "opaque" or not contract_family(profile, f["family"])]
    manifest = [{"owner": f["owner"], "path": f["path"], "sha256": f["sha256"]} for f in files]
    input_hash = digest(json.dumps({"files": sorted(manifest, key=lambda f: (f["owner"], f["path"])), "playset": playset}, sort_keys=True).encode())
    for index, issue in enumerate(findings):
        issue.setdefault("id", "finding-" + digest(json.dumps(public(issue), sort_keys=True).encode())[:20])
        issue.setdefault("cluster_id", "cluster-" + digest(issue.get("target", "unknown").encode())[:12])
        issue.setdefault("title", {"independent_intents": "Independent field changes", "contradictory_intents": "Competing exact values",
                                   "exact_path_shadow": "Whole-file shadow", "unproven_ancestry_or_reader": "Preservation prerequisites unknown",
                                   "missing_reference": "Missing active reference", "parse_diagnostic": "Source syntax or encoding issue",
                                   "identical_overrides": "Identical overrides", "localization_labels": "Competing localization labels"}.get(issue["kind"], issue["kind"].replace("_", " ").capitalize()))
        issue.setdefault("description", issue.get("message", issue.get("impact", "Inspect source evidence and coverage.")))
    for obligation in obligations:
        selector = obligation.get("leaf_path") or obligation.get("field") or "definition presence"
        if obligation.get("member_key"):
            selector += "." + obligation["member_key"]
        target_name = obligation["target"].rsplit("/", 1)[-1]
        desired = obligation.get("expected_value", obligation.get("expected"))
        text_value = desired if isinstance(desired, str) else json.dumps(desired, ensure_ascii=False, sort_keys=True)
        obligation["description"] = f"{obligation['owner']} requires {target_name}.{selector} = {text_value}"
    file_outputs = []
    for file in files:
        doc = file.get("document")
        file_outputs.append({"id": file["id"], "owner": file["owner"], "path": file["path"], "sha256": file["sha256"],
                             "size": file["size"], "kind": file["kind"], "family": file["family"], "stage": file["stage"],
                             "opaque_blob": file.get("opaque_blob"),
                             "active": file["active"], "shadowed_by": file["shadowed_by"], "diagnostics": file["diagnostics"],
                             "encoding": doc.encoding if doc else None, "bom": doc.bom.hex() if doc else None,
                             "newline": doc.newline if doc else None, "snippet": file["_raw"][:512].decode("utf-8", "backslashreplace"),
                             "entries": file.get("entries", []), "metadata": file.get("data"),
                             "occurrences": [node_summary(n) for n in doc.children[:200]] if doc and file["kind"] in {"script", "gui"} else []})
    result = {"input_manifest_hash": input_hash, "playset": list(playset), "profile": profile,
              "baselines": copy.deepcopy(baselines or {}), "files": file_outputs, "definitions": public(definitions),
              "source_definitions": public(records), "findings": findings, "obligations": obligations,
              "graphs": {"package": package_edges, "definition": definition_edges,
                         "operation": [{"id": op["id"], "source": op["file_id"], "target": op["key"], "mode": op["mode"],
                                        "outcome": op.get("outcome", "unknown"), "span": op["span"], "evidence_ids": op["evidence_ids"]} for op in simulation["operations"]],
                         "behavior": behavior_edges},
              "coverage": {"mode": "synthetic_contract" if profile["kind"] == "synthetic" else "conditional_static",
                           "supported_families": profile.get("families", []) if profile["kind"] == "synthetic" else [],
                           "opaque_or_unsupported_files": unknown_files, "conformed_rules": 0, "game_runs": 0,
                           "production_export_enabled": False, "remaining": ["Windows build-scoped conformance", "gameplay behavior observations"]}}
    result["summary"] = {"files": len(files), "definitions": len(definitions), "findings": len(findings),
                         "obligations": len(obligations), "unknown_obligations": sum(o["state"] == "unknown" for o in obligations),
                         "violated_obligations": sum(o["state"] == "violated" for o in obligations),
                         "state": "invalid_input" if any(f["kind"] == "invalid_input" for f in findings) else
                                  "needs_attention" if any(f["category"] != "compatible_overlap" for f in findings) else "analyzed",
                         "llm_calls": 0, "game_runs": 0}
    return result
