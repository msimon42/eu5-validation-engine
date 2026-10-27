# Implementation status

27 October 2026. This is a working local implementation with an executable synthetic workflow. The complete research plan also includes Windows/game qualification that cannot be completed on this macOS host. **No EU5 conformance or universal compatibility is claimed.**

## Working application

- Local FastAPI service, React/TypeScript workbench, compact transactional SQLite state, installation session capability, origin/host checks, strict command payloads and actual request-body budgets.
- Immutable blobs, stable source inventory, streamed opaque assets, target Windows path policy, contained descriptor/native-handle reads, source/managed-root isolation and cross-process coordinator locks.
- Bounded lossless parser/CST, original serialization, malformed/encoding preservation, occurrence-aware edits, byte/code-point/UTF-16 positions, family front ends and bounded whole-document caching.
- Stage-aware file selection, explicit synthetic six-mode scheduling/readers, hidden-source provenance, typed graph projections, exact baseline-relative obligations, repeated/deleted contributions and symbolic unknowns.
- Deterministic synthetic repair staging, complete final-stack reanalysis, explicit design alternatives/waivers, current decision-set fingerprints, source/schema/parser invalidation and race-safe publication.
- Five UI screens, source/effective/staged views, snapshot history, jobs/cancellation/reconnection, bounded paginated detail reads, source previews, findings/obligation ledgers, independent gates and evidence inspection.
- Inactive ZIP review exports; journaled managed-release/rollback module with fault recovery and external-edit checks. The application does not expose unqualified game promotion.
- Complete runtime-state backup/restore with hash manifests, evidence/releases/journals/artifacts, no-overwrite restore, stale restored decisions/plans and required recovery for incomplete journals.
- Bounded OpenRouter executor, adversarial offline replay lane, model/provider/excerpt/budget settings and backend-only credentials. Model tools share local staging/validation boundaries; they cannot waive obligations or activate releases.
- Windows Steam/known-folder discovery, arbitrary-build byte fingerprinting, allowlisted runtime recipes, manual observation capture and raw log comparisons. Those adapters have offline contract tests, not executed Windows qualification.
- Windows 11 `Start-EU5.cmd`/PowerShell bootstrap with pinned checksum-verified local uv/Node, locked dependencies, UI build and browser launch. Source-and-built-UI ZIP packaging and a macOS/Windows CI definition.
- Physical synthetic fixture folders with immutable manifests, exact source hashes, safe materialization and disk-backed workspace scans. Changed, missing or additional source files invalidate the fixture contract.
- Playwright Chromium tests against the built UI and actual local backend, with isolated temporary databases, physical mod files, real HTTP requests, ZIP verification and retained failure diagnostics. One command prepares and runs this lane on macOS before VM deployment.

## Verification actually performed

| Check | Result |
|---|---|
| Python tests | **262 passed** on macOS/Python 3.12.16 |
| Executable fixture runner | **F01–F20 all pass** their declared synthetic expectations, including blocked/no-write outcomes |
| React integration tests | **7 passed**, including workflow, explicit choices, stale/outage handling, roots, inference privacy/configuration |
| TypeScript and production frontend build | Pass on Node 22.22.0 |
| Python lint | Pass |
| Generated request types/OpenAPI drift | Pass |
| npm production dependency audit | 0 reported vulnerabilities at this check |
| Release ZIP | Built locally; dependency closure/hash-manifest regression covered |
| Windows bootstrap download checksums | Official uv x64/ARM64 and Node x64/ARM64 checksum URLs verified; script itself not run on Windows |
| Automated browser E2E | **5 passed** on macOS/Chromium headless and headed, including the one-command setup runner: disk inputs through actual UI/backend to ZIP, explicit conflict choice, malformed input, unknown preservation obligation, and stale-source export rejection |
| Manual browser verification | Local scan, provenance/source display, staging, independent validation and experimental export workflow exercised |
| Benchmark | Measured the small F01–F20 corpus only; no full-installation performance target or claim |
| Original specification package | Preserved; implementation does not change supplied specification/source assets |

The Python test run emits one FastAPI/Starlette test-client deprecation warning about its HTTP transport adapter. It does not affect passing results. No game log warning allowlist is inferred from this tooling warning.

The seven React tests use mocked API responses; the five Playwright tests run the actual application without API mocks. Browser tests preserve source hashes, leave active-playset/release files absent, and reject external network access. These are synthetic application contracts, not executed EU5 evidence. CI is configured to run this browser lane on macOS and Windows; Windows execution has not been performed in this session.

## Qualification and remaining scope

| Plan area | Current boundary / required next evidence |
|---|---|
| M0 / W00 Windows 11 VM feasibility | Launcher and app must actually run in the selected VM; initialize the actual EU5 installation and archive baseline milestones. No VM is connected in this session |
| W01 discovery/playset/NTFS qualification | Native adapter code exists. Confirm known-folder/Steam paths, aliases/reparse behavior and actual active content/order on the selected Windows environment |
| W02 runtime driver qualification | Controlled recipes and observation capture exist. Qualify actual commands, cold starts, stage coverage, crash-driven disabling, direct sentinels and log grammar |
| W03 / E01–E25 conformance | **All experiments remain proposed/not-run. Zero C rules are shipped.** Measure each relevant build/stage/family/field before enabling its production capability |
| W04 game-directed repair/activation | Disabled. Requires current measured loading/readers, complete behavior obligations and a qualified activation method. Playset writers remain unavailable until persistence is conformed |
| Installed script-doc formats / language semantics | A versioned structured importer and opaque preservation path exist. Actual dump-format adapters, exhaustive type/scope/macros/runtime arithmetic semantics need the selected installation and qualification; unknowns stay explicit |
| Full managed-copy/playset repair strategies | Synthetic full-file composition is implemented. Real-game strategies and metadata/writer policies depend on measured family/activation behavior |
| Broader family production coverage | Metadata/localization/GUI syntax and synthetic composition are exercised; events/on-actions/setup/maps/assets remain outside automatic real-game composition until their own experiments pass |
| Live OpenRouter | Executor, policy UI and mock/replay contracts are implemented. No live provider request, key/spend, or endpoint evaluation was used during development |
| Release/deployment operations | Local package/backup/recovery checks pass. Windows installation/upgrade, actual filesystem interference and whole-stack runtime acceptance remain unrun |
| GitHub hosting | Source repository: [msimon42/eu5-validation-engine](https://github.com/msimon42/eu5-validation-engine). GitHub Actions is configured for macOS and Windows checks |

“Any EU5 version” means the app accepts and fingerprints arbitrary installations and keeps unsupported behavior visible. It does not mean one unmeasured loader assumption is applied to every release. Static analysis and experimental review can be useful before game conformance; validated game repairs remain gated.

## Run and continue

Use `uv run python scripts/test_e2e.py` for the complete synthetic browser lane on macOS, or add `--headed` to watch it. See [testing operations](operations/TESTING.md) for physical fixture imports, reports and individual checks. For a macOS preview, build the frontend and run `uv run eu5 serve`, then open [the local app](http://127.0.0.1:8765). The [Windows quick start](../README.md#windows-11-clone-and-launch) remains the VM entry point.

The next external qualification is W00 in the user's Windows 11 VM, then active-playset/driver qualification and a narrowly selected W03 campaign. The [implementation plan](IMPLEMENTATION_PLAN.md) remains the complete roadmap; this ledger distinguishes implemented software from experiments and production capabilities still requiring evidence.
