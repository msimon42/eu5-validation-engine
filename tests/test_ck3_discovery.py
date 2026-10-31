import json
import sqlite3

import pytest

from backend.engine import ck3_discovery
from backend.engine.ck3_discovery import discover_ck3


def environment(tmp_path, *, platform="macos"):
    steam = tmp_path / "Steam"
    install = steam / "steamapps/common/Crusader Kings III"
    (install / "game/common").mkdir(parents=True)
    (install / "launcher").mkdir()
    user = tmp_path / "Documents/Paradox Interactive/Crusader Kings III"
    (user / "mod").mkdir(parents=True)
    executable = "../binaries/ck3.exe" if platform == "windows" else "../binaries/ck3.app/Contents/MacOS/ck3"
    (install / "launcher/launcher-settings.json").write_text(json.dumps({
        "gameId": "ck3", "rawVersion": "fixture-1", "gameDataPath": str(user),
        "exePath": executable, "dlcPath": "../game"}))
    (steam / "steamapps/appmanifest_1158310.acf").write_text(
        '"AppState" { "appid" "1158310" "installdir" "Crusader Kings III" }')
    return steam, install, user


def database(user, entries, *, wal=False):
    connection = sqlite3.connect(user / "launcher-v2.sqlite")
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE playsets(id TEXT,name TEXT,isActive INTEGER);
        CREATE TABLE mods(id TEXT,gameRegistryId TEXT,dirPath TEXT,archivePath TEXT,status TEXT,source TEXT);
        CREATE TABLE playsets_mods(playsetId TEXT,modId TEXT,enabled INTEGER,position INTEGER);
        INSERT INTO playsets VALUES('active','Fixture active',1),('other','Fixture other',0);
    """)
    for number, (registry, path, enabled, position) in enumerate(entries):
        connection.execute("INSERT INTO mods VALUES(?,?,?,?,?,?)", (
            str(number), registry, str(path), None, "ready_to_play", "local"))
        connection.execute("INSERT INTO playsets_mods VALUES(?,?,?,?)", ("active", str(number), enabled, position))
    connection.commit()
    return connection


def mod(user, name, *, body="", path=None):
    payload = path or user / "mod" / name
    payload.mkdir(parents=True)
    (payload / "common").mkdir(exist_ok=True)
    registry = f"mod/{name}.mod"
    (user / registry).write_text(f'name="{name}"\npath="{payload.as_posix()}"\n' + body)
    return registry, payload


def inputs(steam, **kwargs):
    kwargs.setdefault("user_data_path", steam.parent / "Documents/Paradox Interactive/Crusader Kings III")
    return discover_ck3(platform="macos", steam_roots=[steam], **kwargs)


def source_files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("platform", ["macos", "windows"])
def test_discovers_installation_descriptors_order_and_preserves_sources(tmp_path, platform):
    steam, install, user = environment(tmp_path, platform=platform)
    first, one = mod(user, "first", body='replace_path="common/traits"\ndependencies={ "Other" }\n')
    second, two = mod(user, "second")
    disabled, off = mod(user, "disabled")
    connection = database(user, [(second, two, 1, 20), (disabled, off, 0, 30), (first, one, 1, 10)])
    connection.close()
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": [first, second], "disabled_dlcs": []}))
    before = source_files(tmp_path)
    result = discover_ck3(platform=platform, steam_roots=[steam], user_data_path=user)
    assert result["complete"], result["diagnostics"]
    assert result["playset"] == ["ck3:" + first, "ck3:" + second]
    assert [source["owner"] for source in result["sources"]] == ["V", *result["playset"]]
    assert result["installation"]["content_root"] == str(install / "game")
    assert result["selected_playset_id"] == "active"
    assert result["mods"][0]["replace_paths"] == ["common/traits"]
    assert result["mods"][0]["dependencies"] == ["Other"]
    assert result["capabilities"]["executed_game_evidence"] is False
    assert source_files(tmp_path) == before
    if platform == "macos":
        assert inputs(steam)["configuration_hash"] == result["configuration_hash"]


def test_other_steam_library_and_explicit_selections(tmp_path):
    steam, install, user = environment(tmp_path / "second")
    primary = tmp_path / "primary"
    (primary / "steamapps").mkdir(parents=True)
    (primary / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "path" "' + steam.as_posix() + '" } }')
    (user / "dlc_load.json").write_text('{"enabled_mods":[]}')
    result = inputs(primary, user_data_path=user)
    assert result["complete"]
    assert result["installation"]["path"] == str(install)
    override = discover_ck3(platform="windows", steam_roots=[], installation_path=install, user_data_path=user)
    assert override["complete"]


def test_missing_payload_is_not_hidden_by_ready_to_play(tmp_path):
    steam, _, user = environment(tmp_path)
    registry, payload = mod(user, "missing")
    (payload / "common").rmdir()
    payload.rmdir()
    connection = database(user, [(registry, payload, 1, 1)])
    connection.close()
    result = inputs(steam)
    assert not result["complete"]
    assert result["consistent"]
    assert not result["mods"][0]["available"]
    assert result["mods"][0]["status"] == "ready_to_play"
    assert result["playset"] == []


def test_wal_is_read_without_ignoring_commits_or_changing_originals(tmp_path):
    steam, _, user = environment(tmp_path)
    registry, payload = mod(user, "walmod")
    connection = database(user, [(registry, payload, 1, 1)], wal=True)
    before = source_files(tmp_path)
    assert (user / "launcher-v2.sqlite-wal").exists()
    result = inputs(steam)
    assert result["complete"], result["diagnostics"]
    assert result["playset"] == ["ck3:" + registry]
    assert source_files(tmp_path) == before
    connection.close()


def test_root_override_is_required_for_external_payload(tmp_path):
    steam, _, user = environment(tmp_path)
    registry, external = mod(user, "external", path=tmp_path / "private-mod")
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": [registry]}))
    blocked = inputs(steam)
    assert not blocked["complete"]
    allowed = inputs(steam, root_overrides={registry: external})
    assert allowed["complete"]
    assert allowed["sources"][-1]["path"] == str(external)
    assert allowed["configuration_hash"] != blocked["configuration_hash"]


def test_traversal_descriptor_and_linked_payload_never_grant_sources(tmp_path):
    steam, _, user = environment(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (user / "mod/link").symlink_to(external, target_is_directory=True)
    (user / "mod/link.mod").write_text('path="mod/link"')
    (user / "dlc_load.json").write_text('{"enabled_mods":["mod/link.mod","../outside.mod"]}')
    result = inputs(steam)
    assert not result["complete"]
    assert len(result["sources"]) == 1
    assert len(result["mods"]) == 2


def test_launcher_mismatch_and_explicit_saved_playset_selection(tmp_path):
    steam, _, user = environment(tmp_path)
    registry, payload = mod(user, "one")
    connection = database(user, [(registry, payload, 1, 1)])
    connection.close()
    (user / "dlc_load.json").write_text('{"enabled_mods":[]}')
    result = inputs(steam)
    assert not result["complete"]
    assert any(row["code"] == "launcher_state_mismatch" for row in result["diagnostics"])
    other = inputs(steam, playset_id="other")
    assert other["complete"]
    assert other["selected_playset_id"] == "other"
    assert other["playset"] == []


def test_metadata_change_during_discovery_rejects_consistency(tmp_path, monkeypatch):
    steam, _, user = environment(tmp_path)
    registry, payload = mod(user, "one")
    connection = database(user, [(registry, payload, 1, 1)])
    connection.close()
    (user / "dlc_load.json").write_text(json.dumps({"enabled_mods": [registry]}))
    original = ck3_discovery._database_rows

    def changed(records):
        result = original(records)
        (user / "dlc_load.json").write_text('{"enabled_mods":[]}')
        return result

    monkeypatch.setattr(ck3_discovery, "_database_rows", changed)
    result = inputs(steam)
    assert not result["complete"]
    assert not result["consistent"]
    assert any(row["code"] == "metadata_changed" for row in result["diagnostics"])


@pytest.mark.parametrize("body", ['path!="mod/target"', 'path="mod/target" path="mod/target"',
                                 'path={ "mod/target" }', 'path="mod/target" bare_statement'])
def test_ambiguous_descriptor_paths_never_resolve_payload_roots(tmp_path, body):
    steam, _, user = environment(tmp_path)
    (user / "mod/target").mkdir()
    (user / "mod/ambiguous.mod").write_text(body)
    (user / "dlc_load.json").write_text('{"enabled_mods":["mod/ambiguous.mod"]}')
    result = inputs(steam)
    assert not result["complete"]
    assert result["playset"] == []


def test_missing_database_is_never_created_and_invalid_state_is_reported(tmp_path):
    steam, _, user = environment(tmp_path)
    result = inputs(steam)
    assert not result["complete"]
    assert not (user / "launcher-v2.sqlite").exists()
    (user / "dlc_load.json").write_text('{"enabled_mods":"wrong"}')
    invalid = inputs(steam)
    assert not invalid["complete"] and not invalid["consistent"]
    (user / "launcher-v2.sqlite").write_bytes(b"not a sqlite database")
    (user / "dlc_load.json").write_text('{"enabled_mods":[]}')
    corrupt = inputs(steam)
    assert not corrupt["complete"] and not corrupt["consistent"]


def test_duplicate_positions_unknown_playsets_and_foreign_paths(tmp_path):
    steam, _, user = environment(tmp_path)
    one, first = mod(user, "first")
    two, second = mod(user, "second")
    connection = database(user, [(one, first, 1, 1), (two, second, 1, 1)])
    connection.close()
    assert not inputs(steam)["complete"]
    assert not inputs(steam, playset_id="unknown")["complete"]
    with pytest.raises(ValueError):
        discover_ck3(platform="linux")
