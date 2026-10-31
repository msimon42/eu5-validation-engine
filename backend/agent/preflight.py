"""Bounded local source/version checks; candidates never change launcher truth."""
from __future__ import annotations

import fnmatch
from collections import defaultdict
import os
from pathlib import Path
import re
import time

from backend.app.store import Conflict, canonical, digest
from backend.engine.ck3_discovery import _fields
from backend.engine.safety import paths_overlap, read_source_bytes, reject_link_components

SEARCH_VERSION = "local-candidates-1"
MAX_DIRECTORIES = 10000
MAX_DESCRIPTOR_BYTES = 16 * 1024 * 1024
MAX_MATCHES = 10000
PREFERENCES = {"preserve_current", "open_to_change", "undecided"}


def version_relation(game_version, declarations):
    """Only explicit numeric patterns are comparable; no guessed release rules."""
    if not isinstance(game_version, str) or not re.fullmatch(r"\d+(?:\.\d+){1,3}", game_version):
        return "unknown"
    if not isinstance(declarations, list) or len(declarations) != 1:
        return "unknown"
    declared = declarations[0]
    if not isinstance(declared, str) or not re.fullmatch(r"\d+(?:\.\d+)*(?:\.\*)?", declared):
        return "unknown"
    target = game_version.split(".")
    expected = declared.split(".")
    if expected[-1] == "*":
        return "matches_declaration" if target[:len(expected) - 1] == expected[:-1] else "version_question"
    return "matches_declaration" if target == expected else "version_question"


def briefing_preflight(discovery):
    """Small metadata-only input for a context; excludes descriptor source bytes."""
    discovery = discovery or {}
    version = (discovery.get("installation") or {}).get("version_display")
    mods = []
    versions = []
    for mod in discovery.get("mods", []):
        if not mod.get("enabled"):
            continue
        descriptor = mod.get("descriptor") or {}
        mods.append({**{k: mod.get(k) for k in ("owner", "registry_path", "name", "available", "path", "reason", "position")},
                     "workshop_ids": descriptor.get("remote_file_id", []),
                     "archive": bool(descriptor.get("archive"))})
        declarations = descriptor.get("supported_version", [])
        versions.append({"owner": mod["owner"], "name": mod.get("name"), "declarations": declarations,
                         "descriptor_sha256": mod.get("descriptor_sha256"),
                         "relation": version_relation(version, declarations)})
    return {"versions": {"game_version": version, "mods": versions,
                         "meaning": "Declared version support, not a test of game compatibility."},
            "search_scope": discovery.get("known_search_roots", []), "mods": mods,
            "sources": discovery.get("sources", []),
            "scope": "launcher_selection", "version": SEARCH_VERSION}


def _preference_id(context):
    options = context.get("options") or {}
    identity = [context.get("game_id"), context.get("target_platform"),
                (context.get("playset") or {}).get("id"), options.get("user_data_path"),
                options.get("installation_path"), context.get("workspace_id") if context.get("manual") else None]
    return "version_preference_" + digest(canonical(identity))[:32]


def version_preference(store, context):
    try:
        return store.get("agent_preference", _preference_id(context))
    except KeyError:
        return {"preference": "undecided", "trust": "player_preference_not_approval_or_game_evidence"}


def candidate_search_summary(store, context, excluded_patterns=None):
    """Small saved status for resume; does not enumerate live directories."""
    import json
    with store.lock:
        store._check_database()
        rows = store.connection.execute(
            "SELECT json_extract(payload,'$.summary') FROM records WHERE kind='agent_candidate_search' "
            "AND json_extract(payload,'$.configuration_hash')=? "
            "AND json_extract(payload,'$.policy_hash')=? "
            "AND json_extract(payload,'$.search_scope_hash')=? "
            "AND json_extract(payload,'$.version')=? ORDER BY updated DESC LIMIT 1",
            (context.get("configuration_hash"), digest(canonical(excluded_patterns or [])),
             digest(canonical((context.get("preflight") or {}).get("search_scope", []))), SEARCH_VERSION)).fetchall()
    return json.loads(rows[0][0]) if rows and rows[0][0] else None


def _ids(values):
    return {value if isinstance(value, str) and value.isdecimal() else "invalid_identifier"
            for value in values}


class Preflight:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def set_version_preference(self, context_id, preference):
        if preference not in PREFERENCES:
            raise ValueError("Choose preserve_current, open_to_change, or undecided.")
        context = self.store.get("agent_context", context_id)
        return self.store.put("agent_preference", {"id": _preference_id(context),
            "workspace_id": context.get("workspace_id"), "preference": preference,
            "game_version_when_chosen": ((context.get("preflight") or {}).get("versions") or {}).get("game_version"),
            "trust": "player_preference_not_approval_or_game_evidence"})

    def _snapshot(self, context):
        preflight = context.get("preflight")
        if preflight and preflight.get("version") == SEARCH_VERSION:
            return preflight
        if preflight and preflight.get("version") not in (None, SEARCH_VERSION):
            raise Conflict("This preflight record uses an unsupported version. Refresh with matching tools.")
        # Older contexts lack bounded search metadata. Rediscover only known roots,
        # retaining the configuration precondition instead of inventing a scope.
        if context.get("manual"):
            return briefing_preflight({})
        self.service._guard_discovery_roots(context["options"])
        discovery = self.service._discover_selection(context["options"])
        if discovery.get("configuration_hash") != context.get("configuration_hash"):
            raise Conflict("The selected playset changed. Get fresh context before looking for missing mods.")
        return briefing_preflight(discovery)

    def _assert_policy(self, patterns):
        if self.service.inference_policy()["excluded_patterns"] != patterns:
            raise Conflict("The source policy changed during this request. Refresh before inspecting results.")

    def _receipt_id(self, context, patterns=None):
        if (context.get("preflight") or {}).get("version") not in (None, SEARCH_VERSION):
            raise Conflict("This preflight record uses an unsupported version. Refresh with matching tools.")
        if patterns is None:
            patterns = self.service.inference_policy()["excluded_patterns"]
        return "candidate_search_" + digest(canonical([SEARCH_VERSION, context["id"],
            context.get("configuration_hash"), patterns]))[:32]

    def find_missing_mod_candidates(self, context_id, offset=0, limit=20):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Choose a page of at most 50 missing mods.")
        context = self.store.get("agent_context", context_id)
        patterns = list(self.service.inference_policy()["excluded_patterns"])
        identifier = self._receipt_id(context, patterns)
        try:
            receipt = self.store.get("agent_candidate_search", identifier)
            if receipt.get("version") != SEARCH_VERSION:
                raise Conflict("This candidate search uses an unsupported version. Refresh with matching tools.")
            reused = True
        except KeyError:
            receipt = self._search(context, identifier, patterns)
            reused = False
        self._assert_policy(patterns)
        if receipt.get("policy_hash") != digest(canonical(patterns)):
            raise Conflict("The saved candidate search belongs to a different source policy. Refresh before continuing.")
        rows = receipt["mods"]
        return {"context_id": context_id, "search_id": receipt["id"], "checked_at": receipt["checked_at"],
            "reused": reused, "mods": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "coverage": receipt["coverage"], "scope": "candidates_only_launcher_unchanged",
            "next_step": "Ask which candidate the player wants inspected before using inspect_mod_candidate."}

    def _search(self, context, identifier, patterns):
        snapshot = self._snapshot(context)
        missing = [mod for mod in snapshot["mods"] if not mod.get("available")]
        gaps, searched, candidates = [], [], []
        seen, descriptor_bytes, directories, entries_examined = set(), 0, 0, 0
        for root in snapshot["search_scope"] if missing else []:
            path = Path(root["path"])
            try:
                self.service._guard_discovery_roots({"root_overrides": {"candidate": str(path)}})
                reject_link_components(path)
                if not path.exists():
                    searched.append({**root, "status": "absent"})
                    continue
                if root["kind"] == "explicit_payload":
                    children = [path]
                else:
                    # A single level only. Stop reading directory entries at the
                    # global bound instead of allocating an unbounded sorted list.
                    children = []
                    with os.scandir(path) as entries:
                        for entry in entries:
                            entries_examined += 1
                            if entries_examined > MAX_DIRECTORIES:
                                gaps.append({"reason": "directory_budget", "root": str(path)})
                                break
                            if entry.is_symlink():
                                gaps.append({"reason": "link_not_searched", "root": entry.path})
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                children.append(Path(entry.path))
                    children.sort(key=lambda p: p.name)
                searched.append({**root, "status": "searched"})
                for child in children:
                    directories += 1
                    if directories > MAX_DIRECTORIES:
                        gaps.append({"reason": "directory_budget", "root": str(path)})
                        break
                    if str(child) in seen:
                        continue
                    seen.add(str(child))
                    try:
                        reject_link_components(child)
                        descriptor = child / "descriptor.mod"
                        if not descriptor.exists():
                            gaps.append({"reason": "payload_descriptor_missing", "root": str(child)})
                            continue
                        if any(fnmatch.fnmatchcase("descriptor.mod", pattern) or
                               fnmatch.fnmatchcase(str(descriptor), pattern) for pattern in patterns):
                            gaps.append({"reason": "source_excluded", "root": str(child)})
                            continue
                        if descriptor_bytes >= MAX_DESCRIPTOR_BYTES:
                            gaps.append({"reason": "descriptor_byte_budget", "root": str(path)})
                            break
                        remaining = MAX_DESCRIPTOR_BYTES - descriptor_bytes
                        if descriptor.stat().st_size > remaining:
                            gaps.append({"reason": "descriptor_byte_budget", "root": str(path)})
                            continue
                        raw = read_source_bytes(child, "descriptor.mod", max_bytes=min(1024 * 1024, remaining))
                        descriptor_bytes += len(raw)
                        if descriptor_bytes > MAX_DESCRIPTOR_BYTES:
                            gaps.append({"reason": "descriptor_byte_budget", "root": str(path)})
                            break
                        fields, diagnostics = _fields(raw)
                        if diagnostics:
                            gaps.append({"reason": "malformed_descriptor", "root": str(child)})
                            continue
                        ids = fields.get("remote_file_id", [])
                        folder_id = child.name if root["kind"] == "workshop" and child.name.isdecimal() else None
                        name = (fields.get("name") or [None])[-1]
                        candidates.append({"path": str(child), "descriptor_sha256": digest(raw),
                            "workshop_ids": ids, "folder_workshop_id": folder_id,
                            "supported_versions": fields.get("supported_version", []),
                            "name": name if isinstance(name, str) else None, "archive": bool(fields.get("archive")),
                            "directory_identity": [child.stat().st_dev, child.stat().st_ino]})
                    except (OSError, ValueError) as exc:
                        gaps.append({"reason": "candidate_unreadable", "root": str(child), "detail": str(exc)})
            except (OSError, ValueError) as exc:
                gaps.append({"reason": "location_unreadable", "root": str(path), "detail": str(exc)})
        rows, matches_written = [], 0
        by_id, by_name = defaultdict(set), defaultdict(set)
        for number, candidate in enumerate(candidates):
            for workshop_id in _ids(candidate["workshop_ids"]):
                by_id[workshop_id].add(number)
            if candidate["folder_workshop_id"]:
                by_id[candidate["folder_workshop_id"]].add(number)
            if candidate["name"]:
                by_name[candidate["name"]].add(number)
        for mod in missing:
            match = re.fullmatch(r"mod/ugc_(\d+)\.mod", mod.get("registry_path") or "")
            expected = _ids(mod.get("workshop_ids") or [])
            if match:
                expected.add(match.group(1))
            matches = []
            numbers = set()
            for workshop_id in expected:
                numbers.update(by_id.get(workshop_id, set()))
            if isinstance(mod.get("name"), str):
                numbers.update(by_name.get(mod["name"], set()))
            for number in sorted(numbers):
                if matches_written >= MAX_MATCHES:
                    gaps.append({"reason": "candidate_result_budget", "owner": mod["owner"]})
                    break
                candidate = candidates[number]
                observed = _ids(candidate["workshop_ids"])
                if candidate["folder_workshop_id"]:
                    observed.add(candidate["folder_workshop_id"])
                same_name = bool(mod.get("name") and mod["name"] == candidate["name"])
                if not (expected & observed or same_name):
                    continue
                matching = len(expected) == len(observed) == 1 and expected == observed and "invalid_identifier" not in expected
                relation = "matching_workshop_identity" if matching else (
                    "conflicting_identity" if expected and observed else "name_only_suggestion")
                candidate_id = "mod_candidate_" + digest(canonical([identifier, mod["owner"], candidate]))[:32]
                saved = {**candidate, "id": candidate_id, "context_id": context["id"], "search_id": identifier,
                         "owner": mod["owner"], "registry_path": mod["registry_path"], "match": relation,
                         "inspectable": matching and not candidate["archive"],
                         "workspace_id": context.get("workspace_id")}
                self.store.put("agent_mod_candidate", saved)
                matches_written += 1
                matches.append({k: saved[k] for k in ("id", "path", "name", "match", "inspectable", "archive")})
            rows.append({"owner": mod["owner"], "name": mod.get("name"), "available_at_registered_location": False,
                         "state": "candidates_found" if matches else "search_incomplete" if gaps else "no_candidate_found",
                         "candidates": matches, "registration_reason": mod.get("reason"),
                         "ambiguous": len([m for m in matches if m["inspectable"]]) > 1})
        self._assert_policy(patterns)
        checked_at = time.time()
        return self.store.put("agent_candidate_search", {"id": identifier, "context_id": context["id"],
            "configuration_hash": context.get("configuration_hash"), "policy_hash": digest(canonical(patterns)),
            "search_scope_hash": digest(canonical(snapshot["search_scope"])),
            "workspace_id": context.get("workspace_id"), "checked_at": checked_at, "mods": rows,
            "summary": {"search_id": identifier, "checked_at": checked_at, "missing_mods": len(rows),
                "mods_with_candidates": sum(bool(row["candidates"]) for row in rows), "complete": not gaps,
                "scope": "saved_candidate_search_not_a_fresh_file_check"},
            "version": SEARCH_VERSION, "coverage": {"complete": not gaps, "searched_locations": searched,
                "gaps": gaps, "directories_examined": directories, "descriptor_bytes": descriptor_bytes,
                "directory_entries_examined": entries_examined,
                "recursive": False, "directory_limit": MAX_DIRECTORIES, "descriptor_byte_limit": MAX_DESCRIPTOR_BYTES}})

    def inspect_mod_candidate(self, context_id, candidate_id):
        """User-selected read-only alternative; never replace the primary selection."""
        from .context import AssistantContext
        context = self.store.get("agent_context", context_id)
        patterns = list(self.service.inference_policy()["excluded_patterns"])
        candidate = self.store.get("agent_mod_candidate", candidate_id)
        if candidate.get("context_id") != context_id or candidate.get("search_id") != self._receipt_id(context, patterns):
            raise Conflict("This candidate belongs to another selection or source policy. Search again.")
        if not candidate.get("inspectable"):
            raise ValueError("This folder does not have an unambiguous supported Workshop identity.")
        snapshot = self._snapshot(context)
        path = reject_link_components(Path(candidate["path"]))
        info = path.stat()
        raw = read_source_bytes(path, "descriptor.mod", max_bytes=1024 * 1024)
        if [info.st_dev, info.st_ino] != candidate["directory_identity"] or digest(raw) != candidate["descriptor_sha256"]:
            raise Conflict("The candidate changed. Search again before inspecting it.")
        if not context.get("manual"):
            current = self.service._discover_selection(context["options"])
            if current.get("configuration_hash") != context.get("configuration_hash"):
                raise Conflict("The launcher selection changed. Get fresh context before inspecting the candidate.")
        sources = [item for item in snapshot["sources"] if item["owner"] != candidate["owner"]]
        sources.append({"owner": candidate["owner"], "path": str(path)})
        roots = []
        for source in sources:
            root = reject_link_components(Path(source["path"]))
            if any(paths_overlap(root, previous) for previous in roots):
                raise ValueError("The selected candidate overlaps another source folder; choose separate roots.")
            roots.append(root)
        self._assert_policy(patterns)
        workspace = self.service.create_workspace({"game_id": "ck3", "target_platform": context["target_platform"],
            "mode": "game", "name": ("Alternative inspection: " + str(candidate["name"] or "found mod"))[:120],
            "sources": sources})
        present = {item["owner"] for item in sources}
        alternative = {"kind": "alternative_candidate", "parent_context_id": context_id,
                       "parent_workspace_id": context.get("workspace_id"), "candidate_id": candidate_id,
                       "meaning": "Includes a player-selected found copy; not the launcher-selected files."}
        remaining_missing = [{"owner": mod["owner"], "name": mod.get("name"), "reason": mod.get("reason")}
                             for mod in snapshot["mods"] if mod["owner"] not in present]
        alternative_preflight = {**snapshot, "scope": "alternative_candidate", "sources": sources,
            "mods": [{**mod, "available": True, "path": str(path), "reason": None}
                     if mod["owner"] == candidate["owner"] else mod for mod in snapshot["mods"]]}
        alternative_preflight["versions"] = {**snapshot["versions"], "mods": [
            {**mod, "name": candidate["name"], "declarations": candidate["supported_versions"],
             "descriptor_sha256": candidate["descriptor_sha256"],
             "relation": version_relation(snapshot["versions"]["game_version"], candidate["supported_versions"]),
             "origin": "player_selected_alternative"}
            if mod["owner"] == candidate["owner"] else mod for mod in snapshot["versions"]["mods"]]}
        workspace = self.store.put("workspace", {**workspace, "inspection_scope": alternative,
            "inspection_missing_mods": remaining_missing,
            "inspection_preflight": alternative_preflight,
            "default_playset": [mod["owner"] for mod in snapshot["mods"] if mod["owner"] in present],
            "discovery_complete": False, "ck3_selection": {"installation": context.get("installation")}})
        flow = AssistantContext(self.service)
        selected = flow.get(selection="resume", workspace_id=workspace["id"])
        selected = self.store.put("agent_context", {**self.store.get("agent_context", selected["id"]),
            "inspection_scope": alternative, "preflight": alternative_preflight,
            "source_status": {**selected["source_status"], "complete": False,
                "available_enabled_mods": len(present - {"V"}),
                "missing_enabled_mods": remaining_missing}})
        # Policy changes use this coordinator lock too: the final check and job
        # submission share one boundary even after the slower source reads.
        with self.service.command_lock:
            self._assert_policy(patterns)
            job = flow.request_check(selected["id"], "Inspect the selected found copy as a separate alternative.")
        return {**job, "inspection_scope": alternative, "launcher_changed": False, "game_runs": 0}
