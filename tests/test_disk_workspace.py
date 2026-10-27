from pathlib import Path

import pytest

from backend.app.service import Service
from backend.app.store import Conflict
from backend.engine.fixture_directories import materialize_fixture


def test_disk_synthetic_workflow_reads_real_roots_and_pinned_baselines(tmp_path):
    fixture = materialize_fixture("F03", tmp_path / "sources")
    service = Service(tmp_path / "state")
    try:
        workspace = service.create_workspace({"name": "Physical fixture", "mode": "synthetic", "fixture_path": fixture["fixture_path"]})
        assert workspace["mode"] == "synthetic" and len(workspace["sources"]) == 3
        scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
        scan = service.store.get("scan", scan_id)
        assert scan["fixture_manifest_hash"] == fixture["manifest_hash"]
        assert scan["profile"]["kind"] == "synthetic" and scan["baselines"] == fixture["baselines"]
        assert scan["source_roots"] == workspace["sources"]
        staged = service._stage(workspace, {"scan_id": scan_id}, lambda *args: None)
        validated = service._validate(workspace, {"candidate_id": staged["candidate_id"]}, lambda *args: None)
        assert validated["validation"]["experimental_eligible"]
        assert not validated["validation"]["validated_promotion_eligible"]
        source = next(entry for entry in fixture["sources"] if entry["owner"] == "A")
        (Path(source["path"]) / "in_game/common/testdb/10.txt").write_bytes(b"changed source")
        with pytest.raises(Conflict, match="source changed"):
            service._export(workspace, {"candidate_id": staged["candidate_id"]}, lambda *args: None)
        assert not (service.root / "artifacts").exists()
    finally:
        service.close()


@pytest.mark.parametrize("remove_manifest", [False, True])
def test_fixture_mutation_during_capture_never_publishes_a_generation(tmp_path, monkeypatch, remove_manifest):
    from backend.engine import fixture_directories
    fixture = materialize_fixture("F03", tmp_path / "sources")
    service = Service(tmp_path / "state")
    try:
        workspace = service.create_workspace({"name": "Concurrent update", "fixture_path": fixture["fixture_path"]})
        original_load = fixture_directories.load_fixture_directory
        calls = 0

        def changing_fixture(root):
            nonlocal calls
            calls += 1
            if calls == 2:
                if remove_manifest:
                    (Path(fixture["fixture_path"]) / "case.json").unlink()
                else:
                    source = next(entry for entry in fixture["sources"] if entry["owner"] == "A")
                    (Path(source["path"]) / "in_game/common/testdb/10.txt").write_bytes(b"external update")
            return original_load(root)

        monkeypatch.setattr(fixture_directories, "load_fixture_directory", changing_fixture)
        with pytest.raises(Conflict, match="changed during capture"):
            service._scan(workspace, {}, lambda *args: None)
        assert service.store.list("scan", workspace["id"]) == []
        assert service.store.get("workspace", workspace["id"])["generation"] is None
        assert service.store.list("candidate", workspace["id"]) == []
    finally:
        service.close()


def test_missing_fixture_manifest_is_a_user_input_error(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    service = Service(tmp_path / "state")
    try:
        existing = service.store.list("workspace")
        with pytest.raises(ValueError):
            service.create_workspace({"fixture_path": str(sources)})
        assert service.store.list("workspace") == existing
    finally:
        service.close()


def test_disk_fixture_mode_cannot_be_used_to_bypass_source_or_profile_selection(tmp_path):
    fixture = materialize_fixture("F03", tmp_path / "sources")
    service = Service(tmp_path / "state")
    try:
        with pytest.raises(ValueError, match="synthetic mode"):
            service.create_workspace({"mode": "game", "fixture_path": fixture["fixture_path"]})
        with pytest.raises(ValueError, match="no game roots"):
            service.create_workspace({"mode": "synthetic", "fixture_path": fixture["fixture_path"], "sources": [{"owner": "V", "path": str(tmp_path)}]})
        workspace = service.create_workspace({"name": "Disk", "mode": "synthetic", "fixture_path": fixture["fixture_path"]})
        for payload in [{"fixture_id": "F04"}, {"profile_id": "other"}, {"inputs": [{"fake": True}]}, {"baselines": {"fake": True}}]:
            with pytest.raises(ValueError, match="registered source folders"):
                service._scan(workspace, payload, lambda *args: None)
    finally:
        service.close()
