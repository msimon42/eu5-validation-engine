"""Capture-budget contracts on temporary synthetic roots, never live installs."""
import base64
import copy
import hashlib

import pytest

from backend.app import service as service_module
from backend.app.service import Service
from backend.app.store import Conflict


@pytest.fixture
def service(tmp_path):
    instance = Service(tmp_path / "managed")
    try:
        yield instance
    finally:
        instance.close()


def write(root, path, raw):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)


def test_ck3_primary_mod_and_base_scripts_precede_lower_tiers_without_reordering(service, tmp_path, monkeypatch):
    base, mod = tmp_path / "base", tmp_path / "mod"
    payloads = {
        ("V", "common/traits/base.txt"): b"baseline={diplomacy=1}\n",
        ("V", "gfx/map/generated.txt"): b"symbolic={lots=12345}\n",
        ("V", "localization/base_l_english.yml"): b'l_english:\n base:0 "Base"\n',
        ("A", "common/traits/mod.txt"): b"added={diplomacy=2}\n",
        ("A", "common/unknown/data.txt"): b"symbolic={unknown=123}\n",
        ("A", "descriptor.mod"): b'name="Mod"\n',
        ("A", "localization/mod_l_english.yml"): b'l_english:\n added:0 "Added"\n',
        ("A", "gfx/texture.dds"): b"opaque image bytes",
    }
    roots = {"V": base, "A": mod}
    for (owner, path), raw in payloads.items():
        write(roots[owner], path, raw)
    chosen = {("V", "common/traits/base.txt"), ("A", "common/traits/mod.txt"), ("A", "descriptor.mod")}
    budget = sum(len(payloads[key]) for key in chosen)
    monkeypatch.setattr(service_module, "TEXT_CAPTURE_BUDGET", budget)
    workspace = {"game_id": "ck3", "sources": [{"owner": "V", "path": str(base)}, {"owner": "A", "path": str(mod)}],
                 "default_playset": ["A"]}
    before_workspace = copy.deepcopy(workspace)
    captured = service._snapshot_sources(workspace, lambda *args: None)
    inline = {(row["owner"], row["path"]) for row in captured if "bytes_base64" in row}
    assert inline == chosen
    assert sum(len(base64.b64decode(row["bytes_base64"])) for row in captured if "bytes_base64" in row) == budget
    assert [row["owner"] for row in captured] == ["V"] * 3 + ["A"] * 5
    assert [(row["owner"], row["path"]) for row in captured] == [
        ("V", "common/traits/base.txt"), ("V", "gfx/map/generated.txt"), ("V", "localization/base_l_english.yml"),
        ("A", "descriptor.mod"), ("A", "common/traits/mod.txt"), ("A", "common/unknown/data.txt"),
        ("A", "gfx/texture.dds"), ("A", "localization/mod_l_english.yml"),
    ]
    for row in captured:
        original = payloads[row["owner"], row["path"]]
        assert row["sha256"] == hashlib.sha256(original).hexdigest()
        blob = service.root / "blobs/sha256" / row["sha256"][:2] / row["sha256"]
        assert blob.read_bytes() == original
        assert (roots[row["owner"]] / row["path"]).read_bytes() == original
        if "opaque_blob" in row:
            assert row["capture_reason"] == ("unsupported_family" if row["path"].endswith(".dds") else "text_budget_limit")
    assert workspace == before_workspace


@pytest.mark.parametrize("base_owner", ["V", "base", "vanilla", "DLC:synthetic"])
def test_ck3_mods_precede_all_base_owner_forms_within_the_same_tier(service, tmp_path, monkeypatch, base_owner):
    base, mod = tmp_path / "base", tmp_path / "mod"
    write(base, "common/traits/first.txt", b"a={}")
    write(mod, "common/traits/last.txt", b"b={}")
    monkeypatch.setattr(service_module, "TEXT_CAPTURE_BUDGET", 4)
    workspace = {"game_id": "ck3", "sources": [{"owner": base_owner, "path": str(base)}, {"owner": "A", "path": str(mod)}]}
    captured = service._snapshot_sources(workspace, lambda *args: None)
    assert [row["owner"] for row in captured] == [base_owner, "A"]
    assert captured[0]["capture_reason"] == "text_budget_limit"
    assert base64.b64decode(captured[1]["bytes_base64"]) == b"b={}"


def test_eu5_retains_its_existing_source_order_budget_policy(service, tmp_path, monkeypatch):
    base, mod = tmp_path / "base", tmp_path / "mod"
    write(base, "in_game/common/testdb/a.txt", b"a={}")
    write(mod, "in_game/common/testdb/b.txt", b"b={}")
    monkeypatch.setattr(service_module, "TEXT_CAPTURE_BUDGET", 4)
    captured = service._snapshot_sources({"game_id": "eu5", "sources": [
        {"owner": "V", "path": str(base)}, {"owner": "A", "path": str(mod)}]}, lambda *args: None)
    assert base64.b64decode(captured[0]["bytes_base64"]) == b"a={}"
    assert captured[1]["capture_reason"] == "text_budget_limit"


def test_oversized_text_is_preserved_as_opaque_without_spending_inline_budget(service, tmp_path, monkeypatch):
    root = tmp_path / "source"
    write(root, "common/traits/large.txt", b"")
    with (root / "common/traits/large.txt").open("r+b") as output:
        output.truncate(8_000_001)
    write(root, "common/traits/small.txt", b"a={}")
    monkeypatch.setattr(service_module, "TEXT_CAPTURE_BUDGET", 4)
    captured = service._snapshot_sources({"game_id": "ck3", "sources": [{"owner": "A", "path": str(root)}]}, lambda *args: None)
    assert captured[0]["capture_reason"] == "file_size_limit"
    assert captured[0]["opaque_blob"]["size"] == 8_000_001
    blob = service.root / "blobs/sha256" / captured[0]["sha256"][:2] / captured[0]["sha256"]
    assert blob.stat().st_size == (root / "common/traits/large.txt").stat().st_size == 8_000_001
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == captured[0]["sha256"]
    assert base64.b64decode(captured[1]["bytes_base64"]) == b"a={}"


@pytest.mark.parametrize("mutation", ["bytes", "membership"])
def test_complete_recheck_still_rejects_source_changes_after_priority_selection(service, tmp_path, monkeypatch, mutation):
    root = tmp_path / "source"
    write(root, "common/traits/a.txt", b"a={}")
    write(root, "common/traits/b.txt", b"b={}")
    monkeypatch.setattr(service_module, "TEXT_CAPTURE_BUDGET", 4)
    changed = False

    def checkpoint(phase, index, total):
        nonlocal changed
        if phase == "snapshotting sources" and index == 1 and not changed:
            changed = True
            write(root, "common/traits/a.txt" if mutation == "bytes" else "common/traits/new.txt", b"c={}")

    with pytest.raises(Conflict, match="Source bytes changed|Source inventory changed"):
        service._snapshot_sources({"game_id": "ck3", "sources": [{"owner": "A", "path": str(root)}]}, checkpoint)
