"""Inactive review bundles and guarded, journaled managed releases.

No playset persistence format is guessed here. A trusted local activation
observer must confirm in-game UI activation; this module never writes a playset.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from pathlib import Path
from typing import Callable

from .evidence import EvidenceRegistry, canonical_bytes
from .safety import ManagedFS, ManagedLock, check_path_collisions, sha256_bytes


REQUIRED_GATES = frozenset({"source_consistency", "syntax", "encoding_metadata", "paths",
                            "references_scope", "full_stack", "preservation", "write_set",
                            "runtime", "decisions", "conformance"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _manifest_view(candidate: dict) -> dict:
    """Export provenance and generated outputs, never a bundled source corpus."""
    excluded = {"bytes_base64", "_raw", "raw_bytes", "source_bytes", "source_text",
                "raw", "content", "text", "transcript", "messages", "api_key", "token", "secret"}
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key not in excluded}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    fields = ("id", "workspace_id", "mode", "inputs", "validation", "profile",
              "build_fingerprint", "decisions")
    result = {key: clean(candidate[key]) for key in fields if key in candidate}
    plan = candidate.get("plan", {})
    result["plan"] = {key: clean(plan[key]) for key in
                      ("read_set", "write_set", "obligations", "affected_scope",
                       "expected_results", "baseline_hashes", "known_unknowns", "rationale") if key in plan}
    return result


class InjectedCrash(RuntimeError):
    """Test-only process interruption at a durable boundary."""


class ReleaseManager:
    def __init__(self, root: Path, *, evidence_root: Path | None = None):
        self.fs = ManagedFS(root, max_bytes=128 * 1024 * 1024)
        self.root = self.fs.root
        self.evidence = EvidenceRegistry(evidence_root or self.root / "evidence")
        self.fs.write_bytes(".locks/owner", b"managed release coordination\n")

    def _lock(self):
        return ManagedLock(self.fs.resolve(".locks/promotion.lock"))

    def _read_json(self, path: str) -> dict:
        return json.loads(self.fs.read_bytes(path))

    def _write_json(self, path: str, value: dict) -> None:
        self.fs.write_bytes(path, canonical_bytes(value))

    def active(self) -> dict | None:
        if not (self.root / "active-release.json").exists():
            return None
        pointer = self._read_json("active-release.json")
        self._verify_release(pointer)
        return pointer

    def _verify_release(self, pointer: dict) -> dict:
        identifier = pointer.get("release_id", "")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise ValueError("invalid managed release pointer")
        payload = self.fs.read_bytes(f"releases/{identifier}/manifest.json")
        if sha256_bytes(payload) != pointer.get("manifest_sha256"):
            raise ValueError("managed release manifest was externally changed")
        manifest = json.loads(payload)
        for file in manifest["files"]:
            if sha256_bytes(self.fs.read_bytes(f"releases/{identifier}/files/{file['path']}")) != file["sha256"]:
                raise ValueError("managed release bytes were externally changed")
        return manifest

    @staticmethod
    def _files(candidate: dict) -> list[tuple[str, bytes]]:
        if not isinstance(candidate, dict) or not _ID.fullmatch(str(candidate.get("id", ""))):
            raise ValueError("candidate needs a bounded opaque identifier")
        plan = candidate.get("plan", {})
        records = plan.get("files")
        if not isinstance(records, list) or not records or len(records) > 4096 or any(not isinstance(item, dict) for item in records):
            raise ValueError("candidate requires a bounded nonempty file set")
        check_path_collisions([item.get("path") for item in records])
        files = []
        total = 0
        for item in records:
            try:
                data = base64.b64decode(item["bytes_base64"], validate=True)
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError("invalid exact file base64") from exc
            total += len(data)
            if len(data) > 32 * 1024 * 1024 or total > 128 * 1024 * 1024:
                raise ValueError("candidate file budget exceeded")
            files.append((item["path"].replace("\\", "/"), data))
        declared = plan.get("write_set")
        if isinstance(declared, list) and all(isinstance(item, dict) for item in declared):
            declared_paths = [item.get("path") for item in declared]
            hashes = {path: sha256_bytes(data) for path, data in files}
            if any(item.get("sha256") != hashes.get(item.get("path")) for item in declared):
                raise ValueError("write-set output hash differs from generated bytes")
        else:
            declared_paths = declared
        if (not isinstance(declared_paths, list) or any(not isinstance(path, str) for path in declared_paths) or
                len(declared_paths) != len(files) or set(declared_paths) != {path for path, _ in files}):
            raise ValueError("write set must equal the complete candidate file set")
        return files

    def export_bundle(self, candidate: dict) -> Path:
        files = self._files(candidate)
        digest = sha256_bytes(canonical_bytes(candidate))
        identifier = f"{candidate['id'][:96]}-{digest[:16]}"
        prefix = f"bundles/{identifier}"
        manifest = {"kind": "experimental_bundle", "activated": False,
                    "validation_label": "unvalidated", "candidate": _manifest_view(candidate),
                    "files": [{"path": path, "sha256": sha256_bytes(data)} for path, data in files]}
        with self._lock():
            for path, data in files:
                target = f"{prefix}/files/{path}"
                try:
                    self.fs.write_bytes(target, data, replace=False)
                except FileExistsError:
                    if self.fs.read_bytes(target) != data:
                        raise ValueError("existing bundle was externally changed")
            target = f"{prefix}/manifest.json"
            encoded = canonical_bytes(manifest)
            try:
                self.fs.write_bytes(target, encoded, replace=False)
            except FileExistsError:
                if self.fs.read_bytes(target) != encoded:
                    raise ValueError("existing bundle manifest differs")
        return self.fs.resolve(f"{prefix}/manifest.json").parent

    @staticmethod
    def _current(candidate: dict, current_inputs) -> dict:
        if not isinstance(candidate.get("inputs"), dict) or not candidate["inputs"]:
            raise ValueError("candidate needs captured source preconditions")
        actual = current_inputs() if callable(current_inputs) else current_inputs
        if actual is None or actual != candidate["inputs"]:
            raise ValueError("live inputs changed or fresh input verification is unavailable")
        return actual

    def _eligible(self, candidate: dict, current_inputs) -> tuple[list[tuple[str, bytes]], dict]:
        files = self._files(candidate)
        if candidate.get("mode") != "game":
            raise ValueError("synthetic workspaces cannot activate a real release")
        self._current(candidate, current_inputs)
        profile = candidate.get("profile")
        if isinstance(profile, str):
            profile = self.evidence.get_profile(profile)
        elif isinstance(profile, dict):
            registered = self.evidence.get_profile(profile.get("id", ""))
            if registered != profile:
                raise ValueError("candidate profile is not the immutable registered revision")
        else:
            raise ValueError("registered conformed profile required")
        self.evidence.validate_profile(profile, require_conformed=True)
        if candidate.get("build_fingerprint") != profile["build_fingerprint"]:
            raise ValueError("candidate target fingerprint differs from measured profile")
        scope = candidate.get("plan", {}).get("affected_scope")
        if not isinstance(scope, list) or not scope:
            raise ValueError("complete affected stage/family scope is required")
        for affected in scope:
            if not any(affected.get("stage") in rule["selectors"]["stages"] and
                       affected.get("family") in rule["selectors"]["families"] and
                       (not rule["selectors"].get("fields") or
                        set(affected.get("fields", [])) <= set(rule["selectors"]["fields"]))
                       for rule in profile["rules"]):
                raise ValueError("affected scope exceeds conformed capability")
        validation = candidate.get("validation", {})
        gates = validation.get("gates", [])
        if not isinstance(gates, list) or len({gate.get("id") for gate in gates}) != len(gates):
            raise ValueError("invalid or duplicate validation gates")
        outcomes = {gate.get("id"): gate for gate in gates}
        if not REQUIRED_GATES <= outcomes.keys():
            raise ValueError("required deterministic gate policy is incomplete")
        for identifier in REQUIRED_GATES:
            if outcomes[identifier].get("outcome") != "pass" or outcomes[identifier].get("required") is not True:
                raise ValueError(f"required gate blocks promotion: {identifier}")
        if any(gate.get("required") and gate.get("outcome") != "pass" for gate in gates):
            raise ValueError("required unknown, failed or not-run gate blocks promotion")
        input_hash = sha256_bytes(canonical_bytes(candidate["inputs"]))
        if (validation.get("inputs_sha256") != input_hash or
                validation.get("profile_sha256") != profile["sha256"]):
            raise ValueError("validation is stale or not bound to exact inputs/profile")
        obligations = candidate["plan"].get("obligations")
        if not isinstance(obligations, list) or not obligations:
            raise ValueError("complete preservation obligations are required")
        identifiers = [item.get("id") for item in obligations]
        if len(set(identifiers)) != len(identifiers) or None in identifiers:
            raise ValueError("obligation identities must be unique")
        if (set(validation.get("obligation_ids", [])) != set(identifiers) or
                validation.get("complete_obligation_closure") is not True):
            raise ValueError("validation omitted the complete affected obligation closure")
        decisions = {item.get("id"): item for item in candidate.get("decisions", [])}
        for item in obligations:
            status = item.get("status", item.get("state"))
            if status == "satisfied" and item.get("evidence_ids"):
                continue
            decision = decisions.get(item.get("decision_id"), {})
            if (status != "waived" or decision.get("inputs_sha256") != input_hash or
                    decision.get("profile_sha256") != profile["sha256"] or
                    item["id"] not in decision.get("waived_obligations", []) or
                    decision.get("approved_by") != "user"):
                raise ValueError("unknown or violated unwaived preservation obligation")
        return files, profile

    @staticmethod
    def _fault(fault_at: str | None, state: str) -> None:
        if fault_at == state:
            raise InjectedCrash(state)

    def promote(self, candidate: dict, current_inputs=None, *,
                verify_activation: Callable[[dict], dict] | None = None,
                fault_at: str | None = None) -> dict:
        if not callable(verify_activation):
            raise ValueError("a trusted direct active-playset observer is required; use an inactive bundle")
        with self._lock():
            files, profile = self._eligible(candidate, current_inputs)
            previous = self.active()
            previous_bytes = self.fs.read_bytes("active-release.json") if previous else None
            identifier = f"{candidate['id'][:96]}-{sha256_bytes(canonical_bytes(candidate))[:16]}"
            manifest = {"kind": "validated_managed_release", "release_id": identifier,
                        "candidate": _manifest_view(candidate), "profile_sha256": profile["sha256"],
                        "files": [{"path": path, "sha256": sha256_bytes(data)} for path, data in files],
                        "playset_mode": "manual", "application_playset_changes": []}
            for path, data in files:
                target = f"releases/{identifier}/files/{path}"
                try:
                    self.fs.write_bytes(target, data, replace=False)
                except FileExistsError:
                    if self.fs.read_bytes(target) != data:
                        raise ValueError("release generation was externally changed")
                self._fault(fault_at, "staging_write")
            manifest_bytes = canonical_bytes(manifest)
            target = f"releases/{identifier}/manifest.json"
            try:
                self.fs.write_bytes(target, manifest_bytes, replace=False)
            except FileExistsError:
                if self.fs.read_bytes(target) != manifest_bytes:
                    raise ValueError("release manifest was externally changed")
            pointer = {"release_id": identifier, "manifest_sha256": sha256_bytes(manifest_bytes)}
            journal = {"id": identifier, "state": "prepared", "new_pointer": pointer,
                       "previous_pointer": previous,
                       "previous_bytes_base64": base64.b64encode(previous_bytes).decode() if previous_bytes else None,
                       "playset_mode": "manual", "application_playset_changes": []}
            journal_path = f"journals/{identifier}.json"
            if (self.root / journal_path).exists():
                existing = self._read_json(journal_path)
                if existing.get("state") == "verified" and self.active() == pointer:
                    return existing
                raise ValueError("release has a prior promotion journal; recover before retry")
            self._write_json(journal_path, journal)
            try:
                for state in ("prepared", "validated", "promotion_started"):
                    journal["state"] = state
                    self._write_json(journal_path, journal)
                    self._fault(fault_at, state)
                self._current(candidate, current_inputs)
                self.fs.write_bytes("active-release.json", canonical_bytes(pointer))
                journal["state"] = "files_active"
                self._write_json(journal_path, journal)
                self._fault(fault_at, "files_active")
                observation = verify_activation(copy.deepcopy(manifest))
                if (not isinstance(observation, dict) or observation.get("confirmed") is not True or
                        not observation.get("direct_observation") or not observation.get("playset_hash")):
                    raise ValueError("actual active content and order were not directly confirmed")
                journal["activation_observation"] = observation
                journal["state"] = "playset_applied"
                self._write_json(journal_path, journal)
                self._fault(fault_at, "playset_applied")
                self._current(candidate, current_inputs)
                self._verify_release(pointer)
                journal["state"] = "verified"
                self._write_json(journal_path, journal)
                self._fault(fault_at, "verified")
                return journal
            except InjectedCrash:
                raise
            except Exception as exc:
                journal["error"] = str(exc)
                self._restore(journal)
                self._write_json(journal_path, journal)
                raise ValueError(f"promotion refused; {journal['state']}: {exc}") from exc

    def _restore(self, journal: dict) -> None:
        try:
            current = self.active()
            if current not in (journal["new_pointer"], journal["previous_pointer"]):
                raise ValueError("active pointer changed externally")
            previous = journal["previous_pointer"]
            if previous:
                self._verify_release(previous)
            if current == journal["new_pointer"]:
                if journal["previous_bytes_base64"]:
                    self.fs.write_bytes("active-release.json", base64.b64decode(journal["previous_bytes_base64"], validate=True))
                else:
                    self.fs.unlink("active-release.json")
            journal["state"] = "rolled_back"
        except (ValueError, OSError, KeyError) as exc:
            journal["state"] = "recovery_required"
            journal["recovery_reason"] = str(exc)

    def rollback(self, release_id: str, *, preview: bool = False) -> dict:
        if not isinstance(release_id, str) or not _ID.fullmatch(release_id):
            raise ValueError("invalid release identifier")
        with self._lock():
            journal_path = f"journals/{release_id}.json"
            journal = self._read_json(journal_path)
            if journal["state"] == "rolled_back":
                return journal
            if self.active() != journal["new_pointer"]:
                raise ValueError("intervening active state prevents rollback")
            if preview:
                return {"release_id": release_id, "previous_pointer": journal["previous_pointer"],
                        "playset_changes": [], "managed_only": True}
            self._restore(journal)
            self._write_json(journal_path, journal)
            if journal["state"] != "rolled_back":
                raise ValueError(journal["recovery_reason"])
            return journal

    def recover(self) -> list[dict]:
        recovered = []
        with self._lock():
            directory = self.root / "journals"
            if not directory.exists():
                return recovered
            for path in sorted(directory.glob("*.json")):
                journal = self._read_json(f"journals/{path.name}")
                if journal.get("state") in {"verified", "rolled_back"}:
                    continue
                self._restore(journal)
                self._write_json(f"journals/{path.name}", journal)
                recovered.append(journal)
        return recovered
