import os
import sqlite3
import hashlib
import threading
from contextlib import contextmanager

import pytest

from backend.app.store import Store, Conflict
from backend.engine import safety


@pytest.mark.parametrize("position", ["root", "ancestor"])
def test_store_rejects_linked_root_before_any_external_write(tmp_path, position):
    external = tmp_path / "outside"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_bytes(b"untouched original")
    link = tmp_path / "link"
    link.symlink_to(external, target_is_directory=True)
    selected = link if position == "root" else link / "new-workspace"
    with pytest.raises(ValueError, match="link/reparse"):
        Store(selected)
    assert sorted(path.name for path in external.iterdir()) == ["sentinel"]
    assert sentinel.read_bytes() == b"untouched original"


@pytest.mark.parametrize("name", ["workspace.sqlite3", "workspace.sqlite3-wal", "workspace.sqlite3-shm",
                                  "session-token", "coordinator.lock", "blobs", "backups", "managed"])
def test_preexisting_reserved_links_cannot_gain_write_authority(tmp_path, name):
    root, external = tmp_path / "managed", tmp_path / "outside"
    root.mkdir()
    external.mkdir()
    sentinel = external / "original"
    sentinel.write_bytes(b"original")
    target = external if name in {"blobs", "backups", "managed"} else sentinel
    (root / name).symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(ValueError, match="link/reparse"):
        Store(root)
    assert sentinel.read_bytes() == b"original"
    assert sorted(path.name for path in external.iterdir()) == ["original"]


def test_sqlite_hardlink_cannot_modify_an_original_database(tmp_path):
    root = tmp_path / "managed"
    root.mkdir()
    original = tmp_path / "original.sqlite3"
    connection = sqlite3.connect(original)
    connection.execute("CREATE TABLE original(value TEXT)")
    connection.execute("INSERT INTO original VALUES('preserved')")
    connection.commit()
    connection.close()
    before = original.read_bytes()
    os.link(original, root / "workspace.sqlite3")
    with pytest.raises(ValueError, match="unshared"):
        Store(root)
    assert original.read_bytes() == before


def test_blob_parent_and_leaf_links_preserve_outside_sentinels(tmp_path):
    store = Store(tmp_path / "managed")
    external = tmp_path / "outside"
    external.mkdir()
    raw = b"snapshot bytes"
    checksum = __import__("hashlib").sha256(raw).hexdigest()
    sentinel = external / checksum
    sentinel.write_bytes(b"private original")
    blobs = store.root / "blobs"
    blobs.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        store.blob(raw)
    assert sentinel.read_bytes() == b"private original"
    assert list(external.iterdir()) == [sentinel]
    blobs.unlink()
    leaf = store.root / "blobs" / "sha256" / checksum[:2] / checksum
    leaf.parent.mkdir(parents=True)
    leaf.symlink_to(sentinel)
    with pytest.raises(ValueError):
        store.blob(raw)
    assert sentinel.read_bytes() == b"private original"
    store.close()


def test_atomic_event_and_idempotency_writes_do_not_commit_partial_generation(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(RuntimeError):
        with store.atomic():
            store.put("scan", {"id": "scan-1"})
            store.append_event("job-1", {"phase": "incomplete"})
            store.cache_request("key", "hash", {"scan_id": "scan-1"})
            raise RuntimeError("injected generation failure")
    with pytest.raises(KeyError):
        store.get("scan", "scan-1")
    assert store.events("job-1") == []
    assert store.cached_request("key", "hash") is None
    store.close()


def test_streamed_large_asset_uses_bounded_reads_and_keeps_database_responsive(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    raw = bytes(range(256)) * (5 * 1024 * 1024 // 256)
    (source / "texture.dds").write_bytes(raw)
    store = Store(tmp_path / "managed")
    store.put("job", {"id": "query-during-stream", "state": "running"})
    original = safety.open_source_stream
    reads, queried = [], []
    @contextmanager
    def bounded_reader(root, relative):
        with original(root, relative) as stream:
            class Reader:
                def fileno(self):
                    return stream.fileno()
                def read(self, size=-1):
                    assert 0 < size <= 1024 * 1024
                    reads.append(size)
                    return stream.read(size)
            yield Reader()
    monkeypatch.setattr(safety, "open_source_stream", bounded_reader)
    def checkpoint(_size):
        if queried:
            return
        query = threading.Thread(target=lambda: queried.append(store.get("job", "query-during-stream")["state"]))
        query.start()
        query.join(timeout=2)
        assert not query.is_alive(), "large source capture held the database lock"
    captured = store.capture_source(source, "texture.dds", checkpoint=checkpoint)
    assert captured == {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    assert queried == ["running"] and len(reads) > 5
    output = store.root / "blobs" / "sha256" / captured["sha256"][:2] / captured["sha256"]
    assert output.read_bytes() == raw
    prior_mtime = output.stat().st_mtime_ns
    assert store.capture_source(source, "texture.dds") == captured
    assert output.stat().st_mtime_ns == prior_mtime
    assert (source / "texture.dds").read_bytes() == raw
    assert list((store.root / "blobs/ingest").iterdir()) == []
    store.close()


@pytest.mark.parametrize("change", ["modify", "replace", "cancel", "budget"])
def test_interrupted_or_changed_stream_never_publishes_a_blob(tmp_path, change):
    source = tmp_path / "source"
    source.mkdir()
    asset = source / "asset.dds"
    asset.write_bytes(b"a" * (3 * 1024 * 1024))
    store = Store(tmp_path / "managed")
    changed = []
    def checkpoint(_size):
        if changed:
            return
        changed.append(True)
        if change == "modify":
            with asset.open("r+b") as stream:
                stream.write(b"z")
        elif change == "replace":
            asset.rename(source / "prior.dds")
            asset.write_bytes(b"z" * (3 * 1024 * 1024))
        elif change == "cancel":
            raise RuntimeError("cancelled at a source chunk boundary")
    with pytest.raises((ValueError, RuntimeError), match="changed|cancelled|bounded"):
        store.capture_source(source, "asset.dds", checkpoint=checkpoint,
                             max_bytes=1024 if change == "budget" else 16 * 1024 * 1024)
    assert not list((store.root / "blobs/sha256").glob("*/*"))
    assert list((store.root / "blobs/ingest").iterdir()) == []
    store.close()


def test_streamed_capture_cannot_overwrite_corrupted_cas_or_follow_source_link(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "asset").write_bytes(b"source bytes")
    store = Store(tmp_path / "managed")
    first = store.capture_source(source, "asset")
    output = store.root / "blobs" / "sha256" / first["sha256"][:2] / first["sha256"]
    output.write_bytes(b"externally changed")
    with pytest.raises(Conflict, match="integrity"):
        store.capture_source(source, "asset")
    assert output.read_bytes() == b"externally changed"
    (source / "link").symlink_to(output)
    with pytest.raises(ValueError):
        store.capture_source(source, "link")
    assert list((store.root / "blobs/ingest").iterdir()) == []
    store.close()
