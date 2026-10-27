# Sources, provenance and evidence limitations

The controlling research input is **Europa Universalis V mod compatibility and repair engine — Engineering research report**, evidence cutoff **26 October 2026**, supplied as `Pasted text(3).txt`. Its V/D/I/H/P distinctions are preserved; this specification adds C solely for future archived build-scoped observations.

## Input provenance

The user referenced `/mnt/data/Pasted text(3).txt`. That path did not exist in the desktop workspace. Reading the referenced ChatGPT conversation (`6adffc88-a2f0-83ea-ae02-0e8179279325`, title *Build EU5 Mod Validator*) exposed a temporary local preview attachment with the same filename. That attachment was read and copied. The preview contained the complete 1,237-line research report. The chat itself exposed only assistant content-reference placeholders and attachment metadata; the earlier specification text was not recoverable.

The report's two companion fixture files were recovered from its explicit linked output directory and copied unchanged into `fixtures/`. No unrelated repository's specification was substituted for the user's unavailable original.

| Artifact | SHA-256 |
|---|---|
| Exact uploaded bytes: [sources/Pasted text(3).txt](<sources/Pasted text(3).txt>) | `7a158316cae9de50589daf2991f279ab8851443595f32efd2ff83b1590cbb80b` |
| Portable [RESEARCH_REPORT.md](RESEARCH_REPORT.md) | `54d526fedc3e56c62b48901e379a03149598c2ee122a829da6059fe30998a235` |
| [Fixture schema](fixtures/fixture-schema.json) | `8c6aa85f5243a8d276c8353609ca58eb59cf0993c5c426532dbe58f5d77d85eb` |
| [Fixture 003](fixtures/fixture-003-disjoint-properties.json) | `483df0756d21de711a8ec27c9ceaf81be8003df3cc3026568b41c03d6603a4ab` |

The portable report changes only its two absolute companion-link destinations to `fixtures/fixture-schema.json` and `fixtures/fixture-003-disjoint-properties.json`. The exact original remains available separately. Both report forms are evidence inputs; their proposed designs are not executed implementation results.

## Source map

The report contains the fuller bibliography and inspected repository revisions. Links here organize the main evidence by purpose. Unless noted below, these are **sources cited and characterized by the report**, not newly executed audits of their latest content. Wiki source ages and disagreements remain material. Runtime claims require separate C evidence.

| Source | What it supports | Boundary retained |
|---|---|---|
| [Official Tinto Talks #85, 22 October 2025](https://forum.paradoxplaza.com/forum/developer-diary/tinto-talks-85-22nd-of-october-modding.1864004/) | Origin of database modes and event/modding examples | Historical official statement; current family coverage not established |
| [Official 1.1 modding diary, 5 February 2026](https://forum.paradoxplaza.com/forum/threads/tinto-talks-extra-modding-in-1-1-rossbach.1899358/) | Variable maps and later scripting additions | Documents a version feature; does not measure current executable behavior |
| [EU5 mod structure](https://eu5.paradoxwikis.com/Mod_structure), [mod discovery](https://eu5.paradoxwikis.com/Mod) | Stage roots, JSON metadata, directory/discovery documentation | Community documentation; exhaustive installed schema still discovered locally |
| [Compatibility](https://eu5.paradoxwikis.com/Mod_compatibility) | File/mode/GUI precedence and injection descriptions | Includes older material and incomplete supported-family coverage |
| [Events](https://eu5.paradoxwikis.com/Event_modding), [on-actions](https://eu5.paradoxwikis.com/On_action) | Event IDs/helpers and hook extension | Conflicting source claims retained; no automatic override/composition without probes |
| [Localization](https://eu5.paradoxwikis.com/Localization), [setup](https://eu5.paradoxwikis.com/Setup_modding), [defines](https://eu5.paradoxwikis.com/Defines) | Format/encoding and family exceptions | Separate build/family conformance required |
| [Scope](https://eu5.paradoxwikis.com/Scope), [variable](https://eu5.paradoxwikis.com/Variable), [macro](https://eu5.paradoxwikis.com/Macro), [script value](https://eu5.paradoxwikis.com/Script_value), [trigger](https://eu5.paradoxwikis.com/Trigger) | Documented language semantics | Mixed-age verification; fixed-point details and scope rewrites remain measured questions |
| [Console commands](https://eu5.paradoxwikis.com/Console_commands), [debugging](https://eu5.paradoxwikis.com/Modding#Debugging) | Documented interactive debugging facilities and log locations | No established generic headless validation contract |
| [Pinned BerFoe inventory](https://github.com/BerFoe/eu5-modding-skill/blob/3b7e8f930303abc949c77f3d5c9b741ee896e620/eu5-modding/references/mod-structure.md), [launch helper](https://github.com/BerFoe/eu5-modding-skill/blob/3b7e8f930303abc949c77f3d5c9b741ee896e620/eu5-modding/scripts/Start-EU5.ps1) | Public inventory, separate-stage observation and EU5-specific playset implementation | V source/author observation, not this package's executed game result |
| [SOL project notes](https://github.com/HLJSXK/eu5-modding-project/blob/main/docs/knowledge/BRIEF.md), [Towards Victory notes](https://github.com/HLJSXK/eu5-towards-victory/blob/main/docs/technical/EU5_Modding_Knowledge_Base.md) | Real-mod syntax and reported reader/duplicate behavior | Mutable source URLs and mod-specific community observations; pin local snapshots before reuse |
| [Pinned Go parser nodes](https://github.com/kaiser-chris/pdx-parser-go/blob/dda99719d41c07da2b7fec4739fb209a7469df33/script/node.go), [pinned Paradoxical grammar](https://github.com/zgavin/paradoxical/blob/798edba0ea92a1306f01393b2e8bf7f5ad9342b2/ext/paradoxical/src/script.pest) | Grammar/tree design prior art | Implementation evidence; not proof of universal game acceptance or lossless serialization |
| [Community toolkit GUI updater](https://github.com/Europa-Universalis-5-Modding-Co-op/community-mod-toolkit/wiki/GUI-Update-Tool) | GUI identity/dependency and update workflow prior art | A reference approach, not an adopted dependency or verified game oracle |
| [OpenRouter client tools](https://openrouter.ai/docs/guides/features/tool-calling), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) | Remote tool protocol, endpoint capability and routing requirements | Endpoint support changes; validate locally and pin configuration |

## Checks made during this update

The official 1.1 diary and OpenRouter client-tool/structured-output documentation were retrievable directly and support the limited source statements attributed to them. The official release modding diary returned a client challenge; its content remains attributed through the supplied report, not represented as newly retrieved text. Other EU5 wiki/repository findings are imported with the report's caveats rather than presented as a fresh runtime audit.

No target installation, executable, DLC set, game logs or runtime observations were available or executed in this task. Historical version announcements in the report remain cutoff context; this package does not recommend a current stable/beta target from those announcements. Capture the user's actual installation and source revisions before enabling a production profile.

Source code is prior art only unless deliberately adopted. Before reusing any dependency or source material, audit its pinned revision, license and necessary notices; this package does not bundle third-party parser code or proprietary game data.
