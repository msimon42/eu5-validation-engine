import hashlib

import pytest

from backend.app.service import Service
from backend.engine.analysis import analyze


def item(owner, checksum="a" * 64, size=5_000_000_000):
    return {"owner": owner, "path": "in_game/gfx/large.dds", "sha256": checksum, "opaque_blob": {"sha256": checksum, "size": size}}


def test_opaque_reference_keeps_real_hash_and_unknown_coverage():
    result = analyze([item("A")], ["A"])
    file = result["files"][0]
    assert file["sha256"] == "a" * 64 and file["size"] == 5_000_000_000
    assert file["kind"] == "opaque"
    assert result["coverage"]["opaque_or_unsupported_files"] == [file["id"]]
    assert result["coverage"]["conformed_rules"] == 0
    changed = analyze([item("A", "b" * 64)], ["A"])
    assert result["input_manifest_hash"] != changed["input_manifest_hash"]


def test_opaque_collisions_use_bytes_hashes_not_empty_previews():
    same = analyze([item("A"), item("B")], ["A", "B"])
    different = analyze([item("A"), item("B", "b" * 64)], ["A", "B"])
    assert not any(finding["kind"] == "asset_payload_conflict" for finding in same["findings"])
    assert any(finding["kind"] == "asset_payload_conflict" for finding in different["findings"])


@pytest.mark.parametrize("bad", [item("A", "bad"), item("A", size=-1), item("A", size=True)])
def test_opaque_references_require_bounded_hash_metadata(bad):
    result = analyze([bad], ["A"])
    assert result["summary"]["state"] == "invalid_input"


def test_streamed_snapshot_and_game_inventory_preserve_asset(tmp_path):
    source = tmp_path / "source"
    (source / "in_game/gfx").mkdir(parents=True)
    payload = (b"opaque asset\x00" * 500_000)
    (source / "in_game/gfx/large.dds").write_bytes(payload)
    service = Service(tmp_path / "state")
    workspace = service.create_workspace({"name": "Any build", "mode": "game", "sources": [{"owner": "V", "path": str(source)}]})
    captured = service._snapshot_sources(workspace, lambda *args: None)
    assert "bytes_base64" not in captured[0]
    sha = hashlib.sha256(payload).hexdigest()
    assert captured[0]["opaque_blob"]["sha256"] == sha
    assert (service.root / "blobs/sha256" / sha[:2] / sha).read_bytes() == payload
    assert (source / "in_game/gfx/large.dds").read_bytes() == payload
    service.close()
