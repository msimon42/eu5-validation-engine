import copy

import pytest

from backend.engine.evidence import EvidenceRegistry
from backend.engine.safety import sha256_bytes


def fingerprint():
    return {key: char * 64 for key, char in (("executable_sha256", "a"), ("content_sha256", "b"),
                                           ("docs_sha256", "c"), ("dlc_sha256", "d"))}


def recorded_profile(registry):
    raw = b'{"observed":31,"control":47}'
    registry.fs.write_bytes("artifacts/probe/observation.json", raw)
    record = {"id": "probe-1", "experiment_id": "E01", "tier": "conformance", "platform": "windows",
              "outcome": "passed_with_scope", "executed": True, "cold_start": True,
              "active_state_confirmed": True, "direct_observation": {"value": 31},
              "negative_control": {"value": 47}, "build_fingerprint": fingerprint(),
              "scope": {"stage": "in_game", "family": "measured_test_family"},
              "artifacts": [{"path": "artifacts/probe/observation.json", "sha256": sha256_bytes(raw)}]}
    registry.record_conformance(record)
    profile = {"id": "measured-test-profile", "kind": "conformed", "build_fingerprint": fingerprint(),
               "rules": [{"id": "measured-rule", "version": "1", "label": "C",
                          "selectors": {"stages": ["in_game"], "families": ["measured_test_family"]},
                          "invalidation_keys": ["executable_sha256", "content_sha256"], "evidence": ["probe-1"]}]}
    return registry.register_profile(profile)


def test_initial_experiments_are_proposed_without_conformance(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    assert [row["id"] for row in registry.experiments()] == [f"E{i:02d}" for i in range(1, 26)]
    assert all(row["status"] == "proposed_not_run" and row["label"] == "P" for row in registry.experiments())


def test_profile_is_immutable_and_artifact_updates_invalidate(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    profile = recorded_profile(registry)
    assert registry.get_profile(profile["id"]) == profile
    assert registry.register_profile(profile) == profile
    changed = copy.deepcopy(profile)
    changed.pop("sha256")
    changed["rules"][0]["version"] = "2"
    with pytest.raises(ValueError, match="immutable"):
        registry.register_profile(changed)
    registry.fs.write_bytes("artifacts/probe/observation.json", b"tampered")
    with pytest.raises(ValueError, match="artifact hash"):
        registry.get_profile(profile["id"])


def test_synthetic_documented_and_broadened_rules_cannot_claim_C(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    profile = recorded_profile(registry)
    for kind in ("synthetic", "documented", "documentation_only"):
        invalid = copy.deepcopy(profile)
        invalid.pop("sha256")
        invalid["kind"] = kind
        with pytest.raises(ValueError, match="manufacture"):
            registry.validate_profile(invalid)
    invalid = copy.deepcopy(profile)
    invalid.pop("sha256")
    invalid["rules"][0]["selectors"]["families"].append("unmeasured_family")
    with pytest.raises(ValueError, match="exceeds measured"):
        registry.validate_profile(invalid)
    registry.quarantine(profile["id"], "contradictory observation")
    with pytest.raises(ValueError, match="quarantined"):
        registry.get_profile(profile["id"])


@pytest.mark.parametrize("field,value", [("executed", False), ("platform", "macos"),
                                         ("tier", "contract"), ("direct_observation", None),
                                         ("negative_control", None), ("active_state_confirmed", False)])
def test_incomplete_and_synthetic_runtime_records_rejected(tmp_path, field, value):
    registry = EvidenceRegistry(tmp_path)
    recorded_profile(registry)
    record = registry.get_conformance("probe-1")
    record.pop("sha256")
    record[field] = value
    with pytest.raises(ValueError):
        registry.record_conformance(record)
