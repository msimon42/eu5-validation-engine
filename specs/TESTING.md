# Testing and validation specification

Status: proposed implementation contract (**P**). Research cutoff: 26 October 2026. No EU5 runtime experiments or repository test suites were executed by the supplied investigation, and this documentation update does not claim any new passing game tests. Evidence labels follow [the index](README.md); **D** means documented behavior, not observed executable behavior. Build-scoped conformance is required before a production repair rule can be trusted.

Related: [product requirements](SPEC.md), [architecture](ARCHITECTURE.md), [script/CST requirements](EU5_SCRIPTING.md), [loader profiles](EU5_LOADING_SEMANTICS.md), [experiment backlog](RESEARCH_GAPS.md), and the supplied [research report](RESEARCH_REPORT.md), sections 7–8 and 10.

## 1. Two fixture tiers

**Contract fixtures** use EU5-shaped files with an explicitly synthetic reader and loader. They test the application's stated behavior without EU5. The fixture fields `x`, `y`, `nested`, `items`, `effect`, and directory `common/testdb` do not claim to be accepted EU5 content. **Conformance fixtures** materialize a valid seed from the user's selected installation, change one controlled axis, and compare a concrete game observation with a prediction. They share a runner format, but only conformance has executable/content/DLC fingerprints and measured observations.

Never promote a synthetic test expectation into an EU5 rule. Public mod examples supply grammar regressions, not proof that their attempted runtime semantics work. Keep proprietary seed bytes and derived game corpora private; the repository contains recipes and hashes rather than redistributed vanilla files.

```text
tests/
  profiles/synthetic-contract-v1.json
  profiles/eu5-observed/<fingerprint>.json
  fixtures/contract/<case>/case.json
  fixtures/conformance/<experiment>/
    seed-recipe.json
    probe-recipe.json
    observations/<fingerprint>/result.json
  agent-replays/<case>/{requests,responses,tool-results}.jsonl
  golden/
  property/
  integration/
  runtime/
```

Each fixture supplies exact byte inputs, owner identities, virtual paths, playset order, profile/version, parse diagnostics, expected findings, effective output, patch bytes or explicit no-patch result, and preservation assertions. Store pathological paths and invalid bytes in manifests rather than creating them on disk. A materializer validates paths before writing; an unsafe-path test must never create the unsafe file to discover that it is unsafe.

The included [fixture schema](fixtures/fixture-schema.json) and [fixture 003](fixtures/fixture-003-disjoint-properties.json) are copied from the research companions. They are illustrative v1 artifacts, not an implemented test runner or game-valid patch. The schema is intentionally minimal: production must add versioned diagnostic/assertion definitions, strict base64 validation, complete hashes, baseline/field-independence prerequisites for automatic planning, explicit disposition, and a conformance fingerprint requirement. Add schema fields through a new schema revision; do not silently append fields rejected by `additionalProperties: false`.

`expected.effective_before_patch` is the unrepaired result. `expected.effective` is the post-patch result when a patch exists. Simulate the original stack first, then add generated patch files and simulate again. The example playset includes a reserved `generated_patch` slot, which supplies no source content during the first pass. `patch: null` explicitly requires no generated repair. The runner records a disposition separately: `no_repair_needed`, `blocked_unknown`, `blocked_design`, `invalid_input`, or `repair_expected`; absence of output must not imply success.

## 2. Synthetic contract v1

The following rules are test choices (**P**), not claims about EU5:

- Bare creation runs first; a second bare definition of the same identity is diagnosed and rejected.
- Prefixed operations then run in this sequence: `INJECT_OR_CREATE`, `REPLACE_OR_CREATE`, `TRY_INJECT`, `TRY_REPLACE`, `INJECT`, `REPLACE`.
- Exact-path shadowing selects the later entry in the supplied playset before operation interpretation. Traverse surviving files with explicit ASCII parent-before-child ordering and retain source occurrence order within a file.
- `INJECT` appends top-level CST entries. A replacement supplies the complete body. The selected field reader then interprets repeated entries; injection does not recursively merge them.
- Synthetic `x`/`y` use last scalar occurrence; `effect` is ordered; `items` is appendable. `nested` is map-like only in fixtures that explicitly select that reader. An unknown-reader variant remains symbolic.
- Strict modes on absent targets diagnose an error; `TRY_` modes do nothing; `_OR_CREATE` modes create. These concrete no-op/error expectations belong to this contract even where real-game details remain unmeasured.

The real-game six-mode meanings have official documentation (**D**); the synthetic schedule and duplicate rules above are independently declared test behavior. [Official modding diary](https://forum.paradoxplaza.com/forum/developer-diary/tinto-talks-85-22nd-of-october-modding.1864004/).

## 3. First twenty fixture families

In this table `D/` abbreviates `in_game/common/testdb/`; V is the synthetic baseline and A/B are mods. All shown text ends in LF unless a byte variant says otherwise. Every case asserts source bytes are unchanged. Unknown-reader, missing-ancestry, and ambiguous-alignment variants are required negative tests.

| ID | Exact meaningful inputs / variants | Required outcome and preservation checks |
|---|---|---|
| F01 Independent mods | A `D/10_a.txt`: `alpha = { x = 1 }`; B `D/20_b.txt`: `beta = { y = 2 }`. | Parse both, byte-exact round trip, no conflict or patch; alpha.x=1 and beta.y=2 in either playset permutation; zero LLM calls. |
| F02 Identical overrides | V `item = { x = 1 y = 1 }`; A/B in distinct files both `REPLACE:item = { x = 2 y = 1 }`. | `compatible_overlap`, effective x=2,y=1; no patch. Retain both owners, occurrences, comments and redundant contributions; do not delete either mod's content. |
| F03 Disjoint fields | Same V; A replaces x=2,y=1; B replaces x=1,y=3. | Before repair x=1,y=3. With pinned common ancestor and known independent fields, emit `REPLACE:item = { x = 2 y = 3 }` and preserve both deltas. Without either prerequisite: `potential_incompatibility`, no automatic write. See included JSON fixture. |
| F04 Contradictory values | Same V; A replaces x=2,y=1; B replaces x=5,y=1. | `confirmed_incompatibility` for simultaneous exact-value obligations. No write before a concrete user design choice. Approved x=5 emits x=5,y=1 and records A's exact-value waiver. Never average to 3.5 or sum to 7. |
| F05 Nested collision | V `item = { nested = { a = 1 b = 1 } }`; A `REPLACE_OR_CREATE:item = { nested = { a = 2 b = 1 } }`; B `INJECT:item = { nested = { b = 3 } }`. | Preserve repeated nested blocks. Unknown reader: symbolic result, potential incompatibility, no write. Known synthetic map reader plus approved combined intent: full replacement a=2,b=3. Separate A=`REPLACE` variant must erase B before reading and yield a=2,b=1; never assume recursive injection. |
| F06 Repeated keys / effects | V `item = { effect = { add = 1 multiply = 2 add = 3 } }`; A changes first add to4; B last add to5. | Distinguish occurrence0/1. Proven sequence alignment yields add4,multiply2,add5, giving13 from initial0. Preserve command order and comments. Ambiguous repeated occurrences block automatic edits. |
| F07 Modes / absent target / duplicate create | Each of six prefixes with `{ y = 2 }`, target present/absent; duplicate bare `item` in one file and across files. | Check every append/replacement/error/no-op/create result and provenance. Duplicate create uses explicit reject-second contract. Only top-level recognized family directives become operations; retain reference colons. Production equivalents need real verified-database probes. |
| F08 Loading axes | Distinct V seed. (a) A/B both `D/00.txt`, different replacements. (b) A `D/zz.txt` injects y2; B `D/00b.txt` replaces x3. (c) two replacements in distinct filenames. | Select exact-path survivor first; hidden sources remain available for intent. (a) Winner changes with playset. (b) replacement erases injection despite filename. (c) within-mode filename order decides under this contract. Store per-profile/permutation predictions; swapping names is a separate axis. Reordering alone is not preservation. |
| F09 References | V file has `helper={x=1}` and `item={ref=helper}`; A shadows that file with only item; B adds `second={ref=helper}`. Dynamic variant `ref="$computed$"`. | Schema-declared literal reference is missing at both use sites; transitive graph includes B. Dynamic target is unresolved, not a proven missing helper. No invented helper; restore only a verified original when authorized and validate its dependencies. |
| F10 Package dependencies | Required C absent/disabled; duplicate metadata ids; A requires B and B requires A; mismatched versions. | Distinguish installed/enabled/identity/version/order. A required-presence/version contract can be unsatisfied; advisory version mismatch warns. Presence-only cycle is potential/cyclic, not automatically impossible. Only verified strict-order cycles prove contradiction. No invented package or silent reorder. |
| F11 Localization | A/B ordinary `main_menu/localization/english/*_l_english.yml`: `l_english:` then `item_name:0 "Alpha"` / `"Beta"`; replace-folder, same-path and wrong-header variants. | Dedicated parser preserves language,key,version,text/spans and `#` inside text. Competing exact labels need user choice. Predicted winner only under selected profile. Approved text emitted in a verified path/encoding; retain other keys/languages. Separate ordinary/replace and replace/replace priority tests. |
| F12 GUI | Same `in_game/gui/test.gui`: V has foo/bar; A changes foo; B changes bar from an old copy. Separate-file duplicate `type foo = default_block_window { name = "a/b" }`. | GUI grammar retains named heads, groups, templates, bindings, widget order and constants. Whole-file shadow can lose unrelated bar; cross-file symbol precedence remains GUI-specific. Full-file composition only with known disjoint baseline changes and all widgets retained; otherwise no write. |
| F13 Malformed syntax | Unclosed `item = { x = 1`; valid `item = { text = "a # }" x = 2 }`; unterminated string; stray brace. | Bounded recovery, accurate diagnostics/spans and exact raw round trip. Valid string delimiters do not change nesting. No semantic rewrite across error regions. Narrowly authorized brace fix emits `item = { x = 1 }` plus LF and strict reparses. |
| F14 Encodings / positions | UTF-8 BOM/no-BOM, LF/CRLF/mixed; UTF-16LE BOM; byte0xFF; legacy accented bytes; non-ASCII prefix before edit. | Preserve raw bytes, codec/BOM/newline diagnostics, distinct byte/character/UTF-16 offsets. Eligibility uses family profile. Unknown conversion blocks; approved conversion has exact expected bytes. No replacement U+FFFD, implicit Unicode normalization or escape rewriting. |
| F15 Windows aliases | Manifest Foo.txt/foo.txt, trailing dot/space, reserved names, composed/decomposed Unicode. | Analyze without illegal materialization. Target-policy aliases produce portability findings on both hosts; real NTFS checks calibrate policy. Unicode variants are review risks unless aliasing is measured. No blind rename of potentially semantic filenames/references. |
| F16 Unsafe paths / links | `../outside.txt`, absolute, drive, UNC/device, ADS colon, both separators, archive traversal, external symlink/junction. | Reject before reading/writing unsafe targets. Outside sentinel unchanged and staging empty. Test opened-handle containment/no-follow traversal or controlled link-free staging; repeat string checks alone do not defeat races. Comments cannot authorize outside-root writes. |
| F17 Invalid agent output | Mock malformed script/JSON, unknown field, wrong scope/id, unsupported tool, extra deletion, valid syntax suppressing B. | Local schema, strict parse, scope/reference, write-set and preservation gates reject promotion. Incomplete schema means unknown, not validated. Originals unchanged; tool ids/budgets checked; failures returned to agent; model's success claim cannot bypass a gate. |
| F18 Unrelated contributions | V file has item/other; A changes item.x, other.y, comments and an unknown parseable field; B changes item.y. | Merge known independent item deltas only; preserve other and unknown content. If exact-file output is required, retain effective unrelated definitions. Byte equality outside allowed spans; every contribution is preserved, explicitly waived, or unresolved. No cleanup deletion. |
| F19 Update / stale plan | Repair pins V0/A0/B0; A1 changes target/helper. Also irrelevant thumbnail-only, game/profile update, and update between validate/export. | Read-set/helper/profile changes invalidate plan and approval. Irrelevant thumbnail may retain validity only with bounded dependency proof. Rebase pins new hashes. Concurrent change fails promotion precondition. Rollback restores exact earlier managed bytes/playset without overwriting later external edits. |
| F20 Assets / runtime meaning | Same texture path with equal/different binary hashes and text refs; two valid hooks independently double one reward. | Hash opaque assets; do not parse DDS/mesh as script. Equal asset needs no repair; differing assets require explicit choice or format-aware composition. Valid reward scripts remain `semantic_gameplay_conflict` until behavior assertions prove duplication is unwanted. No silent deduplication; test dimensions/format where supported and observe hook counts/values. |

The categories above must carry evidence and coverage. A contract's `confirmed_incompatibility` concerns its declared obligations, not a claim that unobserved EU5 gameplay is broken. Expand F07 into all mode/presence pairs and F08 into path, filename, traversal, playset, stage and operation combinations. Each matrix row requires golden parse/findings/effective/provenance/output and no-write assertions; a row label alone is not a test.

## 4. macOS development suite

No game installation is required for contract testing. Run parser/lexer and reference units, golden fixtures, bounded property tests, agent replays, and FastAPI/SQLite/React integration against temporary workspaces. Never run automated tests against the user's live mod directories. Use per-test roots; [pytest documents `tmp_path`](https://docs.pytest.org/en/stable/how-to/tmp_path.html) for this purpose.

Goldens pin token/CST summaries, raw output bytes, diagnostics, duplicate order, provenance, obligations, effective values and displayed explanations. Normalize only transient run ids and temporary host roots. Golden updates require a reviewed explanation; do not normalize away a changed winner, BOM, source owner, repeated key or span.

Property tests generate repeated keys, mixed blocks, operator adjacency, quotes/backslashes/comment characters, Unicode, trivia, bounded nesting and malformed truncations. Assert termination; exact no-op bytes even for malformed input; deterministic parse/serialize; contained spans; no lost occurrences; surgical edit locality; strict parse after accepted edit. Shrink failures into regressions. Whitespace/comment insertion can be a semantic invariant only where allowed; reordering commands, folding numeric spelling, or normalizing identifiers is not a general invariant.

Use stateful action sequences for scan → update → plan → validate → concurrent update → export → rollback. Assert no stale publication and no partial state. [Hypothesis stateful tests](https://hypothesis.readthedocs.io/en/latest/stateful.html) provide a suitable action-generation model. Differential parsers compare a neutral projection of raw scalars/operators/occurrence order within mutual coverage. Disagreement is a triage case, not a majority vote; a second parser is not the game loader oracle.

React integration covers keyboard navigation, readable status labels, cancellation, provenance inspection, filtered coverage, diff review, hash-bound design approval, rejected stale approval, validation progress, failed runtime checks, export and rollback. An unknown result must remain visibly unknown through API and UI serialization. Every changed screen state must expose what evidence supports it.

## 5. OpenRouter mock and replay lane

Routine CI is deterministic and offline: no API key, live spend or provider availability required. Record/redact requests, model responses and local tool results; evaluate resulting behavior rather than exact prose. Replays include parallel/multiple tool calls, invalid argument JSON, unknown/mismatched ids, repeated calls, context growth, prompt injection in mod files, timeouts, rate limits, partial streams, capability mismatch, budget exhaustion and a confident unsupported repair.

Assert structural write limits, schema validation, source-hash preconditions, preservation obligations, reference/scope checks and full-stack expected results after every accepted proposal. Test that the agent cannot approve a design waiver, edit source/Workshop content, request arbitrary shell execution or publish directly. Optional live-model evaluations are a separate manual/scheduled lane with fixed fixtures, explicit budgets and recorded provider/model/endpoint metadata. Every discovered bad proposal becomes a replay regression.

## 6. Platform and deployment matrix

| Lane | macOS without game | Windows VM without game | Windows with selected EU5 build |
|---|---|---|---|
| Bytes/CST, serializers, synthetic loaders, merge obligations | Required | Same manifests/hashes | Same manifests/hashes |
| API, SQLite migrations, React, mocked agent, recovery | Required | Required deployment smoke | Required deployment smoke |
| Windows names from manifests | Injected target policy | Real APIs/NTFS calibration | Real APIs/NTFS calibration |
| Steam/Documents discovery | Synthetic libraries | Native adapters | Real install smoke |
| Lawfully available content parse corpus | Optional local private corpus | Optional private corpus | Required selected coverage |
| Six-mode schedule/readers, localization/GUI/event precedence | Conditional predictions only | Conditional predictions only | Required for conformance |
| Scope/effects/hooks, initialization, hot reload, actual logs | Unavailable | Unavailable | Required selected scenarios |

The first deployment gate is VM feasibility: install the packaged app, start its loopback API/UI, open SQLite, resolve actual Windows known folders/Steam libraries, and prove the VM can launch and initialize the selected game build. Record Windows architecture, VM software/configuration, CPU/RAM/GPU, display/input driver and game dependencies. Do not assume an Apple Silicon Windows VM can run the chosen EU5 build adequately. If it cannot, mark game validation unavailable and, after an explicit recorded project decision, use the same replaceable worker on a supported Windows host; retain macOS development and synthetic coverage.

Test native Windows filesystem directories as well as VM shared folders. Include case aliases, long paths, Unicode user folders, reserved names, junctions, locks, antivirus interference and rename behavior. macOS may itself use a case-insensitive volume; manifest-backed tests keep logical coverage independent of host storage behavior. Pin dependencies and compare deterministic hashes across platforms.

## 7. Transaction and rollback verification

Inject failure at each promotion boundary: staging write, backup, file flush, manifest write, SQLite commit, directory publication, playset-adapter update, and cleanup. On restart, reconcile the durable journal with real file hashes; the visible output must be the old complete generation or the new complete generation. SQLite atomicity alone does not make filesystem publication atomic.

Test simultaneous jobs and Workshop/source updates between planning, validation and promotion; lock one managed destination and recheck every read/write precondition. No interrupted or stale generation may become active. Rollback uses exact saved bytes and playset state, with preconditions to avoid overwriting an externally changed destination. Retain originals, failed staging material and raw run evidence until explicit retention policy removes them; source/Workshop folders remain unchanged. Test low disk space, permissions/locks, cancellation and process termination, not only success.

## 8. Windows game-validation protocol

**D:** The console documentation describes `-debug_mode`, `script_docs`/`script_documentation`, `dump_data_types`/`DumpDataTypes`, `version`, `event`, `test_event_trigger`, `effect`, `trigger`, `run`, and log tools. These are interactive facilities, not evidence of a stable headless validation API. [Console documentation](https://eu5.paradoxwikis.com/Console_commands).

**D:** The modding guide places `error.log` under the EU5 user-data `logs` directory, script docs under `docs`, and data types under `logs/data_types`. It documents hot-reload exceptions including on-actions, crash-driven mod disabling, `--ignore-disable-mods-on-crash`, and file-open problems that can appear as encoding errors. Retain the guide's version caveats and confirm commands on the target build. [Debugging guide](https://eu5.paradoxwikis.com/Modding#Debugging).

**H:** No verified `--validate`, headless mode, parse-only exit code, unattended campaign protocol or inherited EU4/CK3 switches were established. Initial harness behavior is a bounded UI-driven cold launch with documented facilities confirmed on the selected build. A process exit code or mounted-mod list alone cannot establish correct active content.

For every order-sensitive probe, run clean baseline with the same DLC/settings, A alone, B alone, A+B, B+A, and repaired A+B as separate cold starts. Test minimal pairs that vary only one axis. Before each trusted result, prove the intended active playset/order and sentinel content actually loaded; after a crash, recheck it again because mods may have been disabled. Archive raw logs before normalization or clearing. A vanished error caused by disabled mods is not a successful repair.

| Milestone | Evidence gained | Still outside coverage |
|---|---|---|
| Static bytes/paths/CST | Paths and syntax within implemented coverage | Game recognition, semantics |
| Static typed resolution | Known references, scopes, arity, dependencies | Dynamic targets and execution |
| Cold start to main menu | Earliest resources initialized | In-game resources and setup |
| Country-selection lobby | Additional databases/world initialization | Campaign-only behavior |
| New campaign + bounded ticks | Selected startup/monthly/yearly hooks | Other states and long-run balance |
| Targeted effect/event/trigger probes | Exact exercised behavior | Unexercised branches |
| Existing-save load | One migration/save scenario | Other saves and removals |
| GUI / locale scenarios | Selected screen bindings and languages | Other screens/translations |

Every result records reached milestones and individual assertions as pass/fail/unknown. Directly observe the tested value/effect via a verified UI/debug/save/probe method; logs are supplementary. Preserve screenshots, raw saves or outputs as appropriate. Clean startup logs do not prove an override took effect or both mods retained their behavior.

Each run record includes executable hash/version/checksum/branch, content and Steam build identifiers when available, DLC manifests, script-doc/data-type hashes, user overlay, mod raw hashes, playset before/after, launch arguments, environment, seed/scenario, requested and observed milestones, exact probe and observation method, raw logs, emitted-file/source maps, screenshots/save/result evidence, assertion results and remaining obligations. Preserve randomness/timing limits rather than promising perfect deterministic simulation.

## 9. Log comparison and warning policy

Store raw logs first, then a versioned parsed index with optional stage, file/line, engine component, severity, byte offset, original message and normalized fingerprint. Build parsing patterns from observed logs; there is no universal error-line regex established here. Maintain emitted-file line maps because game diagnostics may refer to staged output.

Compare multisets by stage, severity and count, not merely distinct message sets. Report new diagnostics, increased counts, changed severities, disappearing expected diagnostics and regressions against both baseline and individual-mod runs. Preserve meaningful ids, values and script content during normalization. A warning already present in baseline is pre-existing, not thereby harmless; a repeated warning may become a serious regression.

No blanket harmless-warning allowlist is approved. Each contextual suppression requires exact build/family range, reproduction/evidence, expected count/stage and a directly observed success criterion. For a documented override that intentionally emits a duplicate diagnostic, assert both the expected diagnostic and intended effective behavior. Distinguish a file-open failure from a decoder failure before recommending encoding conversion.

## 10. Conformance promotion and release gates

The [research backlog](RESEARCH_GAPS.md) specifies E01–E25. Required priorities include exact-path/playset direction (E01), within-mode/traversal/mode scheduling and bare creates (E02–E07), repeated readers and scripted/modifier behavior (E08–E11), event disagreement/helper closure (E12–E13), on-actions/localization/GUI/masks/stages (E14–E18), paths/setup/encoding/overlays (E19–E22), arithmetic/scopes/maps (E23–E24), and restart/crash state (E25). All are proposed experiments until recorded observations exist.

Before promoting one rule, predict discriminating alternatives, materialize valid private seeds, run controls and both relevant orders, observe the actual affected field/behavior, archive evidence, and bind the result to the tested executable/content/DLC/family scope. A passing main-menu launch cannot confirm an in-game rule. Contradiction invalidates that rule, dependent caches and repairs; changed game/docs/profile fingerprints require revalidation or an explicitly narrower reuse argument.

Release gates are cumulative:

1. Lossless parser, path containment, contract F01–F20 and no-write negatives pass on macOS and Windows.
2. Packaged Windows app, migrations, crash recovery, source immutability and rollback pass; VM feasibility is recorded.
3. Every enabled production repair adapter has build-scoped loading/reader conformance and preservation assertions; unsupported regions stay visible as unknown.
4. Baseline, individual, stack and repaired runtime comparisons reach the promised milestones and satisfy targeted behavior obligations. Remaining unverified obligations appear in the report and UI; they cannot be silently counted as passed.
5. Design conflicts have concrete hash-bound user decisions, stale approvals fail, and every promoted output has exact manifest/backup/rollback material.

A release can ship static analysis before game conformance exists, but must label loader predictions as conditional and keep unsupported automatic repair disabled. Neither this matrix nor a successful test run claims universal compatibility of arbitrary scripts and gameplay intent.

## 11. Cross-boundary regression requirements

- A documentation-only profile may export an `experimental_bundle` for review/probes; syntax success or menu reachability cannot enable `validated_managed_release`. Experimental export changes neither the active-release pointer nor playsets and retains unknown/not-run gates. A synthetic workspace cannot target a real playset.
- Deterministic policy enumerates the complete affected preservation closure. Omitted, unknown or violated unwaived obligations block validated promotion even if a model labels them optional.
- Source-excerpt exclusions are enforced on outbound OpenRouter requests and saved transcripts. Credentials are absent from both, and retries/fallback providers obey the same configured policy.
- Competing application processes serialize target/playset promotion. Locks precede final precondition checks and remain held through verification. External source updates during activation prevent a validated-success result and exercise journaled restoration/recovery.
- Replacing the required Windows VM deployment with a different compatible Windows host requires an explicit recorded project decision; the replaceable worker preserves identical test/evidence contracts.
