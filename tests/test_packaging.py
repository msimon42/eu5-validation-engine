import hashlib
import json
import zipfile
from pathlib import Path

from scripts import package


def test_release_archive_contains_launcher_and_browser_test_dependency_closure(tmp_path, monkeypatch):
    source = tmp_path / "source"
    required = {"Start-EU5.cmd", "scripts/start.ps1", "pyproject.toml", "uv.lock", ".python-version",
                "README.md", "backend/cli.py", "backend/app/main.py", "frontend/dist/index.html",
                "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json",
                "frontend/vite.config.ts", "frontend/index.html", "frontend/src/main.tsx",
                "frontend/playwright.config.ts", "frontend/tsconfig.e2e.json", "scripts/test_e2e.py",
                "frontend/e2e/run.mjs", "frontend/e2e/server.py", "frontend/e2e/fixture_tool.py",
                "frontend/e2e/fixtures.ts", "frontend/e2e/workflow.spec.ts"}
    for name in required | {"frontend/node_modules/private", ".workspace/private", "backend/__pycache__/cache.pyc"}:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    monkeypatch.setattr(package, "ROOT", source)
    archive = package.build(tmp_path / "application.zip")
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert required <= names
        assert not any(set(Path(name).parts) & {"node_modules", ".workspace", ".tools", "__pycache__", ".git"}
                       for name in names)
        manifest = json.loads(bundle.read("release-manifest.json"))
        assert {item["path"] for item in manifest["files"]} == names - {"release-manifest.json"}
        for item in manifest["files"]:
            assert hashlib.sha256(bundle.read(item["path"])).hexdigest() == item["sha256"]
