# EU5 Mod Engine

A local engine for inspecting mod collections, preserving their original files,
and preparing reviewed changes. **For CK3, the conversation in Codex is the
interface.** Ask it to check your mods, explain overlapping changes, and walk
through a small group of choices. No dashboard or separate AI account is needed.

One-time setup from this checkout, with Codex and uv installed:

```sh
uv sync --extra dev
uv run mod-engine install-agent --data-dir .workspace/ck3
```

Reconnect local tools or reopen Codex after setup. Then say “Check my current CK3
playset.” The assistant starts its local engine as needed and remembers progress.
Say “Continue reviewing my mods” to resume the previous investigation. It now
receives a current briefing and can search a sourced CK3 reference library and
related scripts without requiring you to supply internal IDs or past messages.
This path does not require Node or a browser. See [agent setup and current
limits](docs/operations/AGENT.md).

CK3 inspection supports macOS and Windows source layouts. Approved changes can
currently be prepared in a separate, inactive fixes mod for the call-allies
action. Actual game testing and normal-playset activation remain unavailable
until their separate checks are established; this is **not yet the complete
fix/test/enable release**. The existing EU5 workbench and optional developer
dashboard remain available below.

## Test on macOS before using the VM

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node **20.19+ or 22.12+** with npm, then run from the repository root:

```sh
uv run python scripts/test_e2e.py
# To watch Chromium perform the same tests:
uv run python scripts/test_e2e.py --headed
```

uv supplies the pinned Python 3.12 runtime. On first use, the runner installs locked frontend dependencies and Chromium into the project cache, builds the UI, and starts the actual application for each test. No EU5 installation, Windows VM, OpenRouter account, or API key is needed.

The six browser tests read physical synthetic files and exercise EU5 repair/export, explicit conflict decisions, malformed input, unknown preservation obligations, stale-source rejection, and CK3 discovery/import/inspection. They use real HTTP requests and SQLite state, check output and original byte hashes, and verify that no playset is activated. Each test gets temporary state and a separate local port, so an existing preview can stay open. **All six passed on macOS.** GitHub Actions is configured to run the suite on macOS and Windows; native Windows and game checks remain separate.

Open `frontend/playwright-report/index.html` after a run. Failure reports include screenshots, traces, and backend logs. See [testing operations](docs/operations/TESTING.md) for coverage and debugging commands.

## Windows 11: clone and launch

1. Clone [this repository](https://github.com/msimon42/eu5-validation-engine) into a writable local folder in the VM.
2. Double-click **`Start-EU5.cmd`**.
3. The first launch downloads checksum-verified, pinned local tools, installs locked dependencies, builds the UI, and opens **http://127.0.0.1:8765**.

No administrator access, preinstalled Python/Node, global PATH change, or global PowerShell execution-policy change is required. First setup needs internet; installed deterministic analysis runs locally. Keep the console open while using the app; press Ctrl+C to stop. App state is in `.workspace/`, separate from game/mod content. Do not put live SQLite state on a VM shared/network folder unless that filesystem has been qualified.

Alternatively, from PowerShell:

```powershell
.\Start-EU5.cmd
# Optional arguments:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Port 8766 -NoBrowser
```

The launcher supports x64 and ARM64 Windows tool downloads. **Actual Windows launcher and EU5 VM execution have not been performed in this macOS development session.** The CI workflow includes Windows contract checks; that is separate from game feasibility in your particular VM.

## Start with a working synthetic case

Choose **Scan playset → Disjoint properties**. The baseline has `x=1,y=1`; A changes x to 2, B changes y to 3. Investigation shows why the original stack loses A's change. **Stage proposal → Validate full playset → Export experimental bundle** produces the combined `x=2,y=3` review artifact.

Other executable cases cover contradictory values, repeated commands, missing references, malformed input, Windows path hazards, invalid proposals, stale sources, and opaque assets. Design choices are never preselected. Unknown/unwaived obligations block readiness. Experimental export never activates a playset or release pointer.

To try the same physical input path manually after building the UI:

```sh
uv run eu5 materialize F03 .fixtures/F03
uv run eu5 serve
```

Create a workspace, choose **Synthetic**, and paste the printed absolute `fixture_path` into **Synthetic fixture folder (optional)**. Capture and scan reads the actual files under that folder. The materializer accepts only a new or empty destination; it never overwrites source files. Changing a file after capture makes the workspace stale. Materialize a fresh folder to start another pristine case.

For private game content, create a **Game** workspace and register explicit read-only source roots and owner IDs. Use each mod's root (containing resource stages and `.metadata`) and vanilla's `game` root. Run against a disposable profile for eventual runtime experiments. Originals are never the application's write target.

## Any EU5 version

The app has no EU5 version whitelist. Inventory and byte preservation accept arbitrary installed builds. The Windows adapter discovers Steam libraries/Workshop/known-folder sources and captures the actual executable, content, documentation, and DLC fingerprints; historical version labels are never treated as your installation.

Loading and gameplay rules can change between versions and families. Current real-game predictions remain conditional/unknown, and **zero conformed production rules are shipped**. Safe game-directed automatic promotion stays disabled until relevant scoped observations exist. The implemented synthetic profiles are explicit application contracts, not proof of EU5 behavior. Unknown files remain preserved and visible.

Windows probe scaffolding accepts an explicitly selected installation of any version:

```powershell
uv run python scripts/windows_probe.py --help
```

When using the one-click install's project-local tools, substitute `.tools\uv\uv.exe` for `uv`. See [runtime operations](docs/operations/RUNTIME.md) for target selection, controlled recipes, and manual observation limits.

## macOS development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and a supported [Node runtime](https://vite.dev/guide/), then:

```sh
uv sync --frozen --extra dev
cd frontend
npm ci
npm run build
cd ..
uv run eu5 serve
```

Open [the local workbench](http://127.0.0.1:8765). For frontend hot reload, run `npm run dev` in `frontend/` alongside the backend; Vite proxies `/api` to port 8765.

```sh
uv run --extra dev pytest
uv run --extra dev ruff check backend tests scripts
uv run python scripts/generate_contracts.py --check
uv run eu5 fixtures
uv run eu5 scan F03
cd frontend && npm test
```

The repository locks Python dependencies in `uv.lock` and frontend dependencies in `frontend/package-lock.json`. The HTTP interface uses one strict command endpoint and bounded read projections; commands are introduced with their workflows. Transport request types and schemas are generated from Python definitions.

## State, backup, and release artifacts

`.workspace/` contains the local SQLite index, immutable blobs, snapshots, evidence, jobs, staging/release journals, and exported review artifacts. SQLite stores metadata/relationships/jobs; original bytes remain in managed content-addressed files. Back up consistently:

```sh
uv run eu5 backup /absolute/path/to/new-backup-folder
uv run eu5 restore /absolute/path/to/backup /absolute/path/to/new-managed-folder
```

Backups contain a consistent database, immutable blobs, evidence, journals, managed releases, artifacts, and a hash manifest. Restore verifies all hashes and accepts only a new/empty target. Restored decisions/candidates are marked stale; incomplete journals require recovery, and no playset is activated. Start the restored copy with `eu5 serve --data-dir PATH`; preserve the original state until the restored copy is verified. Session capabilities and lock files are regenerated.

Build a source-and-compiled-UI transfer archive after the frontend build:

```sh
uv run python scripts/package.py
```

The implementation/release boundaries and work remaining are recorded in [implementation status](docs/IMPLEMENTATION_STATUS.md). The full governing design remains in [specs](specs/README.md); [implementation plan](docs/IMPLEMENTATION_PLAN.md) retains the original work breakdown.
