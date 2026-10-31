"""Complete, bounded-query CK3 issue index. Findings are observations, not winners."""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
import hashlib

from backend.app.store import canonical, digest
from backend.engine.ck3 import _base
from backend.engine.formats import parse_localization
from backend.engine.parser import parse

INDEX_VERSION = "conversation-issues-1"
KINDS = {"overlapping_path", "duplicate_definition", "localization_overlap", "windows_path_alias"}
TOPICS = {"call_ally_interaction": "Calling allies", "declare_war_interaction": "Declaring war"}


def metadata(path):
    parts = path.casefold().split("/")
    return any(part in {".git", ".ds_store", "desktop.ini"} for part in parts) or (
        len(parts) == 1 and (parts[0].startswith(("readme", "thumbnail.", "license", "changelog", "changes.", "specialthanks"))
                            or parts[0].endswith((".md", ".gitattributes", ".gitignore"))))


class CapturedSources:
    """Read only immutable, hash-checked blobs; never trust exported display bodies."""
    def __init__(self, store, scan):
        self.store = store
        self.inputs = {(item["owner"], item["path"]): item for item in scan["inputs"]}
        self.cache = OrderedDict()
        self.cache_bytes = 0

    def raw(self, owner, path):
        item = self.inputs[owner, path]
        checksum = item["sha256"]
        if checksum in self.cache:
            self.cache.move_to_end(checksum)
            return self.cache[checksum]
        # CAS paths are generated here; client paths cannot select managed files.
        raw = self.store.fs.read_bytes(f"blobs/sha256/{checksum[:2]}/{checksum}")
        if digest(raw) != checksum:
            raise ValueError("A saved copy changed. Please scan again.")
        while self.cache and self.cache_bytes + len(raw) > 32 * 1024 * 1024:
            _, removed = self.cache.popitem(last=False)
            self.cache_bytes -= len(removed)
        if len(raw) <= 32 * 1024 * 1024:
            self.cache[checksum] = raw
            self.cache_bytes += len(raw)
        return raw

    def occurrence(self, occurrence, *, statement=False):
        result = {**occurrence, "sha256": self.inputs[occurrence["owner"], occurrence["path"]]["sha256"]}
        if statement:
            raw = self.raw(result["owner"], result["path"])
            start, end = result["span"]
            if not 0 <= start < end <= len(raw):
                raise ValueError("The saved change location is invalid.")
            statement_raw = raw[start:end]
            doc = parse(statement_raw, dialect="gui" if result["path"].endswith(".gui") else "script")
            result["statement_sha256"] = digest(statement_raw)
            result["token_sha256"] = digest(canonical([(t.kind, t.text) for t in doc.tokens
                if t.kind not in {"trivia", "comment", "bom"}])) if doc.eligible else None
        return result


def relation(occurrences, key):
    values = [item.get(key) for item in occurrences if not _base(item["owner"])]
    return "unknown" if not values or None in values else "identical" if len(set(values)) == 1 else "different"


def base_relation(occurrences, owner):
    baseline = [o.get("token_sha256") for o in occurrences if _base(o["owner"])]
    selected = [o.get("token_sha256") for o in occurrences if o["owner"] == owner]
    if not baseline:
        return "not_available"
    if not selected or None in baseline + selected:
        return "unknown"
    return "identical" if set(selected) == set(baseline) else "different"


def build_index(store, scan, discovery=None, checkpoint=lambda *args: None):
    if scan.get("game_id") != "ck3":
        raise ValueError("This assistant currently handles Crusader Kings III.")
    sources = CapturedSources(store, scan)
    names = {"V": "The game"}
    for package in scan["analysis"].get("package_metadata", []):
        values = package.get("data", {}).get("name", [])
        if isinstance(values, list) and values:
            names[package["owner"]] = str(values[0])
    for mod in (discovery or {}).get("mods", []):
        if mod.get("name"):
            names[mod["owner"]] = mod["name"]
    issues, diagnostics = [], Counter()

    def add(kind, target, occurrences, comparison, *, internal=False, language=None):
        mods = sorted({item["owner"] for item in occurrences if not _base(item["owner"])})
        if len(mods) < 2 and not internal:
            return
        suffix = target.rsplit("/", 1)[-1]
        topic = TOPICS.get(suffix, "Names and descriptions" if kind == "localization_overlap" else
                           "Shared game files" if kind == "overlapping_path" else "Shared game changes")
        identifier = "issue_" + digest(canonical([scan["id"], kind, target,
            [(o["owner"], o["path"], o.get("span"), o["sha256"]) for o in occurrences]]))[:24]
        issues.append({"id": identifier, "kind": kind, "target": target, "area": topic,
            "title": (f"Different wording inside {names.get(mods[0], 'one mod')}" if internal else
                      "Two mods provide different names for the same option" if kind == "localization_overlap" else
                      f"More than one mod changes {topic.lower()}"),
            "what_is_known": "The saved versions differ." if comparison == "different" else
                             "The compared content is identical." if comparison == "identical" else
                             "These mods share a change, but it has not been fully compared.",
            "what_is_unknown": "What the game will keep, and whether either mod loses a feature, has not been tested.",
            "comparison": comparison, "internal": internal,
            "metadata_only": all(metadata(item["path"]) for item in occurrences),
            "mods": [{"owner": owner, "name": names.get(owner, owner)} for owner in mods],
            "sources": occurrences, "language": language,
            "current_game_comparison": [{"owner": owner,
                "relation": base_relation(occurrences, owner)}
                for owner in mods] if kind == "duplicate_definition" else [],
            "repair_available": suffix == "call_ally_interaction", "gameplay_effect": "unconfirmed"})

    for finding in scan["analysis"].get("findings", []):
        kind = finding["kind"]
        if kind not in KINDS:
            diagnostics[kind] += 1
            continue
        if kind == "localization_overlap":
            continue  # Re-index every captured localization file below, including deferred text.
        occurrences = finding.get("source_occurrences", [])
        if len({item["owner"] for item in occurrences if not _base(item["owner"])}) < 2:
            continue
        occurrences = [sources.occurrence(item, statement=kind == "duplicate_definition") for item in occurrences]
        add(kind, finding["target"], occurrences, relation(occurrences,
            "token_sha256" if kind == "duplicate_definition" else "sha256"))

    locale = defaultdict(list)
    locale_files, locale_entries, locale_gaps = 0, 0, []
    # Mod-owned files suffice for cross-mod and within-mod comparisons. Vanilla
    # overrides remain in the complete saved scan, never mislabelled as inter-mod issues.
    candidates = [item for item in scan["inputs"] if not _base(item["owner"]) and
                  item["owner"] in scan["playset"] and item["path"].startswith("localization/") and
                  item["path"].lower().endswith(".yml")]
    for number, item in enumerate(candidates):
        checkpoint("checking names and descriptions", number, len(candidates))
        raw = sources.raw(item["owner"], item["path"])
        if len(raw) > 8_000_000:
            locale_gaps.append({"owner": item["owner"], "path": item["path"], "reason": "file_size_limit"})
            continue
        parsed = parse_localization(raw, item["path"])
        locale_files += 1
        if parsed["diagnostics"]:
            locale_gaps.append({"owner": item["owner"], "path": item["path"],
                                "diagnostics": parsed["diagnostics"]})
        for ordinal, entry in enumerate(parsed["entries"]):
            locale_entries += 1
            start, end = entry["span"]
            value = entry.get("raw_value", "")
            locale[entry["language"], entry["key"]].append({"owner": item["owner"], "path": item["path"],
                "sha256": item["sha256"], "span": [start, end], "ordinal": ordinal,
                "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "tier": "replace" if "replace" in item["path"].split("/") else "ordinary"})
    for (language, key), occurrences in locale.items():
        if len(occurrences) > 1:
            add("localization_overlap", f"game/localization/{language}:{key}", occurrences,
                relation(occurrences, "value_sha256"),
                internal=len({item["owner"] for item in occurrences}) == 1, language=language)
    issues.sort(key=lambda item: (item["comparison"] != "different", item["internal"],
                                 item["metadata_only"], item["area"], item["target"]))
    unavailable = [{"owner": item["owner"], "name": item.get("name") or "An unavailable mod",
                    "reason": item.get("reason", "Its files are not available.")}
                   for item in (discovery or {}).get("mods", []) if item["enabled"] and not item["available"]]
    return {"id": "index_" + digest(canonical([scan["id"], INDEX_VERSION]))[:24],
        "workspace_id": scan["workspace_id"], "scan_id": scan["id"], "game_id": "ck3",
        "target_platform": scan["target_platform"], "version": INDEX_VERSION,
        "manifest_hash": scan["manifest_hash"], "profile_hash": scan["profile_hash"],
        "schema_hash": scan["schema_hash"], "parser_version": scan["parser_version"],
        "issues": issues, "unavailable_mods": unavailable,
        "summary": {"all_groups": len(issues), "differing_cross_mod_groups": sum(
            item["comparison"] == "different" and not item["metadata_only"] and not item["internal"] for item in issues),
            "differing_internal_groups": sum(item["internal"] and item["comparison"] == "different" for item in issues),
            "unavailable_mods": len(unavailable)},
        "coverage": {"source_inventory_complete": scan["analysis"]["coverage"].get("source_inventory_complete", True),
            "mod_localization_files": locale_files, "mod_localization_entries": locale_entries,
            "localization_gaps": locale_gaps, "advisory_counts": dict(diagnostics),
            "game_runs": 0, "note": "History, unknown file types and game behavior remain incompletely checked."}}


def query_index(index, *, query="", area=None, include_equal=False, include_internal=False,
                include_metadata=False, offset=0, limit=20):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid result page.")
    selected = [item for item in index["issues"] if
        (include_equal or item["comparison"] != "identical") and
        (include_internal or not item["internal"]) and (include_metadata or not item["metadata_only"]) and
        (not area or item["area"] == area) and (not query or query.casefold() in
            " ".join([item["target"], item["title"], *[mod["name"] for mod in item["mods"]]]).casefold())]
    return {"index_id": index["id"], "summary": index["summary"], "total": len(selected),
        "offset": offset, "next_offset": offset + limit if offset + limit < len(selected) else None,
        "issues": [{key: value for key, value in item.items() if key != "sources"}
                   for item in selected[offset:offset + limit]],
        "coverage": {key: value for key, value in index["coverage"].items() if key != "localization_gaps"}}
