import hashlib
import os

import pytest

from backend.app import store as store_module
from backend.app.store import Conflict, Store


def source(tmp_path, raw=b"opaque\x00bytes" * 10000):
    root = tmp_path / "source"
    root.mkdir()
    (root / "texture.dds").write_bytes(raw)
    return root, raw


def test_existing_exact_blob_is_verified_and_reused_without_ingest_writes(tmp_path, monkeypatch):
    root, raw = source(tmp_path)
    store = Store(tmp_path / "state")
    checksum = store.blob(raw)
    blob = store.root / f"blobs/sha256/{checksum[:2]}/{checksum}"
    before = (blob.read_bytes(), blob.stat().st_mtime_ns)
    original = store_module.hash_source_file
    calls = []

    def checked(source_root, relative, **kwargs):
        calls.append((source_root, relative, kwargs))
        return original(source_root, relative, **kwargs)

    def no_ingest(*_args, **_kwargs):
        raise AssertionError("an existing blob must not open an ingest writer")

    monkeypatch.setattr(store_module, "hash_source_file", checked)
    monkeypatch.setattr(store.fs, "_parent", no_ingest)
    progress = []
    captured = store.capture_source(root, "texture.dds", native_paths=True, checkpoint=progress.append)
    assert captured == {"sha256": checksum, "size": len(raw)}
    assert calls[0] == (root, "texture.dds", {"max_bytes": 2 ** 42, "native_paths": True})
    assert calls[1][0] == store.root and calls[1][1].endswith(checksum)
    assert len(calls) == 2 and progress == [len(raw)]
    assert (blob.read_bytes(), blob.stat().st_mtime_ns) == before
    assert not (store.root / "blobs/ingest").exists()
    assert (root / "texture.dds").read_bytes() == raw
    store.close()


@pytest.mark.parametrize("corruption", ["same_size", "different_size"])
def test_existing_corrupt_blob_cannot_be_reused_or_overwritten(tmp_path, corruption):
    root, raw = source(tmp_path)
    store = Store(tmp_path / "state")
    checksum = store.blob(raw)
    blob = store.root / f"blobs/sha256/{checksum[:2]}/{checksum}"
    damaged = b"x" * len(raw) if corruption == "same_size" else b"short corruption"
    blob.write_bytes(damaged)
    with pytest.raises(Conflict, match="integrity"):
        store.capture_source(root, "texture.dds")
    assert blob.read_bytes() == damaged
    assert not (store.root / "blobs/ingest").exists()
    store.close()


def test_source_with_same_size_and_timestamp_uses_current_bytes(tmp_path):
    root, raw = source(tmp_path)
    store = Store(tmp_path / "state")
    first = store.capture_source(root, "texture.dds")
    asset = root / "texture.dds"
    prior = asset.stat()
    changed = b"z" * len(raw)
    asset.write_bytes(changed)
    os.utime(asset, ns=(prior.st_atime_ns, prior.st_mtime_ns))
    current = store.capture_source(root, "texture.dds")
    assert current["sha256"] == hashlib.sha256(changed).hexdigest()
    assert current["sha256"] != first["sha256"]
    assert (store.root / f"blobs/sha256/{first['sha256'][:2]}/{first['sha256']}").read_bytes() == raw
    store.close()


def test_change_between_preliminary_hash_and_copy_never_publishes(tmp_path, monkeypatch):
    root, raw = source(tmp_path)
    store = Store(tmp_path / "state")
    original = store_module.hash_source_file
    changed = b"z" * len(raw)

    def mutate(source_root, relative, **kwargs):
        result = original(source_root, relative, **kwargs)
        if source_root == root:
            (root / relative).write_bytes(changed)
        return result

    monkeypatch.setattr(store_module, "hash_source_file", mutate)
    with pytest.raises(Conflict, match="between hashing and capture"):
        store.capture_source(root, "texture.dds")
    assert not list((store.root / "blobs/sha256").glob("*/*"))
    assert not list((store.root / "blobs/ingest").glob("*"))
    store.close()


def test_preliminary_hash_enforces_bound_before_ingest_or_dedup(tmp_path):
    root, raw = source(tmp_path)
    store = Store(tmp_path / "state")
    checksum = store.blob(raw)
    with pytest.raises(ValueError, match="bounded"):
        store.capture_source(root, "texture.dds", max_bytes=len(raw) - 1)
    assert not (store.root / "blobs/ingest").exists()
    assert (store.root / f"blobs/sha256/{checksum[:2]}/{checksum}").read_bytes() == raw
    store.close()
