"""CK3 discovery diagnostics tied to captured identities, never live mod reads."""
from __future__ import annotations

import copy
from collections.abc import Sequence
import hashlib
import json


def discovery_diagnostic_details(diagnostic: dict, discovery: dict, ordinal: int,
                                 packages: Sequence[dict] = ()) -> dict:
    registry = diagnostic.get("registry_path")
    target = registry or diagnostic.get("path") or diagnostic.get("root") or "CK3 launcher"
    code = diagnostic.get("code", "discovery_unknown")
    mod = next((item for item in discovery.get("mods", [])
                if registry and item.get("registry_path") == registry), {})
    package = next((item for item in packages if registry and (
        item.get("path") == registry or item.get("owner") == "ck3:" + registry)), {})
    names = package.get("data", {}).get("name", [])
    mod_name = mod.get("name")
    name = (mod_name if isinstance(mod_name, str) and mod_name else None) or (
        next((value for value in names if isinstance(value, str)), None)
        if isinstance(names, list) else names if isinstance(names, str) else None)
    reason = diagnostic.get("message") or mod.get("reason") or str(code).replace("_", " ")
    title = f"{name or target} · {str(code).replace('_', ' ').capitalize()}"
    provenance = {"kind": "captured_ck3_discovery_diagnostic", "evidence_label": "V",
                  "discovery_id": discovery.get("id"),
                  "configuration_hash": discovery.get("configuration_hash"),
                  "diagnostic_ordinal": ordinal}
    occurrences = []
    if registry:
        provenance.update(registry_path=registry, owner=mod.get("owner") or package.get("owner") or "ck3:" + registry)
        if name:
            provenance["mod_name"] = name
        source = next((item for item in discovery.get("metadata_inputs", [])
                       if item.get("kind") == "descriptor" and item.get("path") == registry), package)
        checksum = source.get("sha256") or mod.get("descriptor_sha256")
        if checksum:
            provenance["descriptor_sha256"] = checksum
            occurrences.append({"owner": provenance["owner"], "path": registry, "sha256": checksum,
                                **({"file_id": source["id"]} if source.get("id") else {})})
    return {"target": target, "title": title, "message": f"{target}: {reason}",
            "severity": diagnostic.get("severity", "warning"), "diagnostic": copy.deepcopy(diagnostic),
            "diagnostic_provenance": provenance, "source_occurrences": occurrences}


def discovery_finding(diagnostic: dict, discovery: dict, ordinal: int,
                      packages: Sequence[dict] = ()) -> dict:
    from .analysis import finding

    details = discovery_diagnostic_details(diagnostic, discovery, ordinal, packages)
    result = finding("uncertain_risk", diagnostic.get("code", "discovery_unknown"),
                     details.pop("target"), details.pop("message"), certainty="inspected_source",
                     coverage="discovery", repairability="blocked_unknown", **details)
    identity = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    result["id"] = "finding-" + hashlib.sha256(identity).hexdigest()[:20]
    result["cluster_id"] = "cluster-" + hashlib.sha256(str(result["target"]).encode()).hexdigest()[:12]
    return result
