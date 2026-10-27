# Research gaps and EU5 conformance backlog

Revision: 2026-10-26. This is a proposed research and implementation contract (**P**), derived from the supplied [research report](RESEARCH_REPORT.md), especially §§8 and 10. Read with [EU5_LOADING_SEMANTICS.md](EU5_LOADING_SEMANTICS.md) and [TESTING.md](TESTING.md).

## Current knowledge state

**No EU5 game experiment was executed for the supplied research, and none is claimed by this documentation package.** The report inspected documentation and public repositories. Its examples, JSON fixtures and proposed experiments are not runtime findings. The package therefore contains no newly conformance-verified loading rules.

Evidence labels are **V** inspected source/repository fact, **D** documented game behavior, **I** inference, **H** hypothesis/unknown, and **P** application proposal. **C** is reserved for an executed and archived, build-scoped conformance observation. Synthetic fixture passes test an application contract, not the executable. Passing a third-party parser's corpus also does not prove EU5 loading semantics or preservation.

The report identified stable 1.3.11 and beta 1.4.4 at its 26 October 2026 cutoff. Maintain separate targets; capture the actual installed build instead of selecting a profile from a displayed version string alone. Future game releases and documentation edits require renewed applicability checks. [Research version baseline](RESEARCH_REPORT.md)

## Decisions that must remain unresolved

| Gap | Current evidence and limitation | Default application behavior (P) | Probe/gate |
|---|---|---|---|
| Actual VM feasibility | Windows deployment and game execution in the chosen VM are required; GPU/driver/game initialization has not been demonstrated. | Build a replaceable Windows worker and prove clean baseline early. Do not equate a running Python service with game feasibility. | P0 baseline on actual VM; record environment and milestones. |
| Active playset persistence | EU5-specific 1.3.11 helper uses `playsets.json`; generic launcher mappings conflict. Mount logs may list inactive available content. | Read-only adapter plus explicit user/game confirmation; preserve every unknown field. | Playset experiment below; E01/E25. |
| Complete content inventory | Representative trees and a public 1.3-era inventory exist; exhaustive current installation not inspected. | Discover folders/extensions/stages; retain unknown content; reduce coverage explicitly. | Installation manifest plus generated docs/data types. |
| File and mask precedence | Compact compatibility rules are D; mask/overlay interactions and DLC/user overlay priority are H. | Conditional trace or symbolic alternatives; no guessed destructive rewrite. | E01–E03, E17, E19, E22. |
| Six-mode applicability and scheduling | Meanings are D for many databases; complete family set, bare create phase, failure scope and global batch boundary are H. | Explicit family allowlist; separate creation and modes; no universal default. | E04–E07 per family. |
| Field-reader semantics | Top-level injection append is D; numeric modifier/price differences are V community observations. | Preserve ordered occurrences; unresolved readers remain symbolic. | E08–E11 per field/type. |
| Event duplicate override | Wiki's earlier-file override and pinned community notes disagree about vanilla-ID override. | Block event override export, retaining both claims. | E12/E13. |
| On-action extension | Dedicated guide permits a narrower callback technique than broad compatibility overview. | Block generalized composition; callback-only implementation still requires conformance. | E14. |
| Localization priorities | Ordinary/replacement processing is D with 1.0-era caveats; replacement-tier tie breaks remain H. | Separate parser and precedence axes; no generic YAML writer or last-wins fallback. | E15/E21. |
| GUI identity and inheritance | Type/template precedence is D; real widget/dependency closure remains family-specific. | Track file shadows, symbols, constants and bindings separately. | E16. |
| Cross-stage visibility | Community notes report separate databases in two stages; exhaustive executable behavior unknown. | Keep stages in identity; no automatic coalescing. | E18. |
| Setup manager semantics | Encoding exceptions, filename identity and additive behavior are D; exact manager rules need checking. | Per-manager adapter; preserve filenames and initialization order. | E20/E21. |
| Arithmetic, scopes and maps | EU5 docs distinguish sequential values, constants, variable lifetimes and scope transitions; precision/conversion details still need observation. | Preserve order and symbolic values; no algebraic normalization or unsafe scope rewrite. | E23/E24. |
| Runtime automation | Debug facilities are documented, but no verified headless/parse-only CLI contract or unattended campaign interface was established. | UI-capable replaceable driver; bounded launch/wait; human-assisted checkpoints allowed. | Runtime harness qualification; E25. |
| Intent ancestry | Current vanilla may differ from the mod author's original baseline. | Mark baseline unavailable; do not claim a three-way merge or additive delta without ancestry. | Pin upstream snapshots/history; user design resolution when predicates conflict. |
| Arbitrary gameplay preservation | Static scripts cannot establish every possible runtime state, random branch or balance objective. | Explicit obligations and scenario coverage; retain unproven behavior in result. | Targeted behavior probes and user design choices. |

The source disagreements and caveats above are retained from [compatibility documentation](https://eu5.paradoxwikis.com/Mod_compatibility), [event guide](https://eu5.paradoxwikis.com/Event_modding), [on-action guide](https://eu5.paradoxwikis.com/On_action), [localization guide](https://eu5.paradoxwikis.com/Localization), [setup guide](https://eu5.paradoxwikis.com/Setup_modding), and [pinned BerFoe inventory/notes](https://github.com/BerFoe/eu5-modding-skill/blob/3b7e8f930303abc949c77f3d5c9b741ee896e620/eu5-modding/references/mod-structure.md). These citations identify reported documentation, not completed experiments.

## Evidence and experiment registry (P)

Each gap shall have a durable ID, owner/status, question, competing hypotheses, affected family/stage/build, sources and source revisions, blocking capabilities, planned experiment IDs, result artifacts and next action. Initial status of every E-series experiment below is `proposed_not_run`. Do not pre-populate a pass or an expected game result merely because a synthetic fixture has one.

Allowed experiment states are `proposed_not_run`, `ready`, `running`, `passed_with_scope`, `failed`, `inconclusive`, and `superseded`. “Inconclusive” must explain why the observations cannot discriminate the hypotheses. A run with unconfirmed active mods, missing direct observation, an unexpected crash, or changed inputs cannot promote a rule.

A conformance record shall contain:

```text
experiment_id, protocol_revision, run_id, timestamps
question, hypotheses, controlled_axis, negative_control
Windows host/VM and driver details
executable version/branch/hash, content/Steam identifiers, DLC manifest
installation inventory, user overlay inventory, script_docs/data_type hashes
settings, scenario, seed when available, save/new-game context
package hashes, source bytes, metadata IDs, exact playset/order before/after
launch arguments, cold-start confirmation, reached milestones
probe source and observation method, raw observations, screenshots/saves/logs
assertions and pass/fail/unknown, repetitions and variability
result scope, limitations, reviewer, artifact hashes, resulting rule revision
```

Retain original artifacts before normalization. Store the exact emitted bytes and source-to-output maps. Separate observed engine diagnostics from the harness's interpretation. A useful result can be “unknown” without blocking independent known regions.

## Common minimal-pair protocol (P)

1. Prove a clean, pinned Windows baseline reaches the subsystem under test. Snapshot executable/content/docs, enabled DLC, settings, user overlay and original playset. Confirm actual active content through a sentinel; mounted availability is insufficient.
2. Use private copied, valid seed definitions from the selected licensed installation. Keep required fields/dependencies intact. Synthetic `testdb` directories are never assumed to be real game databases.
3. Create minimal A/B local mods with distinct valid sentinel values/effects. Run baseline, A, B, A+B and B+A as separate cold starts where applicable. Alter one axis per variant; repeat nondeterministic/timing-sensitive cases.
4. Observe the actual field or behavior through a qualified UI/debug/save probe. Count executions where multiplicity matters. Logs supplement observations; a clean log alone cannot establish that an override loaded.
5. Include a distinguishable negative control and preserve unrelated seed content as a shadowing/preservation control.
6. Archive complete inputs, playsets before/after, raw logs, milestone evidence and assertions. Restore the baseline and verify cleanup.
7. Promote only the tested family, field, stage, build and DLC scope. Record remaining alternatives; contradictions quarantine dependent rules and repairs.

## Proposed E-series experiment matrix

All rows below are **P — proposed, not run**. The discriminating result is a question to answer, not a statement of current EU5 behavior.

| ID | Controlled probe | Discriminating observation | Capabilities gated |
|---|---|---|---|
| E01 Exact path | Same valid relative path with A/B sentinels; reverse only playset order. | Which whole file wins; unrelated definition proves full-file shadowing; actual playlist direction. | VFS precedence and deployment-order assumptions. |
| E02 Distinct filenames | Same target/mode in `01_a` versus `99_b`; swap playset, then names separately. | Filename versus playlist precedence within a mode. | Family enumeration and patch filename policy. |
| E03 Traversal | Parent `zz_probe` versus child `probe/00_probe`, same target/mode; separate sibling/depth variants. | Parent/descendant ordering, sibling order and recursion. | Directory enumeration. |
| E04 Six-mode grid | All 36 ordered mode pairs on a valid seed; both filename orders; vary package assignment separately. | Mode-class priority versus names; batch boundary per database/source. | Mode scheduling per eligible family. |
| E05 Bare creation phase | A bare-creates a unique ID; B strictly injects/replaces; vary creator filename/order. | Registration phase relative to prefixed modes. | Creation placement in production profiles. |
| E06 Duplicate creation | Distinct files create same bare ID; separate repeated-key-in-one-file variant. | Reject/first/last behavior, diagnostic severity, retained winner and ordinal. | Duplicate policy. |
| E07 Missing targets | Absent ID for each strict/TRY/OR_CREATE mode, with a known valid control. | Error/no-op/create; diagnostics and failure scope. | Operation transition and error semantics. |
| E08 Scalar repetition | Different and identical values appended to one known scalar. | First/last/add/reject; idempotence or multiplicity. | That exact scalar reader. |
| E09 Nested repetition | Seed+A appends a disjoint nested block; separately add B replacing the whole seed. Repeat trigger/effect variants. | Repeated nested reader independently from later operation erasure. | Nested/block composition. |
| E10 Scripted code | Inject a distinct visible command into a scripted effect/trigger. | Both commands execute versus replacement; exact counts/order. | Scripted declaration composition. |
| E11 Modifier vs price | Same-shaped valid numeric injections in a static modifier and price definition. | Whether accumulation differs by reader. | Numeric field policies, individually. |
| E12 Event duplicate | Earlier standalone copy changes one vanilla event; B changes same ID; child-folder variant. | Earliest-ID rule, special vanilla treatment, actual visible option/effect. | Individual-event override export. |
| E13 Event helper closure | Copy event alone versus event with renamed/copied file-local helper; collision controls. | File-local/global visibility and required move closure. | Event extraction/movement. |
| E14 On-actions | Distinct callback registrations, then separate `events`, `random_events`, trigger and effect variants. | Which fields compose, diagnostics, callbacks fire exactly once. | Callback/general on-action merge rules. |
| E15 Localization | Ordinary/ordinary, ordinary/replace, replace/replace and identical-path pairs. | Each priority/tie axis independently; header/suffix/BOM negative controls. | Localization resolution and repair. |
| E16 GUI identities | Duplicate named type/template in distinct files; swap names/order; compare exact-path pair. | Symbol priority versus file shadows; preserve widget/constant control. | GUI symbol composition. |
| E17 Path masks | A `replace_paths` mask and B file under it; reverse order; descendant/unrelated variants. | Base/earlier/later source removal, recursion and overlay/mask order. | Path-mask simulation/export. |
| E18 Cross-stage | Same ID in `main_menu`/`in_game` with references from both; constants/macros separate. | Shared/separate identity, visibility and timing. | Cross-stage binding. |
| E19 Case/Unicode | Case-only paths, non-ASCII filenames, non-ASCII user folder in independent variants. | Windows aliases, enumeration and open-versus-decode failures. | Windows path comparison and portability. |
| E20 Setup managers | Distinct additive entries, repeated ID, deletion by whole-file replacement. | Manager-specific append/overwrite/removal and creation dependencies. | Each tested setup manager. |
| E21 Encoding | Valid family-specific script/GUI/loc/setup in BOM/no-BOM/invalid-byte variants. | Acceptance and failure diagnosis; `setup/start` separate from templates/countries. | New-file writer policy per family/build. |
| E22 Overlay/DLC | Disposable editor-generated user overlay and enabled-DLC sentinel collisions. | Additional source precedence and cleanup restores baseline. | Complete resource-source model. |
| E23 Arithmetic | Ordered value calculation plus decimal boundaries, division, negatives, overflow and constant expressions. | Sequential/constant differences, precision, rounding/conversion. | Exact numerical evaluation. |
| E24 Scopes/maps | Dotted/nested transitions, missing left/right targets, map keys with reversed insertion. | `PREV`, existence behavior, overwrite/iteration and dynamic analysis limits. | Scope/map rewrites and evaluation. |
| E25 Restart/crash | Modify one family while running; separate disposable load failure. | Hot reload versus cold initialization; crash disables/changes playset; driver detects state. | Runtime harness trust and recovery. |

The report's synthetic fixture family 7 expands into operation/presence combinations, and family 8 expands into independent ordering probes. The synthetic profile's create-first/reject-duplicate contract is a test choice; E05/E06 determine whether a production profile may use it. [Synthetic matrix](TESTING.md)

## Playset persistence qualification (P)

Before any adapter writes live game state:

1. With EU5 closed, snapshot names, hashes, sizes and modification times in a disposable user-data and relevant application-data area; capture SQLite schemas without altering databases.
2. Use the in-game UI to create `probe_AB`, enable A then B, Apply, exit cleanly and snapshot again.
3. Reverse A/B, disable B, and select another active playset as independent operations, each followed by Apply/exit/snapshot.
4. Inspect changed files only. Distinguish a complete playset database from a next-launch projection; test missing/stale projection behavior.
5. Correlate paths, metadata IDs and Workshop IDs with actual exact-path sentinel outcomes.
6. Implement a read-only versioned adapter first. Qualify transactional write, concurrent-update rejection, crash recovery and backup/restore before enabling export. Until then, activate through the UI.

The EU5-specific 1.3.11 observation is stronger than a generic launcher's EU5 mapping, but remains source evidence, not this package's conformance result. [Pinned EU5 helper](https://github.com/BerFoe/eu5-modding-skill/blob/3b7e8f930303abc949c77f3d5c9b741ee896e620/eu5-modding/scripts/Start-EU5.ps1)

## Runtime driver qualification and unsupported assumptions

The console documentation describes `-debug_mode`, `script_docs`, `dump_data_types`, event/trigger/effect commands and GUI/debug tools (**D**, page marked 1.3). The debugging documentation describes logs, hot-reload exceptions and crash-driven mod disabling (**D**). Qualify exact commands with `help` and direct probes on the target. [Console commands](https://eu5.paradoxwikis.com/Console_commands), [debugging](https://eu5.paradoxwikis.com/Modding#Debugging)

No verified headless validator, parse-only success exit code or stable unattended campaign protocol was established (**H**). Do not publish invented `--validate`, `-batch`, `-debugscripts`, `-mod`, `-userdir` or `-nographics` contracts by analogy with another game. This is absence of established evidence, not proof that the switches cannot exist.

Qualify these further harness checks before trusting its results:

- Startup milestones: deliberate failures in each resource stage and an untriggered event demonstrate what main menu, lobby and campaign checks actually cover.
- Logs: isolated brace, unknown field, missing ID, wrong scope and duplicate-ID defects produce pinned raw golden examples. Preserve counts and stages as well as distinct messages.
- Crash recovery: verify active playset after failures and after any documented crash-suppression flag; empty logs from accidentally disabled mods are invalid evidence.
- Documentation freshness: regenerate script/data-type dumps independently per build and compare hashes/schema changes.
- Cold starts: final acceptance uses fresh launches; hot reload has its own test scope and cannot replace initialization coverage.

## Rule promotion, contradiction and retirement (P)

A rule can enter production only when its exact executable/content/DLC applicability is known; positive and negative controls discriminate competing hypotheses; raw artifacts and direct observations are archived; relevant minimal pairs pass; failure scope and residual unknowns are explicit; and all required preservation obligations have appropriate validation. A reviewed rule may retain D/V evidence alongside C observations. C never means universal validity.

Promotion creates a new immutable profile revision and links its rule IDs to experiment IDs and artifact hashes. Update [EU5_LOADING_SEMANTICS.md](EU5_LOADING_SEMANTICS.md) applicability selectors rather than broadening an old result silently. Re-run affected conformance tests when executable, relevant content/docs/DLC, parser or profile logic changes.

A contradictory result immediately marks the rule `quarantined`, invalidates dependent caches and staged plans, and blocks affected automatic exports. Keep the failed observation, previous result and source disagreement. Reproduction may narrow the rule selector rather than invalidate unrelated families. Retirement must preserve old evidence needed to understand past patches and rollback.

Neither an OpenRouter response nor a user design decision can change a rule's evidence status. The user may choose among concrete gameplay alternatives and waive an explicit design obligation. Unknown loader behavior still requires measurement or an output that remains clearly unvalidated.

## Priorities and exit criteria (P)

| Priority | Work | Exit criterion |
|---|---|---|
| P0 | Windows VM feasibility, source snapshots and path abstraction. | Actual selected game reaches baseline milestones; exact source hashes; Windows path fixtures; originals untouched. |
| P1 | Lossless parser, evidence registry, documentation importer. | Byte-exact no-op/recovery tests; all rules scoped and sourced; unknown syntax/families retained. |
| P2 | VFS/family simulator and 20 synthetic contract families. | Golden provenance, symbolic unknowns, deterministic cross-host results; relevant initial minimal pairs measured. |
| P3 | Narrow deterministic repair and runtime harness. | Full-stack preservation checks; rollback/concurrency recovery; baseline/individual/stack/repaired observations. |
| P4 | OpenRouter staged investigation and conflict review UI. | Replay/tool/schema tests; no source writes; concrete design decisions bound to input hashes. |
| P5 | Broader family coverage and updates. | New adapters meet the same evidence gates; changed inputs invalidate or rebase previous repairs. |

Production scope should start with a small set of measured families, defines, metadata and localization. Unmeasured event, GUI, setup or binary composition must remain outside automatic repair until its own gate passes. The application can continue useful macOS development against synthetic contracts while the Windows program builds narrowly scoped empirical profiles.
