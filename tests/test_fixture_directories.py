import base64
import hashlib
import json
from pathlib import Path

import pytest

from backend.engine.fixture_directories import materialize_fixture, load_fixture_directory
from backend.engine.fixtures import load_fixture


def source_hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("identifier", ["F03", "F04", "F13", "F18"])
def test_materialized_sources_match_exact_catalog_bytes_and_loading_never_writes(tmp_path, identifier):
    root = tmp_path / identifier
    loaded = materialize_fixture(identifier, root)
    case = load_fixture(identifier)
    assert loaded["id"] == identifier
    assert loaded["profile"]["kind"] == "synthetic"
    assert loaded["tier"] == "contract"
    assert loaded["profile"]["production_export_enabled"] is False
    assert "inputs" not in loaded
    assert loaded["baselines"] == case["baselines"]
    sources = {source["owner"]: Path(source["path"]) for source in loaded["sources"]}
    for item in case["inputs"]:
        assert (sources[item["owner"]] / item["path"]).read_bytes() == base64.b64decode(item["bytes_base64"])
    before = source_hashes(root)
    assert load_fixture_directory(root) == loaded
    assert source_hashes(root) == before
    assert loaded["manifest_hash"] == hashlib.sha256((root / "case.json").read_bytes()).hexdigest()


def test_new_or_empty_destination_is_required_and_existing_bytes_are_untouched(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    sentinel = root / "original"
    sentinel.write_bytes(b"do not overwrite")
    before = source_hashes(root)
    with pytest.raises(FileExistsError):
        materialize_fixture("F03", root)
    assert source_hashes(root) == before
    empty = tmp_path / "empty"
    empty.mkdir()
    assert materialize_fixture("F03", empty)["id"] == "F03"


def test_unsafe_catalog_case_is_rejected_before_destination_creation(tmp_path):
    root = tmp_path / "unsafe"
    with pytest.raises(ValueError):
        materialize_fixture("F16", root)
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("change", ["tamper", "missing", "extra", "empty_directory"])
def test_loader_rejects_changed_complete_inventory(tmp_path, change):
    root = tmp_path / "case"
    fixture = materialize_fixture("F03", root)
    target = Path(fixture["sources"][0]["path"]) / fixture["sources"][0]["manifest"][0]["path"]
    if change == "tamper":
        target.write_bytes(target.read_bytes().replace(b"1", b"9", 1))
    elif change == "missing":
        target.unlink()
    elif change == "extra":
        (target.parent / "unrecorded.txt").write_bytes(b"unrecorded = yes")
    else:
        (target.parent / "unrecorded").mkdir()
    before = source_hashes(root)
    with pytest.raises(ValueError, match="changed"):
        load_fixture_directory(root)
    assert source_hashes(root) == before


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(schema_version=99),
    lambda data: data.update(tier="conformance"),
    lambda data: data.update(unrecognized="field"),
    lambda data: data["profile"].update(kind="conformed"),
    lambda data: data["profile"].update(evidence_label="C"),
    lambda data: data["profile"].update(production_export_enabled=True),
    lambda data: data["sources"][0].update(root="../outside"),
    lambda data: data["sources"][0]["files"][0].update(path="../../outside"),
    lambda data: data["sources"][0]["files"][0].update(path="in_game\\file.txt"),
    lambda data: data["sources"][0]["files"][0].update(path="in_game/CON.txt"),
    lambda data: data["sources"][1].update(owner=data["sources"][0]["owner"]),
    lambda data: data["sources"][1].update(root="sources/v"),
    lambda data: data.update(playset=["not-a-source"]),
])
def test_manifest_schema_and_path_authority_cannot_be_broadened(tmp_path, mutate):
    root = tmp_path / "case"
    materialize_fixture("F03", root)
    path = root / "case.json"
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))
    before = source_hashes(root)
    with pytest.raises(ValueError):
        load_fixture_directory(root)
    assert source_hashes(root) == before


@pytest.mark.parametrize("location", ["root", "source_file", "source_directory"])
def test_fixture_links_are_rejected_without_reading_or_changing_outside_content(tmp_path, location):
    root = tmp_path / "case"
    fixture = materialize_fixture("F03", root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "original"
    sentinel.write_bytes(b"outside content")
    if location == "root":
        link = tmp_path / "linked"
        try:
            link.symlink_to(root, target_is_directory=True)
        except OSError:
            pytest.skip("Symbolic links unavailable for this Windows account")
        selected = link
    elif location == "source_file":
        selected = root
        target = Path(fixture["sources"][0]["path"]) / fixture["sources"][0]["manifest"][0]["path"]
        target.unlink()
        try:
            target.symlink_to(sentinel)
        except OSError:
            pytest.skip("Symbolic links unavailable for this Windows account")
    else:
        selected = root
        target = root / "sources/escape"
        try:
            target.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("Symbolic links unavailable for this Windows account")
    with pytest.raises(ValueError, match="link|reparse"):
        load_fixture_directory(selected)
    assert sentinel.read_bytes() == b"outside content"


def test_duplicate_json_keys_are_not_silently_accepted(tmp_path):
    root = tmp_path / "case"
    materialize_fixture("F03", root)
    path = root / "case.json"
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + b',"tier":"contract"}')
    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        load_fixture_directory(root)


def test_utf16_manifest_is_not_silently_decoded_as_utf8(tmp_path):
    root = tmp_path / "case"
    materialize_fixture("F03", root)
    path = root / "case.json"
    path.write_bytes(path.read_text().encode("utf-16"))
    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        load_fixture_directory(root)


def test_source_update_during_verification_refuses_mixed_directory(tmp_path, monkeypatch):
    from backend.engine import fixture_directories
    root = tmp_path / "case"
    fixture = materialize_fixture("F03", root)
    original_hash = fixture_directories.hash_source_file
    altered = False

    def hash_then_change(source_root, relative, **kwargs):
        nonlocal altered
        result = original_hash(source_root, relative, **kwargs)
        if not altered:
            altered = True
            path = source_root / relative
            path.write_bytes(path.read_bytes() + b"# external update\n")
        return result

    monkeypatch.setattr(fixture_directories, "hash_source_file", hash_then_change)
    with pytest.raises(ValueError, match="changed during verification"):
        load_fixture_directory(root)
    assert Path(fixture["sources"][0]["path"]).is_dir()


def test_failed_materialization_preserves_empty_destination_and_cleans_own_staging(tmp_path, monkeypatch):
    from backend.engine import fixture_directories
    root = tmp_path / "empty"
    root.mkdir()
    original_write = fixture_directories.ManagedFS.write_bytes
    calls = 0

    def fail_write(self, path, data, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected full disk")
        return original_write(self, path, data, **kwargs)

    monkeypatch.setattr(fixture_directories.ManagedFS, "write_bytes", fail_write)
    with pytest.raises(OSError, match="injected full disk"):
        materialize_fixture("F03", root)
    assert root.is_dir() and list(root.iterdir()) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["empty"]
