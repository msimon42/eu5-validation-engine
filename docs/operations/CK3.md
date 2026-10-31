# CK3 playset inspection

The primary interface is now [the Codex assistant](AGENT.md). Ask it to check your
current playset and discuss proposed changes. The dashboard instructions below
describe the optional developer interface. Game testing and activation remain
gated; inactive preparation is not a completed game fix.

Create a workspace, choose **Crusader Kings III**, **Game**, and **macOS** or
**Windows**. Choose **Discover CK3** on the overview, review the discovered
installation, saved playsets and diagnostics, then **Import for inspection**.
Capture a scan to preserve immutable bytes and investigate the selected sources.
Changing the saved playset or location overrides requires rediscovery before import.

The first implementation supports Steam library discovery, local `.mod` registry
files and Steam Workshop payloads for app ID `1158310`. Other stores can be
inspected through explicit installation and mod-root selections; automatic
non-Steam service discovery is not implemented. Archive payloads remain visible
as unsupported sources; they are not extracted into original directories.

## Locations and source identity

macOS normally uses `~/Documents/Paradox Interactive/Crusader Kings III` for user
data and `~/Library/Application Support/Steam` for Steam. The installed launcher
settings supply the game-data and executable locations. Vanilla content is the
installation's `game/` directory, separate from `binaries/ck3.app`.

Windows resolves Steam roots through the native adapter and Documents through
the Known Folder API. All Steam libraries are considered. Select explicit roots
when defaults are unavailable, Documents is redirected, or a library is offline.
Location fields expect paths on the computer running the local backend.

An external descriptor can point outside known local/Workshop roots only through
an explicit mod-root override keyed by its registry path, for example
`mod/ugc_123.mod | /absolute/path/to/payload`. The original path is never rewritten.
Payload owner IDs remain distinct from Workshop IDs, launcher IDs and filenames.

Saved playset order comes from the launcher database's enabled rows and positions.
For the active selection it is compared with `dlc_load.json`. JSON-only last-launch
selections are labeled accordingly. This is serialized-state inspection; it is
not proof of the contents actually loaded by the game. Missing payloads remain
diagnostics even when the launcher says `ready_to_play`. An incomplete selection
can register readable roots for investigation; a changing metadata capture cannot.

Import preserves launcher, Steam and descriptor metadata in managed blobs. Scans
capture selected payload bytes, including opaque files. Later metadata or source
changes invalidate reuse. Large captures require space for complete immutable
copies and can be cancelled at safe boundaries. Discovery alone does not copy
the full installation.

Text inspection has a 120 MB budget. Descriptors and primary script/event/GUI
families are prioritized, with mods before base content within each tier. Lower
priority text remains preserved as opaque bytes with an explicit capture reason;
the coverage record lists deferred files by source. This inspection priority
does not change playset order or establish game loading precedence.

Repeated scans reuse a stored blob only after hashing the complete current source
and verifying the complete stored blob. Derived records store occurrence coordinates
and reconstruction references instead of duplicating full nested syntax trees.
The original bytes, parser version, spans and occurrence ordinals remain the
authority for reconstructing the ordered CST. No definitions or preservation
obligations are removed to fit the display/storage projection.

## Analysis and schema coverage

CK3 classification recognizes descriptors, nested events, precise `common/`
families, localization, GUI and symbolic history/reader resources. Script keeps
ordered occurrences, comments, malformed regions and exact bytes. Unknown assets
remain opaque. POSIX source spellings are retained; Windows portability hazards
are findings rather than reasons to rename originals.

The schemas are a custom advisory format, not JSON Schema for serialized CK3
files. `schemas/ck3/_manifest.json` pins the original 24 hashes and separately
records corrected family paths, optional legacy trait indexes, dynamic description
forms, trait localization defaults, religion nesting limits and on-action fallback
shape. Unknown fields remain preserved. Generic blocks, nested entity schemas,
dynamic references, effects/scopes, DLC/library overlays and exhaustive gameplay
meaning remain incompletely modeled. A schema warning does not certify invalid
game content; a clean schema result does not certify compatibility.

The investigation view shows overlapping paths, duplicate identities, declared
dependencies, masks and limited literal-reference diagnostics with source
provenance. Hidden/disabled captured sources stay inspectable. Effective winners,
callback composition, loading phases and gameplay preservation remain unknown.

## Capability boundary and qualification

Repair, decision-waiver and release controls are disabled for CK3 in the UI and
enforced in the backend. EU5 fixture IDs/profiles cannot be used in a CK3 scan.
The existing EU5 runtime worker cannot launch CK3. CK3 runtime requests return
`not_run`; no game or launcher is started.

The CK3 writer module assembles inactive review files from exact generated bytes:
a fresh mod folder, `descriptor.mod`, sibling `.mod` and placement instructions.
It requires an explicit selected version, strips source identity metadata by
construction, and checks portable output paths and hashes. It is a packaging
primitive for future eligible transformations, not an enabled automatic repair.

CK3 has its own proposed experiment catalog. Production evidence must identify
the exact game, platform, executable/content/docs/DLC fingerprints, family and
field scope, negative control, active state and archived direct observations.
Mac observations do not authorize Windows. No CK3 conformance rules ship.

All automated CK3 cases use synthetic temporary roots. Windows discovery fixtures
can run on macOS; that does not qualify native Windows APIs or a real CK3 loader.
Real-game qualification still requires disposable profiles and explicit runtime
work. The authorized read-only macOS installation/playset inspection is recorded
in the [implementation status](../IMPLEMENTATION_STATUS.md). No CK3 runtime or
gameplay conformance tests were performed during this implementation.

Primary research references: [Paradox Mac file locations](https://forum.paradoxplaza.com/forum/threads/wrong-checksum-after-reinstallin-and-restat-of-machine-ck3.1601157/#post-29165771),
[Playset Preserver's original implementation](https://github.com/nullheimer/CK3-Playset-Preserver),
[CWTools CK3 rules](https://github.com/cwtools/cwtools-ck3-config), and
[Tiger](https://github.com/amtep/tiger). External tool rules are comparison sources;
none substitute for this project's scoped conformance and preservation gates.
