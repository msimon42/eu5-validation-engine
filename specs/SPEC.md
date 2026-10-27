# EU5 Mod Compatibility Engine — product specification

Specification revision: **2.0, reconstructed research integration, 26 October 2026**. Status: implementation contract, not an implemented or game-certified product. Read [the index](README.md) first. All product requirements below are **P — proposed design**, incorporating the user's mandatory constraints. Claims about EU5 are separately labeled and linked.

## 1. Purpose and retained constraints

Build a **local, single-user application** that explains how a selected Europa Universalis V mod stack loads, identifies lost contributions and incompatible requirements, and produces reviewable, validated repairs. The default objective is to preserve each mod's functionality and the user's intended playset. Parsing, loader prediction, and gameplay compatibility are distinct claims.

The retained stack is **Python with FastAPI**, **React with TypeScript**, and **SQLite**. An investigative agent uses **OpenRouter** through the backend. Development takes place on **macOS without requiring EU5**, using robust synthetic fixtures. Deployment and executable checks take place in a **Windows VM**, subject to an early actual-game feasibility check. A compatible Windows worker can replace the VM if its graphics, architecture, or game environment cannot initialize EU5. Changing that deployment target requires an explicit recorded project decision.

No universal compatibility guarantee is possible for arbitrary scripts and design intentions. The application must preserve inputs, make uncertainty visible, and refuse automatic repairs whose preservation conditions cannot be established. Runtime success establishes only the tested observations on the captured build.

## 2. Evidence contract

| Label | Meaning | Permitted use |
|---|---|---|
| **V** | A source statement, repository structure, or implementation was inspected | Evidence of that source's content; never automatically an executed game fact |
| **D** | Explicitly documented EU5 behavior | Conditional simulation; show page age, caveat and target-build mismatch |
| **C** | An executed, archived conformance observation on identified executable/content/DLC inputs | Production rule only within its measured scope and prerequisites |
| **I** | Reasoned inference from stated evidence | Investigation and conditional alternatives; no silent promotion to C |
| **H** | Hypothesis, unresolved disagreement, or missing evidence | Unknown result and targeted probe |
| **P** | Application design or illustrative test contract | Implementation requirement; not an assertion about EU5 |

The uploaded [research report](RESEARCH_REPORT.md) contains **no new executed EU5 experiment**. This package introduces **no C-level loader rule**. A source can have V provenance and describe D behavior simultaneously. `C` is an additional application label, not a retroactive relabeling of the report. Synthetic fixtures validate a proposed contract; they cannot create C evidence for EU5.

Results must propagate all relevant evidence dependencies. A final value is not C if any decisive loader or reader transition is unknown or merely documented. Coverage, confidence, static validity, preservation, runtime observations, and design approval remain separate fields; do not combine them into a misleading green score.

## 3. Scope and explicit boundaries

### Included

- Discover and snapshot vanilla, installed/enabled DLC, local mods, Workshop mods, selected playset/order, generated script documentation, and possible editor/user overlays.
- Index all three resource stages: `loading_screen`, `main_menu`, `in_game`; preserve original relative paths and unknown content.
- Build a lossless CST and derived symbol/reference views for supported text families; retain opaque files and recovered syntax.
- Simulate effective file selection, definition operations, and field readers using versioned, evidence-backed rules.
- Detect file shadowing, duplicate creation, replacement erasure, design contradictions, dependency problems, reference failures, ordering sensitivity, path risks and incomplete coverage.
- Investigate conflict clusters deterministically and, when useful, with a bounded OpenRouter agent.
- Stage compatibility patches or managed copies, validate the full final playset, export with a manifest, and roll back exactly.
- Reassess repairs after game, DLC, mod, documentation, profile or approved-intent changes.

### Deferred or constrained

No hosted account system, collaboration service, remote mod distribution, multiplayer support guarantee, universal gameplay proof, or automatic Workshop upload is required. The application does not redistribute proprietary vanilla content. Map/asset/GUI analysis starts with explicit supported adapters; opaque bytes remain preserved. Unknown families are a coverage finding, not evidence that the game ignores them.

## 4. Mandatory requirements and acceptance anchors

| ID | Requirement | Acceptance anchor |
|---|---|---|
| R01 | Operate locally for one user; core analysis works offline | No network required for contract scans; OpenRouter is explicit remote inference |
| R02 | Use Python/FastAPI, React/TypeScript, SQLite | Shared schema contract, backend workers, reproducible local deployment |
| R03 | Develop on macOS; deploy and check EU5 in Windows VM | [Testing tiers](TESTING.md); VM baseline is an early gate |
| R04 | Preserve original mods, vanilla and Workshop content | Original roots read-only; writes restricted to managed staging/output roots |
| R05 | Preserve ordered repeated syntax and original bytes | [CST contract](EU5_SCRIPTING.md); byte-exact no-op, surgical changed ranges |
| R06 | Use build-scoped, versioned loading rules | [Rule profiles](EU5_LOADING_SEMANTICS.md); no universal fallback |
| R07 | Support the six database operation modes with family eligibility | Modes, bare creation, schedule and readers modeled separately |
| R08 | Preserve contributions by default | Every automatic plan satisfies its declared preservation predicates |
| R09 | Obtain user approval for genuine design conflicts | Concrete alternatives, retained/waived obligations, fingerprint-bound decision |
| R10 | Make AI proposals locally checkable and staging-only | Schema, source hashes, allowed scope, budgets and local validators enforced |
| R11 | Validate full stack before promotion and enable rollback | Deterministic gates, required runtime probes, recoverable journal |
| R12 | Report coverage and evidence for every result | Unsupported/unknown regions visible; no “fully compatible” for partial analysis |
| R13 | Detect updates and reject stale repairs | Hash-based read sets; changes invalidate decisions, plans and applicable evidence |
| R14 | Supply a complete frontend workflow | [Wireframes](WIREFRAMES.md); keyboard-accessible evidence, diff, decision, validation, rollback |
| R15 | Retain reproducible evidence and tests | [Testing matrix](TESTING.md), experiment registry, manifests and audit records |

## 5. Discovery and workspace setup

The user selects game and user-data locations, a playset or explicit ordered mod list, a target game build/branch, and a rule profile. Resolve Windows Documents through known-folder APIs and enumerate all Steam libraries; do not guess paths from the username. On macOS, fixtures or imported snapshots are first-class inputs. A fixture workspace must be visibly labeled **Synthetic**, and export to a real game playset is unavailable there.

**D:** EU5 documentation places resources under the three stage roots and uses `.metadata/metadata.json`; a mod root corresponds to vanilla `game/`, without another nested `game/`. Preserve legacy artifacts, but do not generate an EU4-style `.mod` descriptor as a supposed EU5 requirement. Metadata relationship declarations are distinct from actual enabled state and order. [Mod structure](https://eu5.paradoxwikis.com/Mod_structure), [report §1](RESEARCH_REPORT.md#1-mod-structure-discovery-and-metadata).

Discovery must retain metadata IDs, Workshop IDs, filesystem paths and content hashes separately. Warn about absent/disabled dependencies, duplicate identities, unsatisfied versions, cycles, unknown version syntax, and missing DLC. An installed/mounted mod is not sufficient proof that it was enabled in the actual run. The playset adapter remains read-only until the selected build's persistence behavior is conformed.

Inventory each candidate's source, stage, family, raw path, Windows comparison key, size, hash and diagnostics. Preserve unsupported extensions and folders. Snapshot consistency requires stable before/after checks; an update during scanning causes a retry or an explicitly incomplete snapshot, never an internally mixed one.

## 6. User workflow

1. **Configure and scan.** Select sources, order and profile. Display target fingerprints, changed inputs and known coverage before presenting results.
2. **Review findings.** Group connected conflicts, show severity and certainty separately, identify affected mods and lost contributions, and allow filtering by stage, family, evidence, risk and runtime needs.
3. **Inspect provenance.** Follow an effective value back through path shadowing, enumeration, operations and reader selection to exact source occurrences. Hidden files remain inspectable for intent recovery.
4. **Investigate and plan.** Apply deterministic safe rules first. The agent can inspect history, references and documentation, request controlled probes and propose bounded structural edits.
5. **Resolve design conflicts.** Present complete, concrete alternatives only when preserving all requirements is contradictory or user intent is essential. Continue independent safe work while a decision is pending.
6. **Review a staged candidate.** Show file/semantic diffs, final-stack predictions, preserved obligations, unresolved checks and exact read/write sets. Changes have no effect on original mods.
7. **Validate and export.** Run required static, preservation and runtime gates. Promote the complete candidate only after its applicable gates pass and source/playset preconditions still match.
8. **Observe, update or roll back.** Keep the previous managed release and playset state; identify stale repairs after updates and offer an exact reversible restoration.

Scan cancellation leaves originals untouched and an incomplete job marked as such. Failed or budget-limited investigations retain useful evidence but never appear resolved.

## 7. Findings and preservation semantics

Use five headline categories: **confirmed incompatibility**, **potential incompatibility**, **compatible overlap**, **load-order-dependent outcome**, and **semantic/gameplay conflict**. A confirmed static parse or dependency failure need not imply an empirically confirmed loader rule. Store category, impact, certainty, coverage, runtime effect, lost intents, ordering constraints, repairability and evidence IDs independently.

The conflict unit is a connected cluster of files, definitions, operations, reference edges and behavior assertions. Three-mod interactions and whole-file losses must be detectable. A “winner” explains loading; it does not resolve preservation.

Each mod contribution becomes an obligation with:

- origin and exact author baseline, or an explicit `baseline_unknown` condition;
- desired delta, ordered occurrence or deletion and its dependencies;
- predicate, affected scope, measurement method and evidence;
- state `satisfied`, `violated`, `unknown`, or `waived_by_user`;
- links to source bytes, plan, validation and any user decision.

Examples include an option remaining selectable, a callback remaining reachable exactly once, an independent cost field retaining its intended value, and a GUI icon still being referenced. Runtime obligations need observable assertions, not merely source-text presence. Preserve unknown intent as unknown; do not manufacture a predicate that silently narrows a mod's purpose.

Historical author baselines matter. Compare each override to the version it was authored against when available. Current vanilla is not automatically the common ancestor. Distinguish an intended deletion from copied obsolete content, an absolute target from an additive delta, and identical files from identical operations that may intentionally execute twice.

### Automatic repair eligibility

A plan is automatically eligible only if it has a supported transformation, known applicable loader/reader rules, established input preconditions, an exact allowed write set, satisfied mechanical preservation predicates, and no unresolved design waiver. Conformed production profiles enable automatic game-directed export for their measured families. Documentation-only profiles can produce labeled **experimental staged candidates**, but cannot bypass required conformance or be presented as validated repairs.

Safe candidates include identical changes where reader semantics establish equivalence, truly independent fields under a known reader, and callback composition proved to execute each contribution once. These are conditional categories, not blanket permissions. Never automatically sum numeric disagreements, deduplicate commands, drop repeated fields, rename definitions with unresolved dynamic uses, disable a mod, or choose balance/timing/UI behavior on the user's behalf.

A generated patch is preferred. When the loader cannot express the repair safely, stage managed local copies and a replacement playset plan. Originals and subscriptions remain intact. A whole-file override must preserve every relevant definition and helper in the file, including contributions outside the immediate conflict.

### Design approval record

The decision screen must show the contradiction, affected mods, alternatives, exact retained/waived predicates, expected gameplay consequences and remaining uncertainty. Offer keep unresolved and custom design alternatives. Do not preselect a lossy answer. Store the user's chosen scope and explanation with `decision_id`, candidate/input/profile hashes and timestamp. Changes to those assumptions require renewed review; an old approval is not a general waiver.

Routine reversible investigation, safe staging and mechanically determined edits need no design approval. An agent may recommend an alternative, but only the user can waive a functionality requirement.

## 8. Validation, export and rollback

Validation is a set of independent gates: source consistency; strict supported syntax; encoding/naming/metadata; Windows paths; typed references and scope checks; full-stack loader prediction; expected effective results; allowed write set; preservation predicates; required game observations; and decision validity. See [TESTING.md](TESTING.md).

Show `pass`, `fail`, `unknown`, `not_run`, and `not_applicable` for each gate. Requiredness is determined by deterministic policy and the complete affected dependency/obligation closure; the model cannot omit obligations or mark them optional. Every affected obligation must be satisfied or carry a narrowly scoped, current user waiver. An unknown or violated unwaived obligation blocks validated promotion, as does a required unknown or not-run gate. Absence of new log errors cannot establish gameplay preservation. Do not relabel an experimental bundle as production because it parses or reaches the menu.

An experimental export is a portable review/probe artifact only: it never switches an active-release pointer, writes or activates a playset, or bypasses path, snapshot or edit-precondition checks. It retains all unknown/not-run gates and is visibly labeled unvalidated. A synthetic workspace cannot target a real playset.

An export contains generated files, valid EU5 metadata, required placement/managed-playset instructions, input and output hashes, rule/parser/schema versions, decisions, preservation obligations, full validation records, and rollback references. Exported metadata values derive from the selected target and source identities; example version strings are not compatibility promises.

Promotion stages a complete versioned output, verifies hashes, journals the intended transition, and switches a managed pointer/manifest where supported. Multiple renames are not one atomic filesystem transaction. Recheck inputs and active playset immediately before promotion; reject stale plans. Recover interrupted promotions by the journal and show the resulting state.

Rollback restores only application-managed outputs and the captured playset changes made by that promotion. Restore the exact previous hashes, preserve logs/evidence, and detect intervening external edits. Such edits require a displayed reconciliation; do not overwrite them silently. Rollback does not downgrade Workshop or the game installation. Keep original snapshots and dependency manifests for historical reproduction.

## 9. Milestones and release gates

| Milestone | Required outcome |
|---|---|
| M0 — storage and runtime feasibility | Stable snapshots, Windows path abstraction, immutable originals, VM starts the actual selected game and archives a clean baseline |
| M1 — parser and evidence foundation | CST exactness, recovery, JSON/localization/GUI boundaries, rule registry and docs importer |
| M2 — analysis | Stage-aware VFS, profiles, provenance, package/definition/operation/behavior graphs, all 20 initial fixture families represented |
| M3 — safe deterministic repairs | Predicate-based planning, full-stack validation, no-write negatives, stale-input rejection, promotion recovery and rollback |
| M4 — Windows conformance | Build/family-scoped measured rules, verified playset identity, baseline/individual/stack/repaired observations |
| M5 — agent and design UI | OpenRouter mock/replay contracts, bounded tools, concrete decision UI, end-to-end workflows |
| M6 — production expansion | Narrow measured family coverage first; update invalidation, retained historical evidence and new family gates |

M0's runtime-feasibility work proceeds early and in parallel with macOS development. Do not defer discovering that the VM cannot run EU5 until export is complete. Initial production families are selected by measured coverage, likely a small subset of databases plus defines/metadata/localization; this is a proposed prioritization, not a statement that those families are already safe.

## 10. Definition of done

The app is ready for its first measured release when the mandatory requirements above have traced evidence, the complete synthetic matrix passes, the chosen Windows environment runs the real target build, each enabled production rule has scoped conformance evidence, unsupported regions are visible, required preservation predicates pass, design conflicts remain user-controlled, and a promoted multi-file repair can be interrupted and exactly rolled back without modifying original mods.

This documentation package defines those criteria. It does not claim that the application, synthetic runner or game probes have been built or executed.
