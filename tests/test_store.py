
import pytest

from backend.app.store import Conflict, Store


def test_atomic_generation_rollback_and_revision(tmp_path):
    store = Store(tmp_path)
    workspace = store.put("workspace", {"id": "w", "name": "original"})
    with pytest.raises(RuntimeError):
        with store.atomic():
            store.put("scan", {"id": "s", "workspace_id": "w"})
            store.put("workspace", {**workspace, "name": "mixed"})
            raise RuntimeError("injected failure")
    assert store.get("workspace", "w")["name"] == "original"
    with pytest.raises(KeyError):
        store.get("scan", "s")
    with pytest.raises(Conflict):
        store.put("workspace", workspace, expected_revision=9)
    store.close()


def test_blob_integrity_and_consistent_backup(tmp_path):
    store = Store(tmp_path / "state")
    sha = store.blob(b"untouched\xff\r\n")
    store.put("scan", {"id": "s", "blob": sha})
    target = store.backup(tmp_path / "backup")
    restored = Store(target)
    assert restored.get("scan", "s")["blob"] == sha
    assert (target / "blobs" / "sha256" / sha[:2] / sha).read_bytes() == b"untouched\xff\r\n"
    (store.root / "blobs" / "sha256" / sha[:2] / sha).write_bytes(b"corrupt")
    with pytest.raises(Conflict):
        store.blob(b"untouched\xff\r\n")
    restored.close()
    store.close()


def test_idempotency_conflict_and_event_order(tmp_path):
    store = Store(tmp_path)
    store.cache_request("k", "hash", {"job_id": "j"})
    assert store.cached_request("k", "hash") == {"job_id": "j"}
    with pytest.raises(Conflict):
        store.cached_request("k", "other")
    first = store.append_event("j", {"phase": "one"})
    second = store.append_event("j", {"phase": "two"})
    assert [entry["sequence"] for entry in store.events("j", first)] == [second]
    store.close()
