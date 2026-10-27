# EU5 scripting, lossless parsing, and semantic analysis

Status: proposed implementation specification, 26 October 2026. See [index](INDEX.md), [product requirements](SPEC.md), [architecture](ARCHITECTURE.md), [loading semantics](EU5_LOADING_SEMANTICS.md), and [test contracts](TESTING.md). The source investigation is preserved in [RESEARCH_REPORT.md](RESEARCH_REPORT.md), sections 1–3.

## 1. Evidence and scope

Every game-facing semantic rule must carry an evidence record. **V** means an inspected source or repository fact; **D** means documented EU5 behavior; **I** means engineering inference; **H** means unknown or hypothesis; **P** means a proposed engine design. **C** is reserved for an executed, archived conformance result scoped to the tested build, content family, context, and inputs. There are **no C rules in this package**. V verifies the inspected source, not the executable; D is not a substitute for C. Normative MUST/SHOULD statements below specify the proposed application, not verified game behavior.

The parser must answer “what bytes and structures are present?” independently of “what loads?” and “what happens during play?” Lossless parsing is required across the supported corpus; semantic coverage is explicitly narrower. Unknown constructs remain available for inspection and preservation. Their preservation does not authorize an automatic semantic edit.

**D:** the official EU5 modding diary identifies a Jomini-based scripting environment and illustrates event definitions with repeated options, localization references, triggers, and effects. This is EU5 evidence, but not an exhaustive grammar or current executable contract. [Official Tinto Talks #85](https://forum.paradoxplaza.com/forum/developer-diary/tinto-talks-85-22nd-of-october-modding.1864004/)

## 2. Front ends and dispatch

**P — SCRIPT-001:** choose a front end using the target build profile, resource stage, physical relative path, signatures, and extension. Extension alone must not select loader semantics. Preserve exact path spelling. Do not flatten `loading_screen`, `main_menu`, or `in_game` into one namespace.

| Content | Required front end | Rewrite boundary |
|---|---|---|
| Script `.txt` | Byte scanner and ordered CST | Only profile-supported family/constructs |
| `.gui` and GUI descriptor content | Shared token infrastructure plus GUI grammar | Types, templates, inheritance, bindings, and order require GUI-specific checks |
| Localization `.yml` | Dedicated Paradox localization front end | Preserve language headers, optional entry versions, quoting, interpolation, and bytes; do not serialize as ordinary YAML |
| `.metadata/metadata.json` | Lossless JSON editing | Preserve unknown fields, original identity, lexical formatting, and unrelated values |
| CSV, map data, or other tables | Registered format adapter | Respect that format’s delimiters, headers, and ordering |
| Binary and unknown content | Opaque blob and available reference metadata | No semantic rewrite; exact copy or explicit user choice only |

An unsupported document may still participate in exact-path/hash analysis. The report must distinguish “unsupported analysis,” “malformed under selected dialect,” and “documented as ignored by the game.” They are different outcomes.

## 3. Structural grammar and tokenization

**P — SCRIPT-002:** implement a deterministic Python byte scanner and recursive-descent parser. The following grammar is illustrative front-end design, deliberately broader than a certified EU5 grammar:

```ebnf
document  = (trivia | item)* ;
item      = statement | bare_value | opaque_extension | error_node ;
statement = head, [ operator, value ] ;
head      = atom | quoted_atom | keyword_head | compound_head ;
value     = scalar | block | tagged_block | opaque_extension ;
block     = "{", (trivia | item)*, "}" ;
operator  = "=" | "==" | "!=" | "<" | "<=" | ">" | ">=" | "?=" ;
```

`opaque_extension` and `error_node` are application representations, not game keywords. Specific constructs require family eligibility checks after parsing. Recognizing `==`, for example, does not establish that every EU5 context accepts it. EU5 trigger documentation lists `<`, `<=`, `=`, `!=`, `>`, and `>=`; operand legality and scope remain context-specific. [EU5 Trigger documentation](https://eu5.paradoxwikis.com/Trigger)

**V:** the inspected Go parser node model represents bare list items, tagged blocks, dates, repeated fields, and prefixed definitions. The inspected Paradoxical grammar includes GUI heads, mixed blocks, and `code [[...]]` bodies. These observations justify corpus cases and replaceable adapters, not a claim of universal engine acceptance. [Pinned Go node model](https://github.com/kaiser-chris/pdx-parser-go/blob/dda99719d41c07da2b7fec4739fb209a7469df33/script/node.go), [pinned Paradoxical grammar](https://github.com/zgavin/paradoxical/blob/798edba0ea92a1306f01393b2e8bf7f5ad9342b2/ext/paradoxical/src/script.pest)

| Illustrative input | CST requirement | Semantic restriction |
|---|---|---|
| `x!=1`, `x ?= { ... }` | Longest-match operator tokens, with or without spaces | Do not absorb `!` or `?` into the preceding atom |
| `option = {...} option = {...}` | Two ordered property occurrences | No dictionary collapse or automatic deduplication |
| `{ a b c }` | Three ordered bare-value nodes | Do not infer set semantics |
| `{ a = 1 b }` | Mixed ordered items | Family schema may reject mixing without changing the original |
| `rgb { ... }` | Tagged-block node with original tag and values | No numeric normalization or component inference |
| `scripted_trigger helper = {...}` | Composite declaration head | Retain constituent tokens and file-local identity |
| `type panel = base_type {...}` | GUI declaration head | Keep type/name/base and GUI-specific relationships |
| `INJECT:item = {...}` | Raw head plus optional derived operation record | Recognize mode only at an eligible top level; arbitrary colons are not modes |
| `@x`, `@[ ... ]`, `$PARAM$` | Exact expression and parameter spans | Keep compile-time substitution separate from runtime values |
| `"[SomeFunction(...)]"` | String plus optional embedded-language index | Never execute bindings as Python, JavaScript, or shell |
| `1337.4.1`, `-2.50`, `country:ABC` | Raw scalar with optional derived classification | Dates are not floats; dotted atoms are not automatically dates |

**P — SCRIPT-003:** lexer modes must include ordinary script, quoted strings, comments, bracket expressions, and supported template/code bodies. In a quoted string, `#` is not a comment and braces do not alter block depth. Preserve escape spelling; unknown escapes are not errors merely because JSON would reject them. Quote termination must account for the parity of preceding backslashes. Literal `\n`, an actual newline, and path backslashes must remain distinct.

Core `#` comment support is separate from any `//` extension. **V/H:** the inspected Paradoxical grammar models `//` in some EU5 defines, but universal acceptance is unestablished. Enable its semantic eligibility only through an explicit dialect/family rule. [Pinned grammar](https://github.com/zgavin/paradoxical/blob/798edba0ea92a1306f01393b2e8bf7f5ad9342b2/ext/paradoxical/src/script.pest)

## 4. Immutable bytes, encoding, and positions

**P — SCRIPT-004:** the immutable source byte stream is authoritative. Store its content hash, codec decision and diagnostics, BOM bytes, newline observations, token stream, CST, parser version, and dialect profile hash. UTF-8 decoding is strict. Detect UTF-8 BOM without discarding it. Detect UTF-16/32 signatures and retain bytes while reporting unsupported encoding unless an adapter explicitly supports that family. Never guess a replacement codec and then silently rewrite the file.

**D:** setup documentation distinguishes UTF-8 with BOM for `setup/countries` and `setup/templates` from UTF-8 without BOM for `setup/start`. It also gives filenames a role in template inclusion. These claims were documented, not retested for the target build. [EU5 Setup modding](https://eu5.paradoxwikis.com/Setup_modding)

Consequently, a blanket “add BOM to all EU5 text” policy is prohibited. Existing files retain encoding, BOM, newline style, and unchanged byte ranges. New files use the selected versioned family policy. Invalid bytes remain inspectable and byte-preservable but block automatic semantic rewriting. A deliberately requested syntax/encoding repair must be its own visible change with explicit preconditions.

**P — SCRIPT-005:** use half-open byte spans `[start_byte, end_byte)`. Position maps must distinguish:

- Byte offsets in the original blob, including BOM.
- Decoded Unicode code-point offsets.
- Zero-based UTF-16 columns for the React editor/API.
- Human-facing one-based line and displayed-column locations.

Test CRLF, lone LF, BOM, tabs, combining marks, non-BMP characters, and non-ASCII text before every edited occurrence. Store an explicit API convention; never pass a Python character offset as an editor UTF-16 column. Unicode normalization belongs in optional search keys, not serialization. Keep exact source identifiers separate from Windows path-comparison keys.

Raw scalar spelling is part of the CST. Use `Decimal` only in derived numeric views. Never rewrite through binary floating point, round a source value implicitly, or treat `1`, `1.0`, and `01` as identical source text.

## 5. CST contract and derived views

**P — SCRIPT-006:** each document comprises an immutable blob, tokens, and an ordered CST. Nodes retain their token bounds, byte spans, kind, parent, and ordered children. Node identity is valid only within a snapshot. Tokens cover all original bytes, including trivia, unknown regions, and invalid bytes. Synthetic missing tokens have zero width and cannot appear in original serialization.

Minimum node kinds are document, property, bare value, block, tagged block, declaration head, GUI head, constant expression, template/code body, opaque region, and error node. Comments remain independent trivia tokens. Attachment to a deleted/moved node is a separate edit policy: an ambiguous section heading or commented-out property must not disappear because an adjacent property was removed.

The derived semantic IR may normalize values for analysis, but must never mutate the CST or become the serializer authority. Distinguish raw hash, structural hash, and profile-specific effective semantic hash. A hash equality in one domain cannot stand in for equality in another.

Required contracts:

1. `serialize_original(parse(raw)) == raw` for every accepted input, including malformed and opaque documents.
2. Untouched byte ranges remain identical after an approved edit.
3. Repeated fields and bare values retain source order and occurrence count.
4. A generated file is deterministic under a declared style/family policy.
5. Reparsing edited output yields no new unsupported or malformed regions in the affected area, and no unexpected structural changes elsewhere.
6. Semantic lowering is reproducible from the source snapshot, imported docs, and rule profile; it never hides uncertainty.

The first contract proves source preservation, not game validity.

## 6. Structural editing and concurrency

**P — SCRIPT-007:** expose structured operations such as `ReplaceScalar`, `InsertStatementBefore`, `AppendOccurrence`, `RemoveOccurrence`, and `ReplaceDefinitionBody`. Do not expose an unrestricted “set key” operation that implicitly selects one of several occurrences.

Every operation must include document hash, target node signature/span, occurrence selector, old-range hash, intended replacement, reason/provenance, preservation obligations, allowed effect set, and profile revision. A selector such as `definition.effect.add_gold` is insufficient when the field repeats; use parent identity plus ordinal or an exact occurrence identity bound to the snapshot.

Planning sequence:

1. Resolve all targets against the pinned immutable snapshot.
2. Reject ambiguous, stale, overlapping, unsupported, or out-of-bounds edits. Multiple insertions at one boundary need an explicit stable order.
3. Compute the exact byte-range write set. Preserve uncertain adjacent trivia.
4. Apply in memory using original-offset coordinates, or an equivalent deterministic piece-table procedure.
5. Reparse and validate the result; compare unchanged ranges and whole-stack effective behavior where covered.
6. Show source and effective diffs with unresolved obligations. A model proposal is never its own validation result.
7. Pass the validated staging artifact to the transaction/promotion layer in [ARCHITECTURE.md](ARCHITECTURE.md). Recheck hashes before commit and retain rollback bytes.

Node IDs alone cannot authorize edits after a source change. A changed Workshop file invalidates all plans reading it, even if the displayed mod version is unchanged.

## 7. Error recovery and resource limits

**P — SCRIPT-008:** produce explicit diagnostics and recovery nodes for unterminated strings, unexpected closers, missing braces, malformed declaration heads, and partial operators. Preserve bytes rather than fabricating a clean file. Resynchronize using lexical state, brace depth, and credible statement boundaries; newline alone is not a statement delimiter. Report the earliest certain failure and related opener locations.

A recovered region is ineligible for automatic semantic edits. An explicit syntax-repair workflow can propose a minimal correction, but must show its range, inferred intent, newly recovered structures, and validation limitations. Error recovery must not make later symbols silently vanish from coverage reports.

Enforce configurable byte-size, token-count, nesting-depth, diagnostic-count, macro-expansion depth, expanded-node-count, and wall-time limits. A resource-limit result is “analysis incomplete,” not “compatible.” Cancellation leaves source files untouched. Start with whole-file parse caching keyed by `(raw_hash, parser_version, dialect_profile_hash)`. Reindex changed files and dependent closures. Introduce finer-grained incremental parsing only after benchmarks justify it and lexer-state invalidation is correct.

## 8. Semantic analysis contracts

### 8.1 Binding and provenance

**P — SCRIPT-009:** separate syntax recognition, name binding, type/scope checking, control-flow/effect analysis, loader evaluation, and gameplay observations. Keep a symbol’s source stage, family, namespace, identifier, visibility, and occurrence. Stage identity can be unified only by a conformant rule for that family. Each reference records source span, target kind, expression, candidate targets, and certainty: `literal`, `expanded`, `dynamic`, or `unknown`.

Import built-ins, scope/type traits, and accepted commands from the selected installation’s generated script documentation. Pin its hash and build identity; unavailable or incomplete documentation reduces coverage. The importer must not replace unknown mod-defined symbols with a guessed built-in interpretation.

Maintain package dependencies, definition/call dependencies, ordered operation records, and conservative behavior read/write relationships. Literal reference resolution is stronger than heuristic name matching. Dynamic reference sites remain visible even when all literal references resolve.

### 8.2 Scopes and existence checks

**D:** documented scopes include typed game objects, `root`, saved `scope:` links, and scope transitions. Dot chaining can produce a different `PREV` from apparently similar nested blocks. `?=` is existence-aware: effects execute its body when the left scope exists; triggers require that scope and the test. It does not generally validate a missing right-hand comparison target. `any_` iterators and `every_`/`ordered_`/`random_` iterators have different trigger/effect roles. The source page carried a pre-release verification warning in the report. [EU5 Scope documentation](https://eu5.paradoxwikis.com/Scope)

**P:** flow analysis carries `(root, current, previous, saved_scopes)` and uncertainty through ordered statements and branches. Never flatten nested scopes or expand dot chains as a formatting rewrite. A scope-changing repair must preserve entry/exit context, `PREV`, saved-scope lifetime, and existence guards, or report unmet obligations.

### 8.3 Runtime variables and maps

**D:** documented regular variables belong to objects; global variables do not require an owner; local variables have an execution/event-chain lifetime. Reference forms include `var:`, `global_var:`, and `local_var:`. Values can include objects and other data, not just numbers. The report retained the Variable page’s 1.0 age warning. [EU5 Variable documentation](https://eu5.paradoxwikis.com/Variable)

**D:** the official 1.1 modding diary introduced ordinary/local/global variable maps, replacement at an existing key, and a fixed internal iteration order rather than insertion order; integer keys can represent array-like indexing. This corrects a broad assertion that EU5 lacks any array-like structures. [Official 1.1 modding diary](https://forum.paradoxplaza.com/forum/threads/tinto-talks-extra-modding-in-1-1-rossbach.1899358/)

**P:** bind variable reads and writes by storage class, owner, lifetime, and key expression. Equal text names in different owners are not automatically conflicts. Do not serialize runtime maps as source-ordered lists or promise a specific internal iteration order without C evidence. Dynamic keys require conservative alias analysis; unknown aliases remain obligations.

### 8.4 Textual macros and scripted declarations

**D:** `$parameter$` expansion is textual, case-sensitive, and may change names or inject script fragments. File-local `@` values differ from runtime variables. Inline scripted declarations in event files have local visibility and can collide with global names. [EU5 Macro documentation](https://eu5.paradoxwikis.com/Macro), [EU5 Event modding](https://eu5.paradoxwikis.com/Event_modding)

**P:** retain original macro source. Expand only into a bounded auxiliary representation with both definition and call-site provenance. Distinguish macro parameters, localization interpolation, runtime variables, and typed references. Detect cycles and budgets. Do not assume an unresolved parameter is an error in all contexts. Moving an event or helper requires its dependency closure and visibility checks; renaming requires all statically resolved references plus explicit treatment of dynamic references.

### 8.5 Script values and constants

**D:** script-value formula statements execute in source order; constants in `@[ ... ]` instead use conventional arithmetic precedence. Script values may depend on caller scope and game state. The wiki documents five-decimal fixed-point precision and overflow concerns; exact rounding, division, conversion, and overflow behavior remain build-specific H until tested. [EU5 Script value documentation](https://eu5.paradoxwikis.com/Script_value)

Illustrative, unexecuted fixture:

```text
probe_value = { value = 2 add = 3 multiply = 4 }
```

The documented sequential interpretation predicts 20. This is a conditional test expectation, not an observed game result. Sorting properties changes the program. Keep symbolic ordered expression/control-flow graphs. Do not constant-fold game-state-dependent named values, commute operations, normalize decimals, or infer all numeric injections are additive deltas.

### 8.6 Events, GUI, and localization

**D:** event documentation describes namespace-qualified integer IDs, repeated options, inline file-local helpers, and `orphan` console events. Its historical age and loader disagreements remain in [RESEARCH_GAPS.md](RESEARCH_GAPS.md). [EU5 Event modding](https://eu5.paradoxwikis.com/Event_modding)

**P:** index event calls, timing/firing sources, options, localization uses, scope requirements, and local helpers separately. Preserve option/effect ordering. GUI analysis tracks named types, templates, inherited bases, widgets, constants, and bindings. Localization analysis tracks `(stage, language, key)` occurrences plus embedded expressions and replacement tier; cross-stage identity remains profile-specific. A shared CST does not establish shared loader semantics.

## 9. Preservation obligations and repair eligibility

**P — SCRIPT-010:** preservation is the default. A repair must carry obligations for contributions from every affected mod, including source intent hidden by whole-file shadowing. “The surviving winner still works” is insufficient. Known unchanged behavior must remain unchanged; unresolved behavior must remain explicitly unproven. User-approved design waivers are narrow, recorded exceptions, never model-authored permissions.

| Proposed transformation | Required evidence/obligations |
|---|---|
| Scalar edit | Exact occurrence, supported reader semantics, expected effective value, unrelated occurrence preservation |
| Append/inject | Supported family and mode, ordered operation proof, field-reader behavior, duplicate/idempotence analysis |
| Move or rename event/helper | Namespace, local/global visibility, full dependency closure, literal and dynamic call-site accounting |
| Rewrite effect/trigger | Scope, `PREV`, control flow, execution count/order, side effects, variable lifetimes |
| Modify value formula | Source order, scope dependence, precision/overflow assumptions, dependent callers |
| Rewrite GUI/localization | Type/binding/key references, family precedence, languages, runtime observation where necessary |
| Edit unknown/recovered syntax | Block automatic semantic repair; preserve raw data and report uncovered obligations |

The planner must distinguish preservation failure, design contradiction, unsupported analysis, and pending runtime validation. An unavoidable design contradiction goes to the user with concrete alternatives and explicit lost/retained behavior. Broad approval must not conceal unknown loader behavior.

## 10. Verification and definition of done

**P — SCRIPT-011:** parser release acceptance requires the following contracts on macOS and Windows; the full matrix is in [TESTING.md](TESTING.md):

- Byte-exact no-op round trips, including BOM, mixed newlines, Unicode, invalid bytes, malformed strings/braces, and opaque content.
- Ordered preservation of duplicate keys, mixed lists, tagged blocks, compound heads, signed decimals, dates, macro bodies, and embedded expressions.
- Adjacent operator tests such as `x!=1`, `x?={...}`, and all supported longest-match variants.
- Edit-range isolation, stale-hash rejection, repeated-occurrence selection, comment preservation, deterministic generated output, and safe cancellation.
- Position conversion checks with non-BMP characters, combining marks, tabs, CRLF, and BOM before target spans.
- Family-dispatch tests that never parse metadata as script or localization as ordinary YAML, and never rewrite unsupported binaries.
- Conservative semantic tests for scope transitions, file-local helper closure, textual expansion, ordered values, variable ownership, and unresolved dynamic references.
- Differential comparisons with pinned parser implementations where useful; disagreement is evidence to inspect, not permission to adopt either parser as the game oracle.

Passing these checks establishes application contracts over the tested corpus. Runtime acceptance and behavior preservation still require the build-scoped Windows checks in [EU5_LOADING_SEMANTICS.md](EU5_LOADING_SEMANTICS.md) and [TESTING.md](TESTING.md). The UI must expose uncovered families and unproven obligations alongside every result.
