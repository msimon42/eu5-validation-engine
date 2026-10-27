import json
from types import SimpleNamespace

import pytest

from backend.engine import runtime
from backend.engine.runtime import RuntimeWorker, compare_logs, discover, fingerprint_installation
from backend.engine.safety import sha256_bytes


def test_runtime_unavailable_truthful_on_non_windows(tmp_path):
    if runtime.os.name == "nt":
        pytest.skip("non-Windows boundary test")
    worker = RuntimeWorker(tmp_path)
    assert worker.status()["available"] is False
    result = worker.run_recipe({"kind": "baseline"})
    assert result["outcome"] == "not_run" and result["executed"] is False
    assert result["active_state_confirmed"] is False
    assert json.loads((tmp_path / "runs" / result["id"] / "record.json").read_text())["outcome"] == "not_run"


def test_read_only_steam_all_libraries_fixture_inspection(tmp_path):
    root, second = tmp_path / "Steam", tmp_path / "OtherLibrary"
    (root / "steamapps").mkdir(parents=True)
    (second / "steamapps/common/Europa Universalis V").mkdir(parents=True)
    raw = ('"libraryfolders" { "0" { "path" "' + str(root) + '" } "1" { "path" "' + str(second) + '" } }').encode()
    manifest = root / "steamapps/libraryfolders.vdf"
    manifest.write_bytes(raw)
    result = discover([root], tmp_path / "Documents")
    assert len(result["libraries"]) == 2
    assert sum(item["game_present"] for item in result["libraries"]) == 1
    assert result["active_state"] == "unknown"
    assert manifest.read_bytes() == raw


def test_log_multisets_retain_counts_values_and_absence_is_not_success():
    diff = compare_logs("warn x=31\nwarn x=31\nold\n", "warn x=31\nwarn x=31\nwarn x=31\nnew x=47\n")
    rows = {row["message"]: row for row in diff["changes"]}
    assert rows["warn x=31"]["delta"] == 1
    assert rows["old"]["current_count"] == 0
    assert rows["new x=47"]["baseline_count"] == 0
    assert "do not prove" in diff["interpretation"]


def test_any_selected_version_is_fingerprinted_and_updates_are_detected(tmp_path):
    game, docs, evidence = tmp_path / "Game", tmp_path / "Docs", tmp_path / "managed"
    game.mkdir()
    docs.mkdir()
    exe = game / "eu5.exe"
    exe.write_bytes(b"arbitrary past or future build")
    (game / "content.bin").write_bytes(b"content-1")
    (docs / "script_docs.txt").write_bytes(b"docs-1")
    one = fingerprint_installation(exe, content_roots=[game], docs_roots=[docs], dlc_roots=[game / "missing-dlc"])
    assert one["complete"] and one["documentation_available"]
    assert one["dlc_enabled_state"] == "unconfirmed"
    (game / "content.bin").write_bytes(b"content-2")
    two = fingerprint_installation(exe, content_roots=[game], docs_roots=[docs], dlc_roots=[game / "missing-dlc"])
    assert one["build_fingerprint"]["content_sha256"] != two["build_fingerprint"]["content_sha256"]
    assert one["build_fingerprint"]["executable_sha256"] == two["build_fingerprint"]["executable_sha256"]
    worker = RuntimeWorker(evidence)
    configured = worker.configure_target({"executable": str(exe), "content_roots": [str(game)],
                                          "docs_roots": [str(docs)], "version_display": "arbitrary-future-version"})
    assert configured["version_display"] == "arbitrary-future-version"
    assert RuntimeWorker(evidence).target["build_fingerprint"] == configured["build_fingerprint"]
    with pytest.raises(ValueError, match="overlap"):
        worker.configure_target({"executable": str(exe), "content_roots": [str(tmp_path)]})


def test_recipes_reject_unqualified_authority_and_flags(tmp_path, monkeypatch):
    worker = RuntimeWorker(tmp_path)
    with pytest.raises(ValueError):
        worker.run_recipe({"kind": "baseline", "command": "something"})
    with pytest.raises(ValueError):
        worker.run_recipe({"kind": "invented_headless_validator"})
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="enabled"):
        worker._target_command({"arguments": ["--validate"]})


def test_mocked_windows_probe_requires_direct_controls_and_rechecks_crash_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt"))
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"fixture executable bytes, never executed")
    fp = {"executable_sha256": sha256_bytes(exe.read_bytes()), "content_sha256": "b" * 64,
          "docs_sha256": "c" * 64, "dlc_sha256": "d" * 64}
    phases, processes = [], []
    class Process:
        stopped = False
        def poll(self): return None if not self.stopped else 0
        def terminate(self): self.stopped = True
        def wait(self, timeout): return 0
    def launch(command):
        assert command == [str(exe), "-debug_mode"]
        process = Process()
        processes.append(process)
        return process
    def observe(request):
        phases.append(request["phase"])
        if request["phase"] == "observe":
            return {"direct_observation": "fixture UI sentinel", "sentinel_confirmed": True,
                    "sentinel": {"value": 31}, "negative_control": {"value": 47},
                    "milestones": ["main_menu", "new_campaign"], "assertions": [{"id": "value", "outcome": "pass"}]}
        return {"confirmed": True, "game_closed": True, "playset_hash": "AB", "build_fingerprint": fp}
    worker = RuntimeWorker(tmp_path / "managed", target={"executable": str(exe),
                           "executable_sha256": fp["executable_sha256"], "build_fingerprint": fp},
                           observer=observe, launcher=launch, launch_enabled=True)
    recipe = {"kind": "loading_probe", "expected_playset_hash": "AB", "expected_sentinel": {"value": 31}, "launch": True}
    result = worker.run_recipe(recipe)
    assert result["outcome"] == "passed_with_scope" and result["executed"] is True
    assert processes[0].stopped
    assert phases == ["before", "observe", "after"]
    def crashed(request):
        if request["phase"] == "observe":
            raise ValueError("fixture crash")
        return observe(request)
    worker.observer = crashed
    result = worker.run_recipe(recipe)
    assert result["outcome"] == "inconclusive"
    assert "active_after_failure" in result
    assert processes[-1].stopped
    assert exe.read_bytes() == b"fixture executable bytes, never executed"
