# Documentation package checks

Performed for revision 2.0 on 26 October 2026. These are checks of the documentation and its assets, not implementation or EU5 validation.

| Check | Result |
|---|---|
| Requested seven core Markdown files plus index | Present |
| Markdown file-target links | All checked relative targets exist; heading-fragment behavior is not certified |
| Fenced code blocks | Balanced in all 15 Markdown files |
| Fenced JSON examples | Seven parse as JSON |
| Bundled fixture JSON | Both parse; all three input base64 payloads decode strictly |
| Fixture 003 versus supplied schema | Matches the keyword subset used by this schema: type, const, enum, required, properties, additionalProperties and items |
| Schema-validator limitation | Full draft-2020-12 validator was unavailable; no standards-wide schema-validation claim |
| Source provenance | Exact uploaded bytes and all four hashes in SOURCES.md verified |
| Portable research copy | Substantive text unchanged; exactly two companion-link destinations substituted |
| Test and experiment catalogue | F01–F20 and E01–E25 present |
| Frontend assets | Five SVGs parse as XML; five 1440×980 PNG previews and one overview render generated |
| Visual review | All five screens inspected together for clipping, layout and evidence/decision/gate labels; overview playset corrected to match its findings |
| Consistency review | Independent reviews of evidence, preservation, export eligibility, concurrency, fixtures and retained requirements; identified issues corrected |
| Integrity manifest | MANIFEST.json lists hashes/sizes for packaged files excluding itself |

The ZIP is checked for CRC integrity, contained relative paths and byte equality with the packaged directory after creation. External URLs are cited as source references; most are inherited from the supplied report, and universal availability or current page content is not claimed. See [SOURCES.md](SOURCES.md) for direct retrieval checks and source limitations.

No application build, synthetic fixture runner, provider integration, Windows VM game-feasibility trial, EU5 launch or actual-game conformance experiment was run. All displayed wireframe statuses are synthetic. All E-series experiments remain proposed/not-run. Future implementers must execute the required test matrix rather than treating this package check as a passing application result.
