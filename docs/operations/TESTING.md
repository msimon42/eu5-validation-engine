# Testing the application without EU5

The synthetic browser lane runs on macOS before deployment to the Windows 11 VM. It tests the built UI, real FastAPI application, SQLite state, physical synthetic mod files, and downloaded export bytes. It needs no game installation or OpenRouter credentials. Passing results establish synthetic application contracts only; they do not establish EU5 loading or gameplay rules.

## One-command browser run

Install uv and Node 20.19+ or 22.12+ with npm. From the repository root:

```sh
uv run python scripts/test_e2e.py
```

uv supplies the pinned Python 3.12 runtime and locked backend dependencies. The runner installs frontend dependencies when the lockfile changes, installs Chromium into `.cache/ms-playwright`, checks browser-test types, builds the production UI, and runs Playwright. First setup needs internet access. Subsequent tests use only the local application; the test harness blocks external browser requests and removes OpenRouter credentials from the backend environment.

To watch the same tests:

```sh
uv run python scripts/test_e2e.py --headed
```

Other Playwright arguments are forwarded, for example:

```sh
uv run python scripts/test_e2e.py --headed --grep "malformed"
```

Each test materializes fixtures in an owned temporary folder, starts a backend with its own state directory and an OS-assigned loopback port, and removes that temporary state afterward. It does not use your `.workspace/`, game folders, or the preview server on port 8765. Requests reach the actual backend; there are no mocked API responses in this lane.

## Browser coverage

| Case | Assertions |
|---|---|
| F03 disjoint properties | Import physical sources through the UI; scan, investigate, stage, validate, download a ZIP; verify exact merged bytes, manifest hashes, persisted workspace and candidate after reload |
| F04 contradictory targets | No preselected choice; require an explicit explained decision; waive only the selected conflicting obligation |
| F13 malformed source | Preserve input bytes; block repair/export and produce no generated files |
| F18 incomplete preservation | Allow safe mechanical staging while an unknown obligation blocks export |
| Changed F03 source | An external edit after validation makes export fail as stale; preserve that edit and write no artifact |

All scenarios verify that no active release or playset configuration is written. Source hashes remain unchanged except for the deliberate external edit in the stale-source scenario. Fixtures use explicit synthetic profiles and author baselines; they cannot acquire conformance status or production promotion permission.

Open `frontend/playwright-report/index.html` after the run. Failed tests retain a trace, screenshot and backend log; generated downloads and screenshots are under `frontend/test-results/`. The successful F03 test also saves a screenshot and its inspected export ZIP. To use Playwright's report server:

```sh
cd frontend
npx playwright show-report
```

If setup rejects your Node version, check `node --version` in the same shell. Node 22.12+ is a straightforward supported choice. If Chromium installation fails, rerun with network access; the runner does not require a globally installed Chrome browser.

## Manual physical fixture workflow

After the browser runner has built the UI, materialize a case and start the app:

```sh
uv run eu5 materialize F03 .fixtures/F03
uv run eu5 serve
```

Open `http://127.0.0.1:8765`, create a workspace, select **Synthetic**, and paste the absolute `fixture_path` from the command output into **Synthetic fixture folder (optional)**. Choose **Capture & scan**, then investigate, stage, validate and export from the workbench. F04, F13 and F18 provide the other browser scenarios. Leaving the folder field empty uses the existing bundled in-memory cases instead.

`case.json` pins the synthetic profile, author baselines, owner roots, complete file inventory and exact source hashes. The backend reads the actual source files and refuses missing, extra, changed or unsafe paths. Treat the manifest and fixture sources as immutable. An existing populated destination is never overwritten; materialize a new folder to reset a case. `.fixtures/` is ignored by Git.

## Other checks and CI

The backend tests cover parser, engine, preservation, filesystem safety, application contracts and fixture materialization. The React integration tests use mocked API responses and complement the real-browser lane.

```sh
uv run --extra dev pytest
uv run --extra dev ruff check backend tests scripts
uv run python scripts/generate_contracts.py --check
uv run eu5 fixtures
```

Run frontend component tests separately:

```sh
cd frontend
npm test
```

For an already prepared frontend, the individual browser steps are `npm run test:e2e:install`, `npm run test:e2e:types`, `npm run build`, and `npm run test:e2e`. The test harness uses the repository `.venv` by default; `EU5_E2E_PYTHON` can explicitly select the Python interpreter.

GitHub Actions configures backend, component and browser checks on both macOS and Windows. It installs Chromium and uploads browser reports and test results for seven days when a job fails. That workflow is separate from running the launcher and EU5 in the user's VM. Current executed results and unrun Windows/game qualification are recorded in [implementation status](../IMPLEMENTATION_STATUS.md).
