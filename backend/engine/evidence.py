"""Immutable, artifact-backed evidence. Synthetic results never become C rules."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .safety import ManagedFS, sha256_bytes, validate_relative_path


STAGES = {"loading_screen", "main_menu", "in_game"}
LABELS = {"V", "D", "C", "I", "H", "P"}
EXPERIMENT_IDS = tuple(f"E{number:02d}" for number in range(1, 26))
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid immutable record identifier")
    return value


def validate_fingerprint(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("build fingerprint is required")
    for key in ("executable_sha256", "content_sha256", "docs_sha256", "dlc_sha256"):
        if not isinstance(value.get(key), str) or not _HASH.fullmatch(value[key]):
            raise ValueError(f"complete captured fingerprint required: {key}")
    return value


class EvidenceRegistry:
    def __init__(self, root: Path):
        self.fs = ManagedFS(root)
        self.root = self.fs.root

    def experiments(self) -> list[dict]:
        results = []
        for identifier in EXPERIMENT_IDS:
            records = []
            directory = self.root / "conformance"
            if directory.exists():
                for path in sorted(directory.glob("*.json")):
                    record = json.loads(self.fs.read_bytes(f"conformance/{path.name}"))
                    if record.get("experiment_id") == identifier:
                        records.append(record["id"])
            results.append({"id": identifier, "status": "proposed_not_run" if not records
                            else "passed_with_scope", "records": records,
                            "label": "P" if not records else "C"})
        return results

    def _immutable(self, category: str, identifier: str, value: dict) -> dict:
        identifier = _identifier(identifier)
        payload = copy.deepcopy(value)
        payload.pop("sha256", None)
        payload["sha256"] = sha256_bytes(canonical_bytes(payload))
        path = f"{category}/{identifier}.json"
        encoded = canonical_bytes(payload)
        try:
            self.fs.write_bytes(path, encoded, replace=False)
        except FileExistsError:
            if self.fs.read_bytes(path) != encoded:
                raise ValueError("immutable record already exists with different content")
        return payload

    def record_conformance(self, record: dict) -> dict:
        self.verify_conformance(record)
        return self._immutable("conformance", record["id"], record)

    def verify_conformance(self, record: dict) -> None:
        if not isinstance(record, dict):
            raise ValueError("conformance record must be an object")
        _identifier(record.get("id"))
        if record.get("experiment_id") not in EXPERIMENT_IDS:
            raise ValueError("unknown experiment identifier")
        if (record.get("tier") != "conformance" or record.get("platform") != "windows"
                or record.get("outcome") != "passed_with_scope"):
            raise ValueError("only executed Windows conformance can support a C rule")
        for key in ("executed", "cold_start", "active_state_confirmed"):
            if record.get(key) is not True:
                raise ValueError(f"missing trusted runtime prerequisite: {key}")
        if not record.get("direct_observation") or not record.get("negative_control"):
            raise ValueError("direct observation and discriminating negative control required")
        validate_fingerprint(record.get("build_fingerprint"))
        scope = record.get("scope", {})
        if scope.get("stage") not in STAGES or not scope.get("family") or "*" in str(scope):
            raise ValueError("conformance must have exact stage and family scope")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("archived conformance artifacts are required")
        paths = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ValueError("invalid conformance artifact")
            path = validate_relative_path(artifact.get("path"))
            if not path.startswith("artifacts/") or path in paths:
                raise ValueError("artifacts must be unique paths in the managed evidence tree")
            paths.add(path)
            if artifact.get("sha256") != sha256_bytes(self.fs.read_bytes(path)):
                raise ValueError("conformance artifact hash is missing or changed")
        if record.get("sha256"):
            payload = dict(record)
            expected = payload.pop("sha256")
            if expected != sha256_bytes(canonical_bytes(payload)):
                raise ValueError("conformance record hash changed")

    def get_conformance(self, identifier: str) -> dict:
        record = json.loads(self.fs.read_bytes(f"conformance/{_identifier(identifier)}.json"))
        self.verify_conformance(record)
        return record

    def register_profile(self, profile: dict) -> dict:
        self.validate_profile(profile)
        return self._immutable("profiles", profile["id"], profile)

    def validate_profile(self, profile: dict, *, require_conformed: bool = False) -> None:
        if not isinstance(profile, dict):
            raise ValueError("profile must be an object")
        identifier = _identifier(profile.get("id"))
        kind = profile.get("kind", profile.get("status"))
        if kind == "documentation_only":
            kind = "documented"
        if kind not in {"synthetic", "documented", "conformed"}:
            raise ValueError("unknown profile kind")
        if (self.root / "quarantine" / f"{identifier}.json").exists():
            raise ValueError("profile is quarantined")
        if require_conformed and kind != "conformed":
            raise ValueError("production needs a conformed profile")
        rules = profile.get("rules", [])
        if not isinstance(rules, list) or (kind == "conformed" and not rules):
            raise ValueError("conformed profile requires explicit rules")
        ids = set()
        if kind == "conformed":
            validate_fingerprint(profile.get("build_fingerprint"))
        for rule in rules:
            _identifier(rule.get("id"))
            if rule["id"] in ids:
                raise ValueError("duplicate rule identity")
            ids.add(rule["id"])
            label = rule.get("label", rule.get("evidence_label", "P"))
            if label not in LABELS or (kind != "conformed" and label == "C"):
                raise ValueError("synthetic/documentation profiles cannot manufacture C rules")
            selectors = rule.get("selectors", {})
            stages, families = selectors.get("stages", []), selectors.get("families", [])
            if not stages or not families or not set(stages) <= STAGES or "*" in str(selectors):
                raise ValueError("rule requires exact nonempty family/stage selectors")
            if not rule.get("version") or not rule.get("invalidation_keys"):
                raise ValueError("rule version and invalidation dependencies are required")
            if kind == "conformed":
                if label != "C" or not rule.get("evidence"):
                    raise ValueError("every production rule needs conformance evidence")
                covered = set()
                covered_fields = set()
                for reference in rule["evidence"]:
                    record = self.get_conformance(reference)
                    if record["build_fingerprint"] != profile["build_fingerprint"]:
                        raise ValueError("rule evidence belongs to a different target fingerprint")
                    covered.add((record["scope"]["stage"], record["scope"]["family"]))
                    fields = selectors.get("fields")
                    if fields and record["scope"].get("field") not in fields:
                        raise ValueError("field selector exceeds measured evidence")
                    if fields:
                        covered_fields.add((record["scope"]["stage"], record["scope"]["family"], record["scope"]["field"]))
                    elif record["scope"].get("field"):
                        raise ValueError("a field-scoped observation cannot authorize a whole-family reader")
                required = {(stage, family) for stage in stages for family in families}
                if not required <= covered:
                    raise ValueError("profile selector exceeds measured stage/family scope")
                required_fields = {(stage, family, field) for stage, family in required
                                   for field in selectors.get("fields", [])}
                if not required_fields <= covered_fields:
                    raise ValueError("profile field selector exceeds measured evidence")
        if profile.get("sha256"):
            payload = dict(profile)
            expected = payload.pop("sha256")
            if sha256_bytes(canonical_bytes(payload)) != expected:
                raise ValueError("profile content hash changed")

    def get_profile(self, identifier: str) -> dict:
        profile = json.loads(self.fs.read_bytes(f"profiles/{_identifier(identifier)}.json"))
        self.validate_profile(profile)
        return profile

    def quarantine(self, identifier: str, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("contradiction reason required")
        return self._immutable("quarantine", _identifier(identifier),
                               {"id": identifier, "status": "quarantined", "reason": reason})
