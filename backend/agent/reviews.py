"""Player-oriented, evidence-linked CK3 review accounting.

Concern grouping organizes observations; it does not establish game behavior.
Saved interpretations never become approval, conformance or repair authority.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import fnmatch

from backend.app.store import Conflict, canonical, digest
from .investigation import _guard_request

CONCERN_VERSION = "ck3-concerns-1"
REVIEW_VERSION = "ck3-concern-review-1"
MAX_CONCERN_ISSUES = 20
STATES = ("pending", "in_progress", "explained_from_files", "needs_user_choice", "needs_game_test",
          "blocked_by_missing_information")
UNRESOLVED_REASONS = {"missing_source", "unsupported_content", "excluded_content", "missing_documentation",
                      "unresolved_dependency", "unknown_game_behavior"}
TERMINAL = set(STATES) - {"pending", "in_progress"}
TOPICS = (
    "Marriage, romance, and family", "Wars, diplomacy, and allies", "Events and scheduled activities",
    "Characters, traits, and progression", "Culture, religion, and government",
    "Interface, clothing, and backgrounds", "Names, descriptions, and translations", "Other shared changes",
)
TRUST = "Agent explanations are interpretations, not approval, game observations or compatibility guarantees."


def summary_id(index_id):
    return "review_summary_" + digest(canonical([index_id, CONCERN_VERSION]))[:24]


def _topic(issue):
    target = issue.get("target", "").casefold()
    paths = " ".join(source.get("path", "").casefold() for source in issue.get("sources", []))
    text = target + " " + paths
    if issue.get("kind") == "localization_overlap":
        return TOPICS[6]
    if any(word in text for word in ("marriage", "marry", "romance", "courtship", "betroth", "pregnan", "childbirth", "seduc")):
        return TOPICS[0]
    if any(word in text for word in ("call_ally", "declare_war", "casus_belli", "diplomac", "common/alliances", "war.txt")):
        return TOPICS[1]
    if any(word in text for word in ("/events/", "common/on_actions", "/on_action/", "game/event/")) or target.startswith("events/"):
        return TOPICS[2]
    if any(word in text for word in ("common/traits", "common/lifestyles", "common/perks", "game/trait/", "history/characters")):
        return TOPICS[3]
    if any(word in text for word in ("common/culture", "common/religion", "common/government", "game/culture/", "game/religion/")):
        return TOPICS[4]
    if any(word in text for word in ("gfx/", "gui/", "common/event_backgrounds", "barbershop", "portrait", "clothing", "illustration")):
        return TOPICS[5]
    if "localization/" in text:
        return TOPICS[6]
    return TOPICS[7]


def _source_keys(issue):
    return {(source["owner"], source["path"]) for source in issue.get("sources", [])}


def build_concerns(index):
    """Deterministic partition of every issue, including equal/internal/metadata.

    A file overlap adopts a specific definition topic only when all definitions
    sharing its source files agree. Cross-topic relationships remain explicit.
    """
    issues = index.get("issues", [])
    specific = defaultdict(set)
    for issue in issues:
        if issue.get("kind") == "duplicate_definition":
            for key in _source_keys(issue):
                specific[key].add(_topic(issue))
    buckets = defaultdict(list)
    for issue in issues:
        topic = _topic(issue)
        if issue.get("kind") == "overlapping_path":
            related_topics = set().union(*(specific[key] for key in _source_keys(issue)))
            if len(related_topics) == 1:
                topic = next(iter(related_topics))
        owners = tuple(sorted(mod["owner"] for mod in issue.get("mods", [])))
        buckets[topic, owners].append(issue)
    concerns = []
    source_concerns = defaultdict(set)
    for (topic, owners), members in sorted(buckets.items()):
        members.sort(key=lambda issue: (issue.get("target", ""), issue["id"]))
        for offset in range(0, len(members), MAX_CONCERN_ISSUES):
            selected = members[offset:offset + MAX_CONCERN_ISSUES]
            issue_ids = [issue["id"] for issue in selected]
            identifier = "concern_" + digest(canonical([index["id"], CONCERN_VERSION, topic, owners, issue_ids]))[:24]
            identical = all(issue.get("comparison") == "identical" for issue in selected)
            metadata_only = all(issue.get("metadata_only") for issue in selected)
            priority = (5 if identical or metadata_only else 4 if topic == TOPICS[6] else
                        3 if topic == TOPICS[5] else 2)
            mod_names = {mod["owner"]: mod.get("name", mod["owner"])
                         for issue in selected for mod in issue.get("mods", [])}
            concern = {"id": identifier, "version": CONCERN_VERSION, "topic": topic,
                "mods": [{"owner": owner, "name": mod_names[owner]} for owner in owners],
                "issue_ids": issue_ids, "raw_finding_count": len(selected), "priority": priority,
                "segment": offset // MAX_CONCERN_ISSUES + 1,
                "segments": (len(members) + MAX_CONCERN_ISSUES - 1) // MAX_CONCERN_ISSUES,
                "identical": identical, "metadata_only": metadata_only,
                "internal": all(issue.get("internal", False) for issue in selected),
                "languages": sorted({issue["language"] for issue in selected if issue.get("language")}),
                "observations": [{"issue_id": issue["id"], "comparison": issue.get("comparison", "unknown"),
                                  "statement": issue.get("what_is_known", "The shared content needs inspection.")}
                                 for issue in selected],
                "gameplay_effect": "unconfirmed"}
            concerns.append(concern)
            for issue in selected:
                for key in _source_keys(issue):
                    source_concerns[key].add(identifier)
    related = defaultdict(set)
    for identifiers in source_concerns.values():
        for identifier in identifiers:
            related[identifier].update(identifiers - {identifier})
    for concern in concerns:
        concern["related_concern_ids"] = sorted(related[concern["id"]])
    concerns.sort(key=lambda concern: (concern["priority"], concern["topic"],
                                       tuple(mod["owner"] for mod in concern["mods"]), concern["segment"]))
    return concerns


def _page(offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Choose a valid page of at most 100 concerns.")


def _text(value, field, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{field} must be {'nonempty ' if required else ''}text of at most {maximum} characters.")
    return value


def _covered(start, end, intervals):
    position = start
    for lower, upper in sorted(intervals):
        if lower > position:
            break
        position = max(position, upper)
        if position >= end:
            return True
    return False


class ReviewWorkflow:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def _view(self, workspace_id, index_id):
        from .investigation import _Snapshot
        return _Snapshot(self.service, workspace_id, index_id)

    def _policy_hash(self):
        return digest(canonical(self.service.inference_policy()["excluded_patterns"]))

    def _records(self, workspace_id):
        result, offset = [], 0
        while True:
            page = self.store.list("agent_concern_review", workspace_id, limit=1000, offset=offset)
            for record in page:
                if record.get("format") != REVIEW_VERSION:
                    raise Conflict("Saved concern reviews use an unsupported format. Update the connector before continuing.")
            result.extend(page)
            if len(page) < 1000:
                return result
            offset += len(page)

    @staticmethod
    def _identity(view):
        from .knowledge import knowledge_manifest
        return {**{key: view.index.get(key) for key in ("scan_id", "version", "manifest_hash", "profile_hash",
                                                       "schema_hash", "parser_version", "target_platform", "revision")},
                "knowledge_sha256": knowledge_manifest()["sha256"]}

    @staticmethod
    def _excluded(view, concern, by_issue=None):
        by_issue = by_issue if by_issue is not None else {issue["id"]: issue for issue in view.index["issues"]}
        paths = [source["path"] for identifier in concern["issue_ids"] for source in by_issue[identifier]["sources"]]
        return any(fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in view.patterns)

    def _rows(self, view):
        concerns = build_concerns(view.index)
        records = self._records(view.scan["workspace_id"])
        current = {record["concern_id"]: record for record in records if record.get("index_id") == view.index["id"]}
        policy_hash = digest(canonical(view.patterns))
        identity = self._identity(view)
        by_issue = {issue["id"]: issue for issue in view.index["issues"]}
        rows = []
        for concern in concerns:
            record = current.get(concern["id"])
            stale = bool(record and (record.get("identity") != identity or record.get("policy_hash") != policy_hash
                                     or record.get("concern_version") != CONCERN_VERSION))
            excluded = self._excluded(view, concern, by_issue)
            if excluded:
                # A previously saved explanation could quote newly excluded text.
                public = {key: concern[key] for key in ("id", "raw_finding_count", "priority", "segment", "segments")}
                public.update(topic="Content excluded from inspection", issue_ids=[], mods=[], observations=[],
                              excluded=True, related_concern_ids=[])
                review = {"state": "blocked_by_missing_information", "reviewer": "engine",
                    "explanation": "The source policy excludes content needed to inspect this concern.",
                    "unresolved_reason": "excluded_content", "uncertainties": ["The excluded content has not been reviewed."],
                    "next_step": "Keep this limitation visible; do not disclose excluded source contents.",
                    "evidence_refs": [], "stale": stale, "revision": record.get("revision", 0) if record else 0}
            else:
                public = copy.deepcopy(concern)
                if record and not stale:
                    review = {key: copy.deepcopy(record.get(key)) for key in (
                        "state", "explanation", "player_impact", "evidence_refs", "uncertainties", "next_step", "user_question",
                        "unresolved_reason", "engine_gaps", "reviewer", "revision", "created_at", "updated_at")}
                    review["stale"] = False
                elif concern["identical"]:
                    review = {"state": "explained_from_files", "reviewer": "engine", "stale": False,
                        "revision": record.get("revision", 0) if record else 0,
                        "explanation": "The compared content is identical. This does not establish game behavior or compatibility.",
                        "evidence_refs": [{"kind": "issue", "issue_id": identifier} for identifier in concern["issue_ids"]],
                        "uncertainties": ["Which contributions the game uses has not been tested."], "next_step": ""}
                else:
                    review = {"state": "pending", "reviewer": None, "stale": stale,
                        "revision": record.get("revision", 0) if record else 0,
                        "explanation": "", "evidence_refs": [], "uncertainties": [],
                        "next_step": "Inspect the evidence for this concern."}
            rows.append({**public, "review": review})
        historical = sum(record.get("index_id") != view.index["id"] or record.get("identity") != identity
                         or record.get("policy_hash") != policy_hash for record in records)
        return rows, historical

    def _summary(self, view, rows, historical):
        counts = {state: sum(row["review"]["state"] == state for row in rows) for state in STATES}
        raw_counts = {state: sum(row["raw_finding_count"] for row in rows if row["review"]["state"] == state)
                      for state in STATES}
        unfinished = next((row for row in rows if row["review"]["state"] not in TERMINAL), None)
        return {"id": summary_id(view.index["id"]), "workspace_id": view.scan["workspace_id"],
            "format": REVIEW_VERSION, "concern_version": CONCERN_VERSION, "index_id": view.index["id"],
            "scan_id": view.scan["id"], "policy_hash": digest(canonical(view.patterns)), "identity": self._identity(view),
            "total_concerns": len(rows), "raw_findings": len(view.index["issues"]),
            "counts": counts, "raw_finding_counts": raw_counts,
            "accounted_for": unfinished is None, "stale_historical_reviews": historical,
            "next_unfinished": ({"concern_id": unfinished["id"], "topic": unfinished["topic"],
                                 "state": unfinished["review"]["state"]} if unfinished else None),
            "gameplay_compatibility": "not_established", "game_runs": 0,
            "meaning": "Accounting covers detected concerns only; unresolved outcomes and coverage gaps remain."}

    def initialize(self, workspace_id, index_id):
        """Create/update the small summary used by context without loading scans."""
        view = self._view(workspace_id, index_id)
        rows, historical = self._rows(view)
        return self.store.put("agent_review_summary", self._summary(view, rows, historical))

    def context_summary(self, workspace_id, index_id):
        """Header-only resume context; a missing summary never triggers a scan."""
        from .context import headers
        from .knowledge import knowledge_manifest
        workspace = self.store.get("workspace", workspace_id)
        self.service._ck3_workspace(workspace)
        fields = ("workspace_id", "format", "concern_version", "index_id", "scan_id", "policy_hash", "identity",
                  "total_concerns", "raw_findings", "counts", "accounted_for", "next_unfinished",
                  "stale_historical_reviews", "gameplay_compatibility", "updated_at")
        records = headers(self.store, "agent_review_summary", fields, workspace_id=workspace_id,
                          identifier=summary_id(index_id), limit=1)
        if not records:
            return {"index_id": index_id, "state": "needs_report_refresh", "next_step": "Read the investigation report to initialize review accounting."}
        result = records[0]
        if result.get("format") != REVIEW_VERSION or result.get("concern_version") != CONCERN_VERSION:
            return {"index_id": index_id, "state": "needs_report_refresh", "next_step": "The review tools changed; refresh the saved investigation report."}
        identity = result.get("identity") or {}
        index_fields = tuple(key for key in identity if key != "knowledge_sha256")
        indexes = headers(self.store, "agent_index", index_fields, workspace_id=workspace_id,
                          identifier=index_id, limit=1)
        if (not indexes or any(indexes[0].get(key) != identity.get(key) for key in index_fields)
                or result.get("scan_id") != workspace.get("generation") or result.get("policy_hash") != self._policy_hash()
                or identity.get("knowledge_sha256") != knowledge_manifest()["sha256"]):
            return {"index_id": index_id, "state": "needs_report_refresh", "next_step": "The saved review context changed; refresh the report before continuing."}
        return {**result, "state": "ready", "trust": TRUST}

    @_guard_request
    def list_concerns(self, workspace_id, index_id, topic=None, state=None, priority=None, offset=0, limit=20):
        _page(offset, limit)
        if state is not None and state not in STATES:
            raise ValueError("Choose a supported concern review state.")
        if priority is not None and (type(priority) is not int or priority not in range(1, 6)):
            raise ValueError("Priority must be between one and five.")
        view = self._view(workspace_id, index_id)
        rows, historical = self._rows(view)
        selected = [row for row in rows if (topic is None or topic == row["topic"])
                    and (state is None or state == row["review"]["state"])
                    and (priority is None or priority == row["priority"])]
        return {**view.context(), "concern_version": CONCERN_VERSION, "total": len(selected),
            "offset": offset, "next_offset": offset + limit if offset + limit < len(selected) else None,
            "concerns": selected[offset:offset + limit], "summary": self._summary(view, rows, historical),
            "trust": TRUST}

    def _evidence(self, view, concern, references):
        if not isinstance(references, list) or len(references) > 4096 or len(canonical(references)) > 1024 * 1024:
            raise ValueError("Review references must be a bounded list of at most 4096 items and one MiB.")
        from .knowledge import read_knowledge
        normalized, cited_issues, intervals = [], set(), defaultdict(list)
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError("Each evidence reference must identify one issue, source span or knowledge entry.")
            possibilities = [kind for kind, key in (("issue", "issue_id"), ("source", "source_id"), ("knowledge", "entry_id"))
                             if key in reference]
            if len(possibilities) != 1 or reference.get("kind", possibilities[0]) != possibilities[0]:
                raise ValueError("An evidence reference must identify exactly one supported kind.")
            kind = possibilities[0]
            if kind == "issue":
                if set(reference) - {"kind", "issue_id"} or reference["issue_id"] not in concern["issue_ids"]:
                    raise ValueError("A cited finding does not belong to this concern.")
                cited_issues.add(reference["issue_id"])
            elif kind == "source":
                if set(reference) - {"kind", "source_id", "span", "sha256"}:
                    raise ValueError("A source citation has unsupported fields.")
                source = view.by_id.get(reference["source_id"])
                if not source or view.excluded(source):
                    raise ValueError("A cited source is absent or excluded from this inspection.")
                span = reference.get("span")
                if (reference.get("sha256") != source["sha256"] or not isinstance(span, list) or len(span) != 2
                        or any(type(value) is not int for value in span) or not 0 <= span[0] < span[1] <= source["size"]):
                    raise ValueError("A source citation requires its exact captured hash and valid byte span.")
                raw, reason = view.raw(source)
                if reason:
                    raise ValueError("The cited source cannot be verified: " + reason)
                intervals[source["owner"], source["path"]].append(span)
            else:
                if set(reference) - {"kind", "entry_id", "revision", "library_sha256"}:
                    raise ValueError("A knowledge citation has unsupported fields.")
                entry = read_knowledge(reference["entry_id"])
                if any(reference.get(key) != entry[key] for key in ("revision", "library_sha256")):
                    raise Conflict("The cited modding reference revision changed. Inspect it before saving the review.")
            normalized.append({**reference, "kind": kind})
        return normalized, cited_issues, intervals

    @staticmethod
    def _contribution_coverage(view, cited, intervals):
        """Check what was actually read before accepting a terminal disposition.

        An unread contribution is unfinished work, not a missing-documentation
        or runtime gap. Unsupported bytes and absent captured blobs are explicit
        engine-observed gaps and cannot masquerade as readable citations.
        """
        by_source = {(item["owner"], item["path"]): item for item in view.files if item["origin"] == "payload"}
        unread, gaps = [], []
        checked = {}
        for issue in view.index["issues"]:
            if issue["id"] not in cited or issue.get("comparison") == "identical":
                continue
            for source in issue["sources"]:
                key = source["owner"], source["path"]
                captured = by_source.get(key)
                if not captured:
                    raise Conflict("A concern contribution has no captured source identity.")
                if key not in checked:
                    _, reason = view.raw(captured)
                    checked[key] = reason
                reason = checked[key]
                if reason:
                    gaps.append({"issue_id": issue["id"], "source_id": captured["source_id"],
                        "reason": "missing_source" if "saved source copy is missing" in reason else "unsupported_content",
                        "detail": reason})
                    continue
                start, end = source.get("span") or [0, captured["size"]]
                if end > start and not _covered(start, end, intervals[key]):
                    unread.append({"issue_id": issue["id"], "source_id": captured["source_id"]})
        return unread, gaps

    def record_concern_review(self, workspace_id, index_id, concern_id, state, explanation="", player_impact="",
                              evidence_refs=None, uncertainties=None, next_step="", user_question=None,
                              expected_revision=0, unresolved_reason=None):
        if state not in STATES:
            raise ValueError("Choose a supported review state.")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Supply the last review revision, or zero for a new review.")
        terminal = state in TERMINAL
        _text(explanation, "Explanation", 6000, required=terminal)
        _text(player_impact, "Player impact", 2000)
        _text(next_step, "Next step", 1000, required=state in TERMINAL - {"explained_from_files"})
        if user_question is not None:
            _text(user_question, "User question", 1000, required=state == "needs_user_choice")
        elif state == "needs_user_choice":
            raise ValueError("A user-choice review requires the concrete question to ask.")
        uncertainties = [] if uncertainties is None else uncertainties
        if not isinstance(uncertainties, list) or len(uncertainties) > 50:
            raise ValueError("Provide at most 50 uncertainty statements.")
        for uncertainty in uncertainties:
            _text(uncertainty, "Uncertainty", 1000, required=True)
        if state in {"needs_game_test", "blocked_by_missing_information"} and not uncertainties:
            raise ValueError("An unresolved review requires the specific missing information.")
        if unresolved_reason is not None and unresolved_reason not in UNRESOLVED_REASONS:
            raise ValueError("Choose a supported unresolved reason; unfinished reading is still pending.")
        if state == "blocked_by_missing_information" and unresolved_reason is None:
            raise ValueError("A blocked review must identify the missing information or application limitation.")
        if state == "needs_game_test":
            unresolved_reason = "unknown_game_behavior"
        view = self._view(workspace_id, index_id)
        policy_hash = digest(canonical(view.patterns))
        concern = next((item for item in build_concerns(view.index) if item["id"] == concern_id), None)
        if concern is None:
            raise ValueError("That concern does not belong to the current inspection.")
        if self._excluded(view, concern):
            raise ValueError("This concern includes excluded content; its blocked disposition is reported automatically.")
        references, cited, intervals = self._evidence(view, concern, evidence_refs or [])
        if terminal and cited != set(concern["issue_ids"]):
            raise ValueError("Account for every finding in the concern before recording a completed review outcome.")
        gaps = []
        if terminal:
            unread, gaps = self._contribution_coverage(view, cited, intervals)
            if unread:
                raise ValueError("A completed review outcome needs citations covering every differing contribution that can be read; unfinished reading must remain pending or in progress.")
            if state == "blocked_by_missing_information":
                if unresolved_reason in {"missing_source", "unsupported_content"}:
                    if not any(gap["reason"] == unresolved_reason for gap in gaps):
                        raise ValueError("This blocked reason needs a matching engine-observed source gap in the concern.")
                elif unresolved_reason == "excluded_content":
                    raise ValueError("Excluded-content dispositions are produced automatically from the current source policy.")
                elif gaps:
                    raise ValueError("This concern has unreadable contributions; record the actual source gap before drawing further conclusions.")
            elif gaps:
                raise ValueError("This concern has unreadable contributions; record the actual source gap instead of a file explanation, user choice or game-test outcome.")
        identifier = "review_" + digest(canonical([workspace_id, index_id, concern_id, REVIEW_VERSION]))[:24]
        record = {"id": identifier, "format": REVIEW_VERSION, "workspace_id": workspace_id,
            "index_id": index_id, "scan_id": view.scan["id"], "concern_id": concern_id,
            "concern_version": CONCERN_VERSION, "identity": self._identity(view), "policy_hash": policy_hash,
            "state": state, "explanation": explanation, "player_impact": player_impact,
            "evidence_refs": references, "uncertainties": uncertainties, "next_step": next_step,
            "user_question": user_question, "unresolved_reason": unresolved_reason, "engine_gaps": gaps,
            "reviewer": "agent", "interpretation_basis": "agent_recorded_interpretation",
            "game_observations": [], "grants_repair_capability": False, "approval": False, "trust": TRUST}
        with self.store.atomic():
            from .context import headers
            current = self.store.get("workspace", workspace_id)
            current_indexes = headers(self.store, "agent_index", ("revision", "scan_id"),
                                      workspace_id=workspace_id, identifier=index_id, limit=1)
            if (current.get("generation") != view.scan["id"] or self._policy_hash() != policy_hash
                    or not current_indexes or current_indexes[0].get("revision") != view.index.get("revision")):
                raise Conflict("The inspection or source policy changed while saving the review. Refresh before continuing.")
            try:
                old = self.store.get("agent_concern_review", identifier)
            except KeyError:
                old = None
            if old and old.get("format") != REVIEW_VERSION:
                raise Conflict("This review has an unsupported version.")
            if old:
                history = {**old, "id": identifier + "_revision_" + str(old["revision"]),
                           "review_id": identifier, "review_revision": old["revision"]}
                self.store.put("agent_concern_review_history", history)
            saved = self.store.put("agent_concern_review", record, expected_revision=expected_revision)
            rows, historical = self._rows(view)
            summary = self.store.put("agent_review_summary", self._summary(view, rows, historical))
        return {**view.context(), "review": saved, "summary": summary, "trust": TRUST}

    @_guard_request
    def get_investigation_report(self, workspace_id, index_id, offset=0, limit=20, missing_offset=0):
        _page(offset, limit)
        _page(missing_offset, 20)
        view = self._view(workspace_id, index_id)
        rows, historical = self._rows(view)
        summary = self._summary(view, rows, historical)
        self.store.put("agent_review_summary", summary)
        sessions = self.store.list("agent_session", workspace_id, limit=1)
        session = sessions[0] if sessions else {}
        context = {}
        if session.get("context_id"):
            try:
                context = self.store.get("agent_context", session["context_id"])
            except KeyError:
                pass
        workspace = self.store.get("workspace", workspace_id)
        scope = workspace.get("inspection_scope") or {"kind": "selected_sources"}
        missing = view.index.get("unavailable_mods", [])
        if scope.get("kind") == "alternative_candidate":
            missing = workspace.get("inspection_missing_mods", missing)
        selected = rows[offset:offset + limit]
        pending = summary["counts"]["pending"] + summary["counts"]["in_progress"]
        unresolved = sum(summary["counts"][state] for state in
                         ("needs_user_choice", "needs_game_test", "blocked_by_missing_information"))
        narrative = (f"{len(rows) - pending} of {len(rows)} concern groups have been accounted for; "
                     f"{pending} remain unfinished and {unresolved} have unresolved questions. "
                     f"{len(missing)} enabled mods were unavailable in this capture. "
                     "This is a review of detected file concerns, not a gameplay compatibility test.")
        if scope.get("kind") == "alternative_candidate":
            narrative = "This inspection includes a player-selected alternative copy, not the launcher-selected files. " + narrative
        missing_next = missing_offset + 20 if missing_offset + 20 < len(missing) else None
        from backend.engine.ck3 import _base
        return {**view.context(), "summary": summary, "narrative": narrative,
            "inspection_scope": scope,
            "total": len(rows), "offset": offset,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "concerns": selected, "available_mod_count": sum(not _base(owner) for owner in view.scan.get("playset", [])),
            "missing_mod_count": len(missing), "missing_mods_total": len(missing),
            "missing_mods": missing[missing_offset:missing_offset + 20], "missing_mods_offset": missing_offset,
            "missing_mods_next_offset": missing_next, "missing_mods_scope": "saved_capture",
            "missing_mods_tool": "get_investigation_report",
            "missing_mods_continuation": ({"workspace_id": workspace_id, "index_id": index_id,
                                            "offset": offset, "limit": limit, "missing_offset": missing_next}
                                           if missing_next is not None else None),
            "coverage": {key: copy.deepcopy(value) for key, value in view.index.get("coverage", {}).items()
                         if key != "localization_gaps"},
            "localization_gap_count": len(view.index.get("coverage", {}).get("localization_gaps", [])),
            "last_file_check_at": session.get("last_checked_at"),
            "launcher_checked_at": context.get("source_status", {}).get("launcher_checked_at"),
            "legacy_notes": {"present": bool(session.get("notes") or session.get("reviewed_issue_ids")),
                             "counts_as_completed_review": False},
            "questions": [{"concern_id": row["id"], "question": row["review"].get("user_question")}
                          for row in selected if row["review"]["state"] == "needs_user_choice"],
            "trust": TRUST}
