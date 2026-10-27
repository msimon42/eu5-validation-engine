
import pytest

from backend.app.store import Store
from backend.engine.backups import BackupManager


def state(tmp_path):
    store = Store(tmp_path / "state")
    store.blob(b"source\xffbytes")
    for relative, raw in {"managed/releases/r/files/mod.txt": b"generated", "managed/journals/j.json": b'{"state":"files_active"}', "evidence-registry/artifacts/run.txt": b"raw observation", "artifacts/review.zip": b"artifact"}.items():
        store.fs.write_bytes(relative, raw)
    store.put("artifact", {"id": "a", "path": str(store.root / "artifacts/review.zip")})
    store.put("candidate", {"id": "c", "status": "ready"})
    store.put("decision", {"id": "d", "state": "current"})
    store.fs.write_bytes("session-token", b"private session")
    return store


def test_complete_backup_restore_evidence_and_stale_state(tmp_path):
    store = state(tmp_path)
    backup = store.backup(tmp_path / "backup")
    assert (backup / "evidence-registry/artifacts/run.txt").read_bytes() == b"raw observation"
    assert not (backup / "session-token").exists()
    restored = BackupManager.restore(backup, tmp_path / "restored")
    assert restored["stale"] and restored["recovery_required"]
    copied = Store(tmp_path / "restored")
    assert copied.get("candidate", "c")["status"] == "stale"
    assert copied.get("decision", "d")["state"] == "stale"
    assert copied.get("artifact", "a")["path"] == str(tmp_path / "restored/artifacts/review.zip")
    assert (copied.root / "managed/releases/r/files/mod.txt").read_bytes() == b"generated"
    copied.close()
    store.close()


def test_restore_checks_hashes_and_never_overwrites(tmp_path):
    store = state(tmp_path)
    backup = store.backup(tmp_path / "backup")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "sentinel").write_bytes(b"keep")
    with pytest.raises((ValueError, FileExistsError)):
        BackupManager.restore(backup, occupied)
    assert (occupied / "sentinel").read_bytes() == b"keep"
    (backup / "artifacts/review.zip").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        BackupManager.restore(backup, tmp_path / "bad-restore")
    assert not (tmp_path / "bad-restore").exists()
    store.close()


def test_backup_rejects_links_before_copying(tmp_path):
    store = state(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    try:
        (store.root / "evidence-registry/escape").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable on this Windows account")
    with pytest.raises(ValueError):
        store.backup(tmp_path / "backup")
    assert outside.read_bytes() == b"untouched"
    store.close()
