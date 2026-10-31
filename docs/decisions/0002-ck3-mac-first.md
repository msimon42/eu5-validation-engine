# CK3 game adapter and Mac-first inspection

28 October 2026. Accepted by the user's CK3 implementation request.

The workbench supports a second explicit game identity, `ck3`, with macOS as its
primary host and Windows as a supported inspection target. Steam installations,
Workshop payloads and local mods are the first discovery sources. EU5 retains
its existing Windows target and synthetic contracts. This decision changes no
requirements or source material under `specs/`.

Shared infrastructure owns immutable snapshots, managed writes, jobs, source
preconditions and display projections. Game adapters own file classification,
analysis, package metadata, writer policies and runtime capabilities. Workspace,
scan, profile, evidence and release scope includes game and target platform.
Legacy workspaces migrate to `eu5`/`windows`; historical evidence retains that
interpretation. An observation for one game/platform cannot authorize another.

CK3's root-relative families are independent of EU5's three resource stages and
six operation prefixes. The initial adapter inspects all captured contributions
and keeps effective selection and preservation unknown. Overlaps, definition
identities, dependencies and schema deviations are investigation findings;
none select a winner or authorize a semantic merge.

The 24 user-supplied CK3 JSON files remain byte-for-byte unchanged. Their custom
format is imported as advisory vocabulary. `_manifest.json` records original
hashes and explicit overlays derived from inspected shipped documentation. The
inspected launcher settings declared 1.19.0.4; this is source inspection, not
executed conformance or a compatibility guarantee for that or another build.

Discovery never opens source SQLite for mutation: it captures bounded database
and WAL bytes, queries a private replica, and checks source hashes again. Missing
payloads are inspectable incomplete coverage. Temporally inconsistent captures
cannot be imported. Launcher state and descriptors are preserved in managed
blobs separately from payload snapshots. Sources and managed roots cannot overlap.

CK3 automatic repairs, runtime execution, playset writes and validated promotion
remain unavailable. The inactive writer can assemble exact reviewed generated
bytes and fresh CK3 descriptors; it does not establish a transformation's
eligibility. Production requires scoped archived observations, complete
preservation, current source preconditions and separately qualified activation.
