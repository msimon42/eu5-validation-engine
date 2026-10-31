"""File/ZIP assertions for the browser suite; does not invoke app use cases."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.engine.fixture_directories import materialize_fixture  # noqa: E402


def materialize_ck3(destination: Path) -> dict:
    """Build synthetic content only; never read an installed game or user profile."""
    destination.mkdir(parents=True, exist_ok=False)
    steam = destination / "Synthetic Steam"
    installation = steam / "steamapps/common/Crusader Kings III"
    user_data = destination / "Synthetic Documents/Paradox Interactive/Crusader Kings III"
    platform = "windows" if os.name == "nt" else "macos"

    def write(path: Path, raw: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    write(steam / "steamapps/appmanifest_1158310.acf",
          b'"AppState" { "appid" "1158310" "installdir" "Crusader Kings III" "buildid" "synthetic" }')
    executable = "../binaries/ck3.exe" if platform == "windows" else "../binaries/ck3.app/Contents/MacOS/ck3"
    write(installation / "launcher/launcher-settings.json", json.dumps({
        "gameId": "ck3", "rawVersion": "synthetic-ck3-v1", "gameDataPath": str(user_data),
        "exePath": executable, "dlcPath": "../game",
    }).encode())
    write(installation / "launcher" / executable, b"SYNTHETIC EXECUTABLE PLACEHOLDER. NEVER EXECUTED.\n")
    write(installation / "game/common/traits/base.txt", b"shared_trait = { diplomacy = 1 }\n")
    registries = ["mod/alpha.mod", "mod/beta.mod"]
    payloads = [user_data / "mod/alpha", user_data / "mod/beta"]
    for index, (name, payload) in enumerate(zip(("Alpha", "Beta"), payloads, strict=True)):
        descriptor = f'name="Synthetic {name}"\nversion="fixture-1"\nsupported_version="synthetic.*"\n'
        write(payload / "descriptor.mod", descriptor.encode())
        write(user_data / registries[index], (descriptor + f'path="mod/{name.lower()}"\n').encode())
        write(payload / "common/traits/shared.txt", f"shared_trait = {{ diplomacy = {index + 2} }}\n".encode())
    write(payloads[0] / "events/nested/fixture_events.txt",
          b"namespace = ck3_fixture\nck3_fixture.1 = { type = character_event title = ck3_fixture.1.t desc = { first_valid = { desc = ck3_fixture.1.desc } } option = { name = ck3_fixture.1.a } }\n")
    write(payloads[0] / "localization/english/fixture_l_english.yml",
          b'\xef\xbb\xbfl_english:\n trait_shared_trait:0 "Synthetic trait"\n ck3_fixture.1.t:0 "Synthetic event"\n ck3_fixture.1.desc:0 "Preserve every source."\n ck3_fixture.1.a:0 "Continue"\n')
    write(payloads[1] / "gfx/interface/fixture.dds", b"SYNTHETIC OPAQUE ASSET\x00\xff")
    connection = sqlite3.connect(user_data / "launcher-v2.sqlite")
    try:
        connection.executescript("""
            CREATE TABLE playsets(id TEXT,name TEXT,isActive INTEGER);
            CREATE TABLE mods(id TEXT,gameRegistryId TEXT,dirPath TEXT,archivePath TEXT,status TEXT,source TEXT);
            CREATE TABLE playsets_mods(playsetId TEXT,modId TEXT,enabled INTEGER,position INTEGER);
            INSERT INTO playsets VALUES('active','Synthetic active',1),('alternate','Synthetic alternate',0);
        """)
        for index, (registry, payload) in enumerate(zip(registries, payloads, strict=True)):
            connection.execute("INSERT INTO mods VALUES(?,?,?,?,?,?)", (
                str(index), registry, str(payload), None, "ready_to_play", "local"))
            for playset, position in (("active", index), ("alternate", 1 - index)):
                connection.execute("INSERT INTO playsets_mods VALUES(?,?,?,?)", (playset, str(index), 1, position))
        connection.commit()
    finally:
        connection.close()
    write(user_data / "dlc_load.json", json.dumps({"enabled_mods": registries, "disabled_dlcs": []}).encode())
    return {"root": str(destination), "steam": str(steam), "installation": str(installation),
            "user_data": str(user_data), "platform": platform,
            "active_order": ["ck3:" + registry for registry in registries],
            "alternate_order": ["ck3:" + registry for registry in reversed(registries)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["materialize", "materialize_ck3", "inspect_zip"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--fixture", default="F03")
    args = parser.parse_args()
    if args.action == "materialize":
        result = materialize_fixture(args.fixture, args.path)
    elif args.action == "materialize_ck3":
        result = materialize_ck3(args.path)
    else:
        with zipfile.ZipFile(args.path) as bundle:
            if bundle.testzip() is not None:
                raise ValueError("Downloaded bundle failed CRC validation")
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP entries")
            result = {"names": names, "manifest": json.loads(bundle.read("manifest.json")), "files": {}}
            for name in names:
                if name == "manifest.json":
                    continue
                raw = bundle.read(name)
                result["files"][name] = {"bytes_base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
