# Research companion fixture artifacts

These files are copied unchanged from the supplied research report's companion outputs:

- `fixture-schema.json`: illustrative JSON Schema draft 2020-12, revision 1.
- `fixture-003-disjoint-properties.json`: synthetic contract example for two baseline-relative independent changes.

They are not game-valid mod files, an implemented runner, or evidence of a passing EU5 experiment. `in_game/common/testdb` and fields `x`/`y` are synthetic. The `zz_compat.txt` name has authority only under the declared synthetic profile; it is not a universal production technique.

See [TESTING.md](../TESTING.md) for runner semantics, profile prerequisites, schema hardening, the distinction between pre/post-patch output, and the required no-write negative variant when ancestry or field independence is unknown.

The example's `generated_patch` playset entry is a reserved slot: materialize no generated files during the before-patch simulation, then add exactly the expected patch for the after-patch simulation.
