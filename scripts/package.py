"""Build an offline-transfer archive from the tested source and compiled UI.

The archive includes locked source dependencies, not proprietary game inputs or
machine-specific environments. First dependency installation needs networking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(destination: Path) -> Path:
    if not (ROOT / "frontend/dist/index.html").exists():
        raise ValueError("Build the frontend before creating a release archive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ["backend", "frontend/dist", "frontend/src", "frontend/e2e", "scripts", "profiles", "schemas", "docs", "specs"]:
        paths.extend(path for path in (ROOT / name).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    paths += [ROOT / name for name in ["README.md", "Start-EU5.cmd", "pyproject.toml", "uv.lock", ".python-version"]]
    paths += [ROOT / "frontend" / name for name in ["package.json", "package-lock.json", "tsconfig.json", "vite.config.ts", "index.html", "playwright.config.ts", "tsconfig.e2e.json"]]
    manifest = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            if path.is_symlink():
                raise ValueError("Release source cannot contain links")
            raw = path.read_bytes()
            relative = path.relative_to(ROOT).as_posix()
            bundle.writestr(relative, raw)
            manifest.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
        bundle.writestr("release-manifest.json", json.dumps({"schema_version": 1, "kind": "application_source_and_built_ui", "files": manifest}, indent=2))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, nargs="?", default=ROOT / "dist/eu5-mod-engine.zip")
    print(build(parser.parse_args().destination))
