import base64
import copy
import json

import pytest

from backend.engine.evidence import canonical_bytes
from backend.engine.releases import InjectedCrash, ReleaseManager, REQUIRED_GATES
from backend.engine.safety import ManagedLock, sha256_bytes


def candidate(manager, identifier="candidate-1"):
    fp = {key: value * 64 for key, value in (("executable_sha256", "a"), ("content_sha256", "b"),
                                            ("docs_sha256", "c"), ("dlc_sha256", "d"))}
    raw = b"controlled actual observation in a synthetic unit test; no real EU5 run"
    registry = manager.evidence
    registry.fs.write_bytes("artifacts/test/observation", raw)
    registry.record_conformance({"id": "record-1", "experiment_id": "E01", "tier": "conformance",
        "platform": "windows", "outcome": "passed_with_scope", "executed": True, "cold_start": True,
        "active_state_confirmed": True, "direct_observation": "unit-test observation",
        "negative_control": "unit-test control", "build_fingerprint": fp,
        "scope": {"stage": "in_game", "family": "fixture_db"},
        "artifacts": [{"path": "artifacts/test/observation", "sha256": sha256_bytes(raw)}]})
    profile = registry.register_profile({"id": "profile-1", "kind": "conformed", "build_fingerprint": fp,
        "rules": [{"id": "rule-1", "label": "C", "version": "1", "evidence": ["record-1"],
                   "selectors": {"stages": ["in_game"], "families": ["fixture_db"]},
                   "invalidation_keys": ["executable_sha256"]}]})
    inputs = {"source-id": "1" * 64}
    files = [{"path": "in_game/common/fixture_db/zz.txt", "bytes_base64": base64.b64encode(b"REPLACE:item={x=2}\n").decode()}]
    return {"id": identifier, "mode": "game", "workspace_id": "unit-test-only", "inputs": inputs,
            "build_fingerprint": fp, "profile": profile,
            "plan": {"files": files, "write_set": [files[0]["path"]],
                     "affected_scope": [{"stage": "in_game", "family": "fixture_db", "fields": ["x"]}],
                     "obligations": [{"id": "A-x", "status": "satisfied", "evidence_ids": ["assert-x"]}]},
            "validation": {"gates": [{"id": key, "required": True, "outcome": "pass"} for key in sorted(REQUIRED_GATES)],
                           "inputs_sha256": sha256_bytes(canonical_bytes(inputs)), "profile_sha256": profile["sha256"],
                           "complete_obligation_closure": True, "obligation_ids": ["A-x"]}}


def observer(_manifest):
    return {"confirmed": True, "direct_observation": "unit-test-only sentinel", "playset_hash": "test-playset"}


def test_experimental_export_is_inactive_and_excludes_original_corpus(tmp_path):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    item["mode"] = "synthetic"
    item["inputs"] = {"files": [{"path": "original", "bytes_base64": base64.b64encode(b"ORIGINAL_SECRET").decode(),
                                  "_raw": "ORIGINAL_SECRET", "sha256": "a" * 64}]}
    bundle = manager.export_bundle(item)
    manifest = (bundle / "manifest.json").read_bytes()
    assert b"ORIGINAL_SECRET" not in manifest
    assert b"bytes_base64" not in manifest
    assert json.loads(manifest)["kind"] == "experimental_bundle"
    assert not (tmp_path / "active-release.json").exists()
    assert manager.active() is None
    assert manager.export_bundle(item) == bundle


@pytest.mark.parametrize("mutation", ["synthetic", "missing_gate", "unknown", "omit_obligation", "unconformed", "scope", "stale"])
def test_promotion_fails_closed(tmp_path, mutation):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    actual = copy.deepcopy(item["inputs"])
    if mutation == "synthetic":
        item["mode"] = "synthetic"
    if mutation == "missing_gate":
        item["validation"]["gates"].pop()
    if mutation == "unknown":
        item["validation"]["gates"][0]["outcome"] = "unknown"
    if mutation == "omit_obligation":
        item["validation"]["obligation_ids"] = []
    if mutation == "unconformed":
        item["profile"]["kind"] = "documented"
    if mutation == "scope":
        item["plan"]["affected_scope"][0]["family"] = "unmeasured"
    if mutation == "stale":
        actual["source-id"] = "2" * 64
    with pytest.raises(ValueError):
        manager.promote(item, actual, verify_activation=observer)
    assert manager.active() is None


def test_real_scope_requires_direct_activation_observer(tmp_path):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    with pytest.raises(ValueError, match="observer"):
        manager.promote(item, item["inputs"])
    with pytest.raises(ValueError, match="not directly confirmed"):
        manager.promote(item, item["inputs"], verify_activation=lambda _: {"confirmed": True})
    assert manager.active() is None


def test_immutable_multi_file_release_and_exact_rollback(tmp_path):
    manager = ReleaseManager(tmp_path)
    first = candidate(manager)
    first["plan"]["files"].append({"path": "in_game/common/fixture_db/other.txt", "bytes_base64": "eD0xCg=="})
    first["plan"]["write_set"].append("in_game/common/fixture_db/other.txt")
    one = manager.promote(first, first["inputs"], verify_activation=observer)
    pointer_one = manager.active()
    second = candidate(manager, "candidate-2")
    second["plan"]["files"][0]["bytes_base64"] = base64.b64encode(b"REPLACE:item={x=3}\n").decode()
    two = manager.promote(second, second["inputs"], verify_activation=observer)
    assert manager.active()["release_id"] == two["id"]
    preview = manager.rollback(two["id"], preview=True)
    assert preview["previous_pointer"] == pointer_one
    assert manager.rollback(two["id"])["state"] == "rolled_back"
    assert manager.active() == pointer_one
    assert manager.rollback(one["id"])["state"] == "rolled_back"
    assert manager.active() is None
    assert (tmp_path / "releases" / one["id"]).exists()


@pytest.mark.parametrize("boundary", ["staging_write", "prepared", "validated", "promotion_started", "files_active", "playset_applied"])
def test_crash_recovery_at_durable_boundaries(tmp_path, boundary):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    with pytest.raises(InjectedCrash):
        manager.promote(item, item["inputs"], verify_activation=observer, fault_at=boundary)
    restarted = ReleaseManager(tmp_path)
    recovered = restarted.recover()
    assert all(journal["state"] == "rolled_back" for journal in recovered)
    assert restarted.active() is None


def test_source_change_during_activation_restores_previous_pointer(tmp_path):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    actual = dict(item["inputs"])
    def mutate(_):
        actual["source-id"] = "changed-during-activation"
        return observer(_)
    with pytest.raises(ValueError, match="inputs changed"):
        manager.promote(item, lambda: actual, verify_activation=mutate)
    assert manager.active() is None


def test_external_edits_and_competing_promotions_are_preserved(tmp_path):
    manager = ReleaseManager(tmp_path)
    item = candidate(manager)
    with ManagedLock(manager.fs.resolve(".locks/promotion.lock")):
        with pytest.raises(ValueError, match="locked"):
            manager.promote(item, item["inputs"], verify_activation=observer)
    result = manager.promote(item, item["inputs"], verify_activation=observer)
    output = tmp_path / "releases" / result["id"] / "files" / item["plan"]["files"][0]["path"]
    output.write_bytes(b"external-user-edit")
    with pytest.raises(ValueError, match="externally changed"):
        manager.rollback(result["id"])
    assert output.read_bytes() == b"external-user-edit"
