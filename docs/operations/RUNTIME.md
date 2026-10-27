# Windows runtime qualification

The selected deployment target is a Windows 11 VM. The app accepts any EU5 version, captures actual byte fingerprints, and does not infer runtime behavior from version display strings.

No actual EU5 runtime/conformance observation has been made during macOS development. All E01–E25 entries initially remain proposed/not-run. The driver and release recovery have synthetic/offline tests; those tests do not qualify your game or VM.

## Select a private installation

Run `python scripts/windows_probe.py --help` through the installed environment. The CLI supports read-only discovery, target configuration, controlled recipes and explicitly enabled launching. Use a disposable user-data/profile and preserve original playset state. Do not test against live mod files.

A target selection JSON identifies explicit paths:

```json
{
  "executable": "C:/Games/Steam/steamapps/common/Europa Universalis V/binaries/eu5.exe",
  "content_roots": ["C:/Games/Steam/steamapps/common/Europa Universalis V/game"],
  "docs_roots": ["C:/Users/YourName/Documents/Paradox Interactive/Europa Universalis V/docs"],
  "dlc_roots": [],
  "log_root": "C:/Users/YourName/Documents/Paradox Interactive/Europa Universalis V/logs",
  "version_display": "capture actual installed build"
}
```

These paths are illustrative. Use discovered known-folder/Steam locations and the actual selected executable; do not assume these filenames or directory locations. Configuration captures hashes of actual bytes and inventories. Missing docs/DLC are explicit inventories, not borrowed schemas.

The qualified protocol is baseline, A, B, A+B, B+A, and repaired A+B as separate cold starts where order matters. Confirm actual enabled content with sentinels and direct observations before/after runs and after crashes. Mounted availability and clean logs are insufficient.

## Record evidence

Recipes allow only known driver operations and bounded waits. The CLI requires explicit launch opt-in and a direct/manual observer; an unconfigured worker returns unrun/inconclusive status. Arbitrary shell commands and guessed headless/validator flags are unavailable. Hot reload is a distinct experiment scope.

Archive target fingerprints, settings/DLC/docs, exact mod bytes/order, source maps, raw logs, controls, screenshots/saves and actual assertions. Manual entries record their source and limitations; JSON that merely asserts success is not newly executed game evidence. The runtime adapter verifies fresh inputs and actual launch prerequisites before any run can support conformance.

Build/family/field-specific results enter the evidence registry only with required archived artifact hashes, controls, direct observations, scope and invalidation dependencies. Synthetic profiles cannot become C evidence. Contradictions quarantine affected rules; updated inputs invalidate dependent plans.

The app's production promotion API remains disabled in the shipped unmeasured profile. The journaled release module is exercised with synthetic conformance records only as an application contract. Enabling a real adapter still requires the relevant observations and complete preservation gates from the specification.
