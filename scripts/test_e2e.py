"""Prepare and run the real-browser suite with isolated temporary application state.

Run from the repository root: uv run python scripts/test_e2e.py [--headed]
First use installs locked frontend dependencies and a project-local Chromium.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> int:
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise SystemExit("Install Node 22.12+ (with npm), then rerun uv run python scripts/test_e2e.py.")
    npm_command = (npm,)
    if os.name == "nt":
        # Invoke JavaScript directly; npm.cmd otherwise depends on shell rules.
        npm_cli = next((base / "node_modules/npm/bin/npm-cli.js" for base in
                        (Path(npm).parent, Path(node).parent)
                        if (base / "node_modules/npm/bin/npm-cli.js").is_file()), None)
        if npm_cli is None:
            raise SystemExit("Cannot locate npm-cli.js beside npm.cmd. Install the standard Node distribution and retry.")
        npm_command = (node, str(npm_cli))
    version = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    major, minor = (int(value) for value in match.groups()[:2]) if match else (0, 0)
    if not (major == 20 and minor >= 19 or major == 22 and minor >= 12 or major > 22):
        raise SystemExit(f"Vite/Playwright need Node 20.19+ or 22.12+; this shell uses {version}. Select a supported Node runtime and rerun.")
    env = dict(os.environ)
    env.pop("OPENROUTER_API_KEY", None)
    env.pop("EU5_WORKSPACE", None)
    env["EU5_E2E_PYTHON"] = sys.executable  # Keep the venv path, not its resolved base interpreter.
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".cache/ms-playwright")
    env["npm_config_cache"] = str(ROOT / ".cache/npm")

    def run(*args):
        print("\n" + " ".join(str(arg) for arg in args), flush=True)
        subprocess.run(args, cwd=FRONTEND, env=env, check=True)

    lock_hash = hashlib.sha256((FRONTEND / "package-lock.json").read_bytes()).hexdigest()
    marker = FRONTEND / "node_modules/.eu5-e2e-lock"
    if not marker.exists() or marker.read_text().strip() != lock_hash:
        run(*npm_command, "ci", "--include=dev", "--no-audit", "--no-fund")
        marker.write_text(lock_hash)
    run(*npm_command, "run", "test:e2e:install")
    run(*npm_command, "run", "test:e2e:types")
    run(*npm_command, "run", "build")
    run(*npm_command, "run", "test:e2e", "--", *sys.argv[1:])
    print("\nReal-browser synthetic tests passed. No EU5/CK3 installation, VM, API key or game observation was used.")
    print("Report: frontend/playwright-report/index.html")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
