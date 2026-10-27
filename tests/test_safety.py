import threading
import subprocess
import sys
from contextlib import contextmanager

import pytest

from backend.engine.safety import (ManagedFS, ManagedLock, check_path_collisions,
                                   read_source_bytes, validate_relative_path)


@pytest.mark.parametrize("path", ["", "../x", "a/../x", "a\\..\\x", "/tmp/x", "C:\\x", "C:x",
                                    "\\\\server\\share", "a//b", "a/./b", "a/", "CON", "nul.txt",
                                    "LPT1.csv", "COM¹.txt", "a/x ", "a/x.", "a/file:stream", "a\x00b",
                                    "a\nb", "a?.txt"])
def test_unsafe_names_rejected_before_materialization(path):
    with pytest.raises(ValueError):
        validate_relative_path(path)


def test_path_policy_preserves_unicode_and_normalizes_only_separators():
    assert validate_relative_path("in_game\\common\\é.txt") == "in_game/common/é.txt"
    assert validate_relative_path("e\u0301.txt") == "e\u0301.txt"
    with pytest.raises(ValueError, match="colliding"):
        check_path_collisions(["a/Foo.txt", "a/foo.txt"])


def test_managed_source_roots_cannot_overlap(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="overlap"):
        ManagedFS(source / "generated", [source])
    with pytest.raises(ValueError, match="overlap"):
        ManagedFS(tmp_path, [source])


def test_managed_root_parent_link_cannot_redirect_initial_writes(tmp_path):
    external = tmp_path / "outside"
    external.mkdir()
    (tmp_path / "alias").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="link/reparse"):
        ManagedFS(tmp_path / "alias" / "managed")
    with pytest.raises(ValueError, match="link/reparse"):
        with ManagedLock(tmp_path / "alias" / "lock"):
            pass
    assert list(external.iterdir()) == []


def test_containment_aliases_bounds_and_immutable_write(tmp_path):
    fs = ManagedFS(tmp_path / "managed", max_bytes=8)
    fs.write_bytes("a/Test", b"original")
    with pytest.raises(ValueError, match="aliased"):
        fs.write_bytes("a/test", b"bad")
    with pytest.raises(ValueError, match="aliased"):
        fs.read_bytes("a/test")
    with pytest.raises(ValueError, match="aliased"):
        fs.unlink("a/test")
    with pytest.raises(FileExistsError):
        fs.write_bytes("a/Test", b"bad", replace=False)
    with pytest.raises(ValueError, match="bounded"):
        fs.write_bytes("large", b"x" * 9)
    assert fs.read_bytes("a/Test") == b"original"
    with pytest.raises(ValueError):
        fs.read_bytes("a/Test", max_bytes=4)


def test_large_read_ceiling_does_not_allocate_the_ceiling(tmp_path, monkeypatch):
    from backend.engine import safety
    fs = ManagedFS(tmp_path / "managed", max_bytes=2 ** 42)
    raw = bytes(range(256)) * 8192 + b"\r\n\x1a"
    fs.write_bytes("journal.bin", raw)
    fdopen = safety.os.fdopen

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def read(self, size):
            assert 0 < size <= 1024 * 1024, "read allocated from the byte ceiling"
            return self.stream.read(size)

    @contextmanager
    def guarded_fdopen(*args, **kwargs):
        with fdopen(*args, **kwargs) as stream:
            yield BoundedReader(stream)

    monkeypatch.setattr(safety.os, "fdopen", guarded_fdopen)
    assert fs.read_bytes("journal.bin") == raw


def test_source_reader_never_follows_parent_or_final_links(tmp_path):
    source, outside = tmp_path / "source", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"private")
    (source / "parent").symlink_to(outside, target_is_directory=True)
    (source / "file").symlink_to(outside / "sentinel")
    for relative in ("parent/sentinel", "file"):
        with pytest.raises((ValueError, OSError)):
            read_source_bytes(source, relative)
    fs = ManagedFS(tmp_path / "managed")
    (fs.root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        fs.write_bytes("escape/sentinel", b"changed")
    assert (outside / "sentinel").read_bytes() == b"private"


def test_safe_snapshot_and_root_identity_check(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_bytes(b"\xef\xbb\xbfx=1\r\n")
    fs = ManagedFS(tmp_path / "managed", [source])
    result = fs.snapshot(source / "a", "blobs/a")
    assert result["size"] == 8
    assert fs.read_bytes("blobs/a") == (source / "a").read_bytes()
    with pytest.raises(ValueError, match="outside"):
        fs.snapshot(tmp_path / "outside", "blobs/b")
    old = tmp_path / "old"
    fs.root.rename(old)
    fs.root.mkdir()
    with pytest.raises(ValueError, match="root changed"):
        fs.write_bytes("x", b"x")


def test_cross_process_style_lock_serializes_competitors(tmp_path):
    lock_path = tmp_path / "lock"
    outcome = []
    with ManagedLock(lock_path):
        def contender():
            try:
                with ManagedLock(lock_path):
                    outcome.append("unexpected")
            except ValueError:
                outcome.append("locked")
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert outcome == ["locked"]
    with ManagedLock(lock_path):
        pass


def test_os_lock_excludes_a_separate_process(tmp_path):
    lock_path = tmp_path / "lock"
    script = "from pathlib import Path\nfrom backend.engine.safety import ManagedLock\nimport sys\ntry:\n with ManagedLock(Path(sys.argv[1])): pass\nexcept ValueError:\n print('locked')\nelse:\n sys.exit(3)\n"
    with ManagedLock(lock_path):
        result = subprocess.run([sys.executable, "-c", script, str(lock_path)],
                                capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "locked"
