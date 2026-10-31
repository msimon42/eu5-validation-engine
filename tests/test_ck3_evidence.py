"""Synthetic registry contracts only: these tests never establish game evidence."""
import copy

import pytest

from backend.engine.evidence import CK3_EXPERIMENT_IDS, EvidenceRegistry
from backend.engine.safety import sha256_bytes


def fixture_record(registry, *, game_id="ck3", platform="macos", identifier="fixture-probe"):
    raw = b"synthetic archived observation fixture; no game was run"
    registry.fs.write_bytes("artifacts/fixture/control.txt", raw)
    return {"id": identifier, "game_id": game_id,
            "experiment_id": "CK3-FILES-01" if game_id == "ck3" else "E01", "platform": platform,
            "tier": "conformance", "outcome": "passed_with_scope", "executed": True,
            "cold_start": True, "active_state_confirmed": True,
            "direct_observation": {"synthetic_fixture": 31}, "negative_control": {"synthetic_fixture": 47},
            "build_fingerprint": {key: char * 64 for key, char in (
                ("executable_sha256", "a"), ("content_sha256", "b"), ("docs_sha256", "c"), ("dlc_sha256", "d"))},
            "scope": {"stage": "game" if game_id == "ck3" else "in_game", "family": "fixture_family"},
            "artifacts": [{"path": "artifacts/fixture/control.txt", "sha256": sha256_bytes(raw)}]}


def fixture_profile(record, *, game_id="ck3", platform="macos"):
    return {"id": "fixture-profile", "game_id": game_id, "target_platform": platform, "kind": "conformed",
            "build_fingerprint": record["build_fingerprint"], "rules": [{
                "id": "fixture-rule", "version": "1", "label": "C", "evidence": [record["id"]],
                "selectors": {"stages": ["game" if game_id == "ck3" else "in_game"],
                              "families": ["fixture_family"]},
                "invalidation_keys": ["game_id", "target_platform", "executable_sha256"]}]}


def test_ck3_catalog_has_no_shipped_conformance(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    rows = registry.experiments(game_id="ck3")
    assert tuple(row["id"] for row in rows) == CK3_EXPERIMENT_IDS
    assert all(row["status"] == "proposed_not_run" and row["label"] == "P" for row in rows)
    assert all(row["game_id"] == "ck3" for row in rows)
    assert all(row["id"].startswith("E") for row in registry.experiments())


@pytest.mark.parametrize("platform", ["macos", "windows"])
def test_ck3_registry_accepts_only_matching_scoped_artifacts(tmp_path, platform):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry, platform=platform)
    registry.record_conformance(record)
    profile = registry.register_profile(fixture_profile(record, platform=platform))
    assert registry.get_profile(profile["id"]) == profile
    rows = registry.experiments(game_id="ck3", platform=platform)
    assert next(row for row in rows if row["id"] == "CK3-FILES-01")["records"] == [record["id"]]
    other = "windows" if platform == "macos" else "macos"
    assert all(not row["records"] for row in registry.experiments(game_id="ck3", platform=other))
    assert all(not row["records"] for row in registry.experiments())


def test_cross_game_and_platform_evidence_cannot_authorize_profile(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry)
    registry.record_conformance(record)
    for game_id, platform, message in [("eu5", "windows", "different game"),
                                       ("ck3", "windows", "different target platform")]:
        with pytest.raises(ValueError, match=message):
            registry.register_profile(fixture_profile(record, game_id=game_id, platform=platform))
    missing = fixture_profile(record)
    missing.pop("target_platform")
    with pytest.raises(ValueError, match="explicit target platform"):
        registry.register_profile(missing)


def test_legacy_eu5_windows_records_and_profiles_remain_valid(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry, game_id="eu5", platform="windows")
    record.pop("game_id")
    registry.record_conformance(record)
    profile = fixture_profile(record, game_id="eu5", platform="windows")
    profile.pop("game_id")
    profile.pop("target_platform")
    registry.register_profile(profile)
    with pytest.raises(ValueError, match="different game"):
        registry.register_profile(fixture_profile(record))


@pytest.mark.parametrize("change,value", [("platform", "linux"), ("platform", None), ("executed", False),
                                         ("tier", "contract"), ("cold_start", False),
                                         ("direct_observation", None), ("negative_control", None)])
def test_ck3_keeps_runtime_and_preservation_prerequisites(tmp_path, change, value):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry)
    record[change] = value
    with pytest.raises(ValueError):
        registry.record_conformance(record)


def test_game_experiment_stage_and_immutable_target_cannot_be_rebound(tmp_path):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry)
    for field, value in [("game_id", "eu5"), ("experiment_id", "E01"),
                         ("scope", {"stage": "in_game", "family": "fixture_family"})]:
        invalid = copy.deepcopy(record)
        invalid[field] = value
        with pytest.raises(ValueError):
            registry.record_conformance(invalid)
    registry.record_conformance(record)
    changed = copy.deepcopy(record)
    changed["platform"] = "windows"
    with pytest.raises(ValueError, match="immutable"):
        registry.record_conformance(changed)
    stored = registry.get_conformance(record["id"])
    stored["platform"] = "windows"
    with pytest.raises(ValueError, match="hash changed"):
        registry.verify_conformance(stored)


@pytest.mark.parametrize("kind", ["synthetic", "documented", "documentation_only"])
def test_ck3_synthetic_and_documented_profiles_cannot_claim_c(tmp_path, kind):
    registry = EvidenceRegistry(tmp_path)
    record = fixture_record(registry)
    profile = fixture_profile(record)
    profile["kind"] = kind
    with pytest.raises(ValueError, match="manufacture C"):
        registry.register_profile(profile)
