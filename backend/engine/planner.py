"""Deterministic preservation planner; output is managed staging material only."""
from __future__ import annotations

import base64
import copy
import json
from collections import defaultdict

from .analysis import analyze, decode_inputs, source_records, baseline_for, _shape
from .loading import is_base, node_value
from .parser import Edit, apply_edits, digest, parse


def _nodes_at_paths(nodes, prefix=()):
    counts, result = defaultdict(int), {}
    for node in nodes:
        if node.key is None:
            continue
        ordinal = counts[node.key]
        counts[node.key] += 1
        path = prefix + (f"{node.key}#{ordinal}",)
        result["/".join(path)] = node
        result.update(_nodes_at_paths(node.children, path))
    return result


def _render_scalar(value):
    if not isinstance(value, str):
        raise ValueError("scalar targets must retain exact string spelling")
    candidate = parse(("x = " + value).encode())
    if not candidate.eligible or len(candidate.children) != 1 or candidate.children[0].is_block:
        raise ValueError("target is not one scalar")
    return value.encode()


def plan_repair(analysis: dict, inputs: list[dict], decisions: dict | None = None) -> dict:
    current = analyze(inputs, analysis.get("playset", []), analysis.get("profile"), analysis.get("baselines"))
    read_set = [{"owner": f["owner"], "path": f["path"], "sha256": f["sha256"]} for f in current["files"]]
    result = {"status": "blocked_unknown", "files": [], "obligations": copy.deepcopy(current["obligations"]),
              "read_set": read_set, "write_set": [], "findings": copy.deepcopy(current["findings"]),
              "reason": "Prerequisites have not been proved.", "input_manifest_hash": current["input_manifest_hash"],
              "profile_hash": current["profile"]["hash"], "before": current,
              "after": None, "beforeprediction": current["definitions"], "afterprediction": None,
              "production_export_enabled": False, "experimental_only": True, "decisions": copy.deepcopy(decisions or {})}
    def block(status, reason):
        result["status"], result["reason"] = status, reason
        return result
    if current["input_manifest_hash"] != analysis.get("input_manifest_hash") or current["profile"]["hash"] != analysis.get("profile", {}).get("hash"):
        return block("blocked_unknown", "Stale snapshot or profile; rescan before planning.")
    if any(f["kind"] == "invalid_input" for f in current["findings"]):
        return block("invalid_input", "Input/path validation failed; no files were generated.")
    if any(f["kind"] in {"windows_path_alias", "portability"} for f in current["findings"]):
        return block("blocked_unknown", "Target filename aliases/order need an explicit calibrated path policy.")
    if any(f["kind"] == "parse_diagnostic" for f in current["findings"]):
        return block("blocked_unknown", "Unsupported encoding or malformed regions require a separate explicit repair.")
    if any(f["kind"] in {"missing_reference", "missing_dependency", "disabled_dependency", "duplicate_bare_definition", "missing_operation_target"}
           for f in current["findings"]):
        return block("blocked_unknown", "A reference, package or operation prerequisite is unsatisfied.")
    if any(f["kind"] in {"asset_payload_conflict", "shared_reward_effects"} for f in current["findings"]):
        return block("blocked_design", "This family or gameplay choice needs a concrete supported design workflow.")
    if any(f["kind"] == "localization_labels" and not ((decisions or {}).get(f["target"]) or (decisions or {}).get(f["target"].split("/", 1)[1])) for f in current["findings"]):
        return block("blocked_design", "Competing labels require an exact approved text and waiver.")
    obligations = current["obligations"]
    unresolved = [o for o in obligations if o["state"] in {"violated", "unknown"}]
    if not unresolved:
        result.update(status="no_repair_needed", reason="No declared synthetic preservation obligation needs a patch.",
                      after=current, afterprediction=current["definitions"])
        return result
    # Equal bodies need no write, while uncertain ancestry remains visible in the report.
    targets_needing_change = {o["target"] for o in unresolved}
    if targets_needing_change and all(any(f["target"] == key and f["kind"] == "identical_overrides" for f in current["findings"]) for key in targets_needing_change):
        result.update(status="no_repair_needed", reason="Identical replacement bodies need no generated patch; ancestry remains unproved.",
                      after=current, afterprediction=current["definitions"])
        return result
    if current["profile"]["kind"] != "synthetic":
        return block("blocked_unknown", "Real-game rules have no archived build-scoped conformance; automatic repair is disabled.")
    known_changes = {o["target"] for o in obligations if o["state"] == "violated"}
    if not known_changes or any(o["state"] == "unknown" and o["target"] in known_changes for o in obligations):
        return block("blocked_unknown", "Affected repair targets require exact ancestry and known readers.")
    # Independent mechanical staging may continue; unrelated unknown obligations remain required.
    targets_needing_change = known_changes
    files, _ = decode_inputs(inputs)
    # Re-run selection flags before extracting source records.
    from .loading import simulate
    simulate(files, current["playset"], current["profile"])
    records = source_records(files, current["playset"], current["profile"])
    by_target = defaultdict(list)
    for obligation in obligations:
        by_target[obligation["target"]].append(obligation)
    waivers, generated, gui_outputs = {}, [], {}
    for key in sorted(targets_needing_change):
        target_obligations = by_target[key]
        decision = (decisions or {}).get(key, (decisions or {}).get(key.split("/", 1)[1]))
        if decision:
            if not isinstance(decision, dict) or decision.get("input_manifest_hash") != current["input_manifest_hash"] or decision.get("profile_hash") != current["profile"]["hash"]:
                return block("blocked_design", "Design decision is stale or lacks exact input/profile preconditions.")
            unknown_waivers = set(decision.get("waive", [])) - {o["id"] for o in target_obligations}
            if unknown_waivers:
                return block("blocked_design", "Design decision names unknown obligations.")
            for obligation_id in decision.get("waive", []):
                waivers[obligation_id] = {"input_manifest_hash": current["input_manifest_hash"], "reason": decision.get("reason", "User selected concrete alternative"), "target": key}
        desires = defaultdict(list)
        for obligation in target_obligations:
            if obligation["id"] not in waivers:
                desires[(obligation["field"], obligation.get("leaf_path"), obligation.get("member_key"))].append(obligation)
        chosen = {}
        for selector, desired_obligations in desires.items():
            values = {json.dumps(o["expected"], sort_keys=True) for o in desired_obligations}
            if len(values) > 1:
                return block("blocked_design", "Competing exact values require an approved choice and narrow waiver.")
            chosen[selector] = desired_obligations[0]["expected"]
        stage, family, identifier = key.split("/", 2)
        if family == "localization":
            if not decision or len(chosen) != 1:
                return block("blocked_design", "Choose one exact localization label and waive conflicting labels.")
            desired = next(iter(chosen.values()))
            if decision.get("values", {}).get("text") != desired:
                return block("blocked_design", "Approved text does not match the unwaived label obligation.")
            language, label_key = identifier.split(":", 1)
            raw_value = next((entry["raw_value"] for file in files if file["kind"] == "localization" for entry in file.get("entries", [])
                              if entry["language"] == language and entry["key"] == label_key and entry["value"] == desired), None)
            if raw_value is None:
                return block("blocked_unknown", "Custom localization emission requires a supported exact quoting policy.")
            emitted = b"\xef\xbb\xbf" + f"l_{language}:\n {label_key}:0 {raw_value}\n".encode()
            path = f"{stage}/localization/{language}/replace/zz_compat_{digest(key.encode())[:10]}_l_{language}.yml"
            generated.append({"owner": "generated_patch", "path": path, "bytes_base64": base64.b64encode(emitted).decode()})
            continue
        baseline, entry = baseline_for(key, records, current.get("baselines"))
        if baseline is None:
            return block("blocked_unknown", "Exact author baseline is unavailable.")
        group = [r for r in records if r["key"] == key and not is_base(r["owner"]) and r["owner"] != "generated_patch"]
        if not group:
            return block("blocked_unknown", "No source occurrence identifies a repair target.")
        for field, leaf_path, member_key in chosen:
            if field not in current["profile"].get("independent_fields", []) and not leaf_path and not decision:
                return block("blocked_design", "Field independence is not established; approve a concrete combined intent first.")
        template = max(group, key=lambda r: r["_node"].value_end - r["_node"].value_start)
        if family == "gui":
            active_group = [r for r in group if r["active"]]
            if len(active_group) != 1 or current["profile"].get("gui", {}).get("composition") != "pinned_disjoint_fields":
                return block("blocked_unknown", "GUI composition requires an explicit whole-file synthetic policy and one active template.")
            template = active_group[0]
            if any(r["_node"].head != baseline["_node"].head or r["_node"].tag != baseline["_node"].tag for r in group):
                return block("blocked_unknown", "Changed GUI declaration/inheritance identity requires a separate supported edit.")
        doc = template["_file"]["document"]
        node = template["_node"]
        if not doc.eligible or node.recovered:
            return block("blocked_unknown", "Template has unsupported or recovered syntax.")
        paths = _nodes_at_paths(template["_nodes"])
        edits = []
        supplied_values = decision.get("values", {}) if decision else {}
        for (field, leaf_path, member_key), desired in chosen.items():
            if field in supplied_values:
                approved = supplied_values[field].get(member_key) if member_key is not None and isinstance(supplied_values[field], dict) else supplied_values[field]
                if approved != desired and not leaf_path:
                    return block("blocked_design", "Approved value contradicts an unwaived obligation.")
                desired = approved if not leaf_path else desired
            if member_key is not None:
                parents = [n for n in template["_nodes"] if n.key == field and n.is_block]
                children = [n for parent in parents for n in parent.children if n.key == member_key and not n.is_block]
                target = children[-1] if children else None
            elif leaf_path:
                if any(_shape(r["_nodes"]) != _shape(baseline["_nodes"]) for r in group):
                    return block("blocked_unknown", "Repeated sequence alignment is ambiguous.")
                target = paths.get(leaf_path)
            else:
                occurrences = [n for n in template["_nodes"] if n.key == field]
                target = occurrences[-1] if occurrences else None
            if desired is None and not leaf_path and member_key is None:
                if target is not None:
                    old = doc.raw[target.start:target.end]
                    edits.append(Edit(target.start, target.end, b"", digest(old), target.ordinal))
                continue
            if target is None or target.is_block:
                return block("blocked_unknown", "No supported exact scalar occurrence exists in the complete template.")
            literal = desired
            if not leaf_path:
                source_literals = [candidate.value for record in group for candidate in record["_node"].walk()
                                   if candidate.key == (member_key or field) and not candidate.is_block and node_value(candidate) == desired]
                if source_literals:
                    literal = source_literals[0]
            try:
                replacement = _render_scalar(literal)
            except ValueError as exc:
                return block("blocked_design", str(exc))
            old = doc.raw[target.value_start:target.value_end]
            if replacement != old:
                edits.append(Edit(target.value_start, target.value_end, replacement, digest(old), target.ordinal))
        if family == "gui":
            output = gui_outputs.setdefault(template["path"], {"doc": doc, "edits": []})
            if output["doc"].sha256 != doc.sha256:
                return block("blocked_unknown", "GUI targets disagree on the complete effective file template.")
            output["edits"].extend(edits)
            continue
        try:
            edited = apply_edits(doc, edits, doc.sha256)
        except ValueError as exc:
            return block("blocked_unknown", str(exc))
        delta = sum(len(edit.replacement) - (edit.end - edit.start) for edit in edits)
        body = edited[node.value_start:node.value_end + delta]
        emitted = b"REPLACE:" + key.rsplit("/", 1)[1].encode() + b" = " + body + b"\n"
        if not parse(emitted).eligible:
            return block("blocked_unknown", "Generated patch does not strict-reparse.")
        stage, family, identifier = key.split("/", 2)
        path = f"{stage}/common/{family}/zz_compat_{digest(key.encode())[:10]}.txt"
        # No claim that zz is authoritative: the actual whole stack is simulated below.
        generated.append({"owner": "generated_patch", "path": path, "bytes_base64": base64.b64encode(emitted).decode()})
    for path, output in sorted(gui_outputs.items()):
        try:
            raw = apply_edits(output["doc"], output["edits"], output["doc"].sha256)
        except ValueError as exc:
            return block("blocked_unknown", str(exc))
        generated.append({"owner": "generated_patch", "path": path, "bytes_base64": base64.b64encode(raw).decode()})
    playset = [owner for owner in current["playset"] if owner != "generated_patch"] + ["generated_patch"]
    after = analyze(inputs + generated, playset, current["profile"], current.get("baselines"))
    updated = copy.deepcopy(after["obligations"])
    for obligation in updated:
        if obligation["id"] in waivers:
            obligation.update(state="waived_by_user", waiver=waivers[obligation["id"]])
    previous_ids = {o["id"] for o in obligations}
    after_ids = {o["id"] for o in updated}
    if previous_ids - after_ids:
        return block("blocked_unknown", "Final-stack analysis omitted affected obligations.")
    before_defs = {d["key"]: d for d in current["definitions"]}
    after_defs = {d["key"]: d for d in after["definitions"]}
    prior_obligations = {o["id"]: o for o in obligations}
    remaining_unknown = []
    for obligation in updated:
        if obligation["state"] in {"satisfied", "waived_by_user"}:
            continue
        target = obligation["target"]
        unchanged_unknown = (obligation["state"] == "unknown" and target not in targets_needing_change
                             and prior_obligations.get(obligation["id"], {}).get("state") == "unknown"
                             and before_defs.get(target, {}).get("body") == after_defs.get(target, {}).get("body")
                             and before_defs.get(target, {}).get("provenance") == after_defs.get(target, {}).get("provenance"))
        if not unchanged_unknown:
            return block("blocked_unknown", "Final-stack simulation does not preserve every affected unwaived contribution.")
        remaining_unknown.append(obligation["id"])
    if any(f["kind"] in {"missing_reference", "missing_operation_target", "duplicate_bare_definition", "parse_diagnostic"} for f in after["findings"]):
        return block("blocked_unknown", "Final-stack structural/reference checks failed.")
    after["obligations"] = updated
    result.update(status="repair_expected", files=generated, obligations=updated, reason="Complete synthetic final-stack obligations are satisfied or explicitly waived.",
                  write_set=[{"owner": f["owner"], "path": f["path"], "sha256": digest(base64.b64decode(f["bytes_base64"]))} for f in generated],
                  after=after, afterprediction=after["definitions"], waived_obligation_ids=sorted(waivers), validation_blockers=remaining_unknown)
    return result
