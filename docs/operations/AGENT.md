# CK3 through Codex

## Start a conversation

Say “Check my current CK3 playset and explain what needs attention,” or “Continue
reviewing my mods.” The installed skill and connector supply the workflow; no
pasted history, workspace IDs, dashboard or startup command is needed. The first
briefing reads launcher metadata and small saved summaries. It labels historical
results rather than presenting them as a fresh check. A check request then runs
the saved job pipeline and reuses unchanged scans after complete source checks.
Continuing or recapping a discussion uses the saved findings without starting
another full-file check; the assistant labels their age.

`get_context` selects the current launcher playset; `selection="resume"` returns
to the most recent investigation. Explicit selections take precedence. Ambiguous
active selections produce named choices. JSON-only launcher state is labeled
“Last launch selection.” The first five missing mod names are a preview;
`list_missing_mods` pages the entire list. Source checks are asynchronous and
cancellable; simultaneous conversations share an existing running job.

## References and deeper investigation

The bundled CK3 library contains 24 authored entries and 26 fingerprinted sources,
including shipped documentation and pinned Tiger/CWTools revisions. It covers
scripts/scopes, loading, supported content families, preservation, updates, save
compatibility, application limits and unresolved behavior. It contains authored
explanations and references, not redistributed game manuals. Matching a version
label does not qualify runtime behavior. `search_knowledge` and `read_knowledge`
return source/evidence distinctions and version applicability.

`investigate_change` gathers contributions, base-game comparisons, related
definitions, relevant knowledge queries and available remedies. `search_sources`
supports paths, symbols and bounded literal text searches across captured files,
including documentation and deferred text; `read_source` verifies hashes and
returns bounded excerpts. `related_definitions` exposes supported literal and
dynamic reference edges without claiming a complete dependency graph. Excluded
sources remain excluded through derived results. A text continuation is a file
cursor, not a result offset; missing blobs, encoding gaps and budget limits remain
explicit. Follow continuation pages before claiming a complete search.
Captured external launcher descriptors are searchable and readable under
`@launcher/` paths and linked from relevant briefs. They retain selected-playset
ownership and available/unavailable-payload labels; disabled registrations are
excluded. Their bytes come from the saved capture, never a separate live read.

Automatic public research is permitted when local references do not settle a
question. The workflow uses the host's web tools, excludes private contents and
local paths from searches, and retains citations and uncertainty. New research
or agent notes do not promote knowledge into executed evidence or repair rights.

`remember_progress` saves objectives, reviewed issues, sourced notes and next
steps. Notes retain the scan they describe; a newer scan marks old notes historical
and clears the current reviewed-issue list. User approvals remain separate signed
records. Capability checks happen before approval prompts, so unsupported tests
and activation do not ask a pointless permission question.

The accepted [interface decision](../decisions/0003-codex-agent-interface.md)
makes the conversation the product interface. The engine remains deterministic;
Codex investigates its saved results, explains them in ordinary language, and
asks about concrete alternatives. The original specification package is preserved.

## Setup and connection

Run `uv sync --extra dev`, then `uv run mod-engine install-agent --data-dir
.workspace/ck3` from the checkout. The installer registers the named
`ck3_mod_agent` local MCP connection and copies its owned workflow into Codex's
skills directory. It refuses to overwrite an unrelated skill with that name.
Reconnect tools or reopen the conversation after installation. There is no
separate model service, API key, frontend build, or Node requirement for this path.

The installer supplies narrowly scoped permission defaults for the 19 inspection
and managed-housekeeping tools, so a normal check can run without repeated host
prompts. Tools truthfully distinguish reads from managed-state writes. Existing
explicit tool policies and server defaults are preserved, along with unrelated
settings and comments. Preparing, approving, writing, testing, enabling and
undoing fixes retain the host's existing policy and the engine's separate gates.

The connector attaches to one loopback-only headless engine per managed library.
Multiple conversations share the engine and its job coordinator. Sources and
choices survive reconnects. An existing legacy server holding the same library
must finish its jobs and stop before the new engine can start; no second writer
is opened. The optional dashboard is not mounted by `mod-engine engine`.

Release 2 installs the complete owned workflow and references as a recoverable
generation, preserving unrelated files. It refuses unsafe paths, unrelated named
connections and user edits to an installed owned file. A receipt binds the skill,
knowledge and connector code; the loaded engine and connector retain their startup
fingerprints. A mismatched running release is reported and cannot prepare or
approve changes. Updating files alone cannot make an old process claim the new
version. Reinstall/restart/reconnect preserves managed scans and choices.
Older proposal records remain readable and prepared files can still be retired;
new preparation choices require the current wording and fresh review.

The wheel's agent resources have been checked in an isolated installation. Full
standalone engine packaging is not qualified: existing schema/profile loaders
still depend on the checkout. The supported delivery here remains this checkout's
environment and installer.

For an already populated library, use its existing data directory during setup;
do not create a new library and assume previous snapshots or choices moved.
An installed connector uses this environment's Python executable. Reinstall it
after moving the checkout or replacing that environment.

## Implemented workflow

Version 3 adds `list_concerns`, `get_concern_evidence`, `read_sources`,
`record_concern_review`, and `get_investigation_report`. The report is the review
completion tracker; conversation notes remain supplementary. Every indexed
finding belongs to a concern, including internal, identical and wording changes.
Small groups retain source references and related-group links. Full review means
each detected concern has an explanation or a concrete unresolved disposition,
not that every enabled mod works in the game.

`find_missing_mod_candidates` searches known local roots automatically during
validation. It preserves missing registrations as missing. After the player's
choice, `inspect_mod_candidate` creates a separate alternative inspection;
launcher settings remain unchanged and ordinary resume retains the main playset.
`set_version_preference` remembers whether the player needs the current campaign
version. Version declarations and current author releases are advisory context,
never proof about the loaded game's behavior or authorization to update mods.

Evidence packages are limited to 128 KiB with explicit continuation. Batch reads
allow up to 16 excerpts of 8 KiB each, 64 KiB total. Current source exclusions and
hash checks still apply with cached projections. Old tools remain available.
Generated request schemas are in `schemas/agent-v3.json`.

Find and import a discovered playset, capture available files, and examine the
saved scan. A complete, searchable index includes captured mod localization that
the initial text budget deferred. Queries report total matches and page offsets;
an initial page is never evidence about the entire collection. Missing payloads,
unreadable content and unsupported readers remain visible. Repeated definitions
are compared with each other and the captured game version; equal content does
not imply a feature clash.

The first repair preparation path covers `call_ally_interaction`. It offers exact
versions from the contributing mods, leaving things alone, and optionally a
bounded, reviewed proposed combination. Original files remain read-only. A
trusted native choice form binds the user's response to the precise proposal;
model arguments cannot provide an approval boolean or sign their own answer.
Clients without choice-form support refuse approval. Changed sources, changed
choices or a newer scan require fresh review.

Approved files are written only into an inactive fixes mod in managed state.
Undo retires that inactive version and retains a recovery copy; intervening edits
are detected. This does not undo a live playset, because live activation has not
been qualified or enabled. Resume returns saved progress and choices; cancelled
or interrupted work is not treated as success.

## Remaining game acceptance

The real feature test, normal-playset activation and live undo milestone is
unfinished. Test requests currently return `not_run`; enable refuses. There is
no path that promotes a prepared artifact based on a clean parser or a simulated
approval. No real game observations are shipped by this increment.

`backend/agent/ck3_test.py` provides operator-only Mac isolation qualification
scaffolding, not a completed gameplay runner or a public model launch tool.
Preparing it never launches a game. Its native OS control checks use disposable
files and establish a write boundary only. A candidate private-data argument
must still be checked by an explicitly approved game launch. Normal data is
denied to that process and all writes outside the private test profile are denied.
The initial isolation probe enables no mods. Its success would not establish
character-action loading, preserved features, or complete playset compatibility.
Windows isolation and native execution are not qualified.

The actual call-allies investigation found Unofficial Patch's significant script
content identical to the captured base game, while More Interactive Vassals adds
behavior. A game test must establish whether those additions are lost before a
fix can be recommended. Missing enabled mods in the current collection also
prevent a claim about the complete installed playset.

## Checks

Run backend tests with `uv run --extra dev pytest` and Ruff with
`uv run --extra dev ruff check backend tests`. The headless process and native Mac
boundary checks need local process/network permissions. All automated tests use
temporary managed roots and synthetic sources. They do not launch CK3 or create
game conformance evidence. Native MCP tests cover actual choice forms, decline,
unsupported clients, and the real stdio connector; frontend checks remain a
regression lane for the optional developer UI.
