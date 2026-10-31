"""Synthetic CK3 inspection contracts; no game or live source directories."""
import base64
import copy
import json

import pytest

from backend.engine import ck3
from backend.engine.parser import PARSER_VERSION, digest, parse


def source(owner, path, raw):
    raw = raw.encode() if isinstance(raw, str) else raw
    return {"owner": owner, "path": path, "bytes_base64": base64.b64encode(raw).decode(), "sha256": digest(raw)}


def kinds(report):
    return {issue["kind"] for issue in report["findings"]}


@pytest.mark.parametrize("path,family,kind", [
    ("descriptor.mod", "descriptor", "descriptor"),
    ("events/nested/example.txt", "event", "script"),
    ("common/religion/religion_types/a.txt", "religion", "script"),
    ("common/religion/doctrine_types/a.txt", "doctrine", "script"),
    ("common/religion/holy_site_types/a.txt", "holy_site", "script"),
    ("common/governments/a.txt", "government_type", "script"),
    ("common/struggle/struggles/a.txt", "struggle", "script"),
    ("common/court_positions/types/a.txt", "court_position", "script"),
    ("common/court_positions/tasks/a.txt", "common/court_positions/tasks", "script"),
    ("common/schemes/scheme_types/a.txt", "scheme", "script"),
    ("common/schemes/agent_types/a.txt", "common/schemes/agent_types", "script"),
    ("history/characters/a.txt", "history/characters", "script"),
    ("gui/widgets/a.gui", "gui", "gui"),
    ("localization/english/a_l_english.yml", "localization", "localization"),
    ("gfx/interface/a.dds", "asset", "opaque"),
    ("in_game/common/traits/a.txt", "unknown", "opaque"),
    (".metadata/metadata.json", "unknown", "opaque"),
])
def test_root_layout_has_no_eu5_stage_or_flattened_common_identity(path, family, kind):
    result = ck3.classify_ck3(path)
    assert (result["family"], result["kind"], result["stage"]) == (family, kind, "game")


@pytest.mark.parametrize("raw", [
    b'\xef\xbb\xbfname="Example"\r\nreplace_path="history/characters"\r\nreplace_path="common/traits"\r\n',
    b'name="Example" name="Other" dependencies={ "A" "B" } unknown={ repeated=1 repeated=2 }',
    b'name="Unfinished', b"\xff\xfename=opaque", b"tags={ key=value }",
])
def test_descriptor_round_trip_including_malformed_and_unknown(raw):
    result = ck3.parse_descriptor(raw)
    assert result["document"].serialize() == raw
    assert b"".join(raw[token.start:token.end] for token in result["document"].tokens) == raw
    assert all(0 <= entry["span"][0] <= entry["span"][1] <= len(raw) for entry in result["entries"])


def test_descriptor_multivalue_projection_retains_masks_duplicates_and_unknowns():
    raw = b'name="Example" name="Other" replace_path="history" replace_path="common/traits" dependencies={"A" "B"} unknown={a=1 a=2}'
    result = ck3.parse_descriptor(raw)
    assert result["data"]["name"] == ["Example", "Other"]
    assert result["data"]["replace_path"] == ["history", "common/traits"]
    assert result["data"]["dependencies"] == [["A", "B"]]
    assert [child["ordinal"] for child in result["entries"][-1]["children"]] == [0, 1]
    assert "descriptor_repeated_scalar" in {item["code"] for item in result["diagnostics"]}


def test_schema_import_records_original_bytes_and_explicit_advisory_overlays():
    result = ck3.schema_manifest()
    assert len(result["schemas"]) == 24
    assert result["originals_changed"] == []
    assert result["source"]["status"] == "user_supplied_unversioned"
    assert all(item["sha256"] == digest((ck3.SCHEMA_ROOT / item["path"]).read_bytes()) for item in result["originals"])
    trait = result["schemas"]["trait"]
    assert "index" not in trait["requiredFields"]
    assert trait["localizationKeys"] == ["trait_{key}", "trait_{key}_desc"]
    assert "genetic" in trait["optionalFields"]
    assert "holy_site" not in result["schemas"]["religion"]["requiredFields"]
    assert result["schemas"]["on_action"]["optionalFields"]["fallback"]["type"] == "reference"
    assert result["policy"]["validation"] == "advisory"
    assert result["conformed_rules"] == 0


def test_schema_hash_changes_invalidate_import_without_overwriting_originals(tmp_path, monkeypatch):
    for original in ck3.SCHEMA_ROOT.glob("*.json"):
        (tmp_path / original.name).write_bytes(original.read_bytes())
    monkeypatch.setattr(ck3, "SCHEMA_ROOT", tmp_path)
    before = ck3.schema_manifest()
    changed = tmp_path / "trait.json"
    changed.write_bytes(changed.read_bytes() + b"\n")
    after = ck3.schema_manifest()
    assert after["hash"] != before["hash"]
    assert after["originals_changed"] == ["trait.json"]
    report = ck3.analyze_ck3([], [])
    assert "schema_source_changed" in kinds(report)
    assert not report["coverage"]["production_export_enabled"]


def test_script_inspection_never_executes_eu5_modes_or_selects_winners():
    inputs = [source("A", "common/traits/same.txt", "REPLACE:example={genetic=yes}\nexample={genetic=yes}\n"),
              source("B", "common/traits/same.txt", "example={genetic=no}\n")]
    before = copy.deepcopy(inputs)
    for order in (["A", "B"], ["B", "A"]):
        report = ck3.analyze_ck3(inputs, list(order))
        assert {"overlapping_path", "duplicate_definition"} <= kinds(report)
        assert report["graphs"]["operation"] == []
        assert all(file["active"] and file["shadowed_by"] is None for file in report["files"])
        assert all(definition["state"] == "unknown" and definition["value"] is None for definition in report["definitions"])
        assert "game/trait/REPLACE:example" in {definition["key"] for definition in report["definitions"]}
        assert all(record["mode"] == "declaration" for record in report["source_definitions"])
        assert all(obligation["required"] and obligation["state"] == "unknown" for obligation in report["obligations"])
        assert report["profile"]["kind"] == "documentation_only"
        assert report["profile"]["id"] == "ck3-advisory-v1"
        assert report["coverage"]["conformed_rules"] == report["summary"]["game_runs"] == 0
        assert not report["profile"]["production_export_enabled"]
    assert inputs == before


def test_repeated_declarations_in_one_file_keep_occurrence_identity():
    report = ck3.analyze_ck3([source("A", "common/traits/a.txt", "a={x=1} a={x=2}")], ["A"])
    assert "duplicate_definition" in kinds(report)
    assert [record["ordinal"] for record in report["source_definitions"]] == [0, 1]
    assert report["source_definitions"][0]["span"] != report["source_definitions"][1]["span"]


def test_advisory_schema_accepts_inspected_alternatives_without_coercion():
    report = ck3.analyze_ck3([
        source("A", "common/traits/a.txt", "example={ category=education genetic=yes desc={desc=example_desc} diplomacy=@[2+2] unknown_field={a=1 a=2} }"),
        source("A", "events/a.txt", "namespace=example example.1={type=activity_event title={desc=example_title} desc={desc=example_desc} option={name=example_option}}"),
        source("A", "common/religion/religion_types/a.txt", "example={family=example_family faiths={example_faith={holy_site=a holy_site=b}}}"),
        source("A", "common/on_action/a.txt", "example={fallback=other on_actions={other}}"),
    ], ["A"])
    assert not {"schema_missing_field", "schema_field_shape", "schema_enum_advisory"} & kinds(report)
    assert "game/event/namespace" not in {definition["key"] for definition in report["definitions"]}
    json.dumps(report)  # Public projection contains no document objects or raw bytes.


def test_schema_diagnostics_are_advisory_and_skip_recovered_regions():
    good = source("A", "common/decisions/a.txt", "example={major={a=1}}")
    malformed = source("A", "common/decisions/b.txt", "broken={major={a=1}")
    report = ck3.analyze_ck3([good, malformed], ["A"])
    assert {"schema_missing_field", "schema_field_shape", "parse_diagnostic"} <= kinds(report)
    assert all(issue["category"] == "potential_incompatibility" for issue in report["findings"])
    assert not any(issue["target"] == "game/decision/broken" and issue["kind"].startswith("schema_") for issue in report["findings"])


def test_literal_reference_missing_only_when_target_family_is_indexed():
    ref = source("A", "common/traits/a.txt", "example={parent=missing}")
    missing = ck3.analyze_ck3([ref], ["A"])
    edge = missing["graphs"]["definition"][0]
    assert edge["resolution_state"] == "missing_in_snapshot"
    assert edge["resolved"] is None
    assert "literal_reference_advisory" in kinds(missing)
    unindexed = ck3.analyze_ck3([source("A", "events/a.txt", "example.1={theme=unseen}")], ["A"])
    assert unindexed["graphs"]["definition"][0]["resolution_state"] == "family_unindexed"
    assert "literal_reference_advisory" not in kinds(unindexed)
    present = ck3.analyze_ck3([ref, source("B", "common/traits/b.txt", "missing={}")], ["A", "B"])
    assert present["graphs"]["definition"][0]["resolution_state"] == "candidate_present"
    dynamic = ck3.analyze_ck3([source("A", "common/traits/a.txt", 'example={parent="$name$"}')], ["A"])
    assert dynamic["graphs"]["definition"][0]["target"] is None


def test_descriptors_dependencies_cycles_masks_and_disabled_sources_are_inspected():
    inputs = [source("A", "descriptor.mod", 'name="Alpha" dependencies={"Beta" "Missing"} replace_path="common/traits"'),
              source("B", "descriptor.mod", 'name="Beta" dependencies={"Alpha"}'),
              source("A", "common/traits/a.txt", "a={}"),
              source("B", "common/traits/b.txt", "b={}")]
    report = ck3.analyze_ck3(inputs, ["A", "B"])
    assert {"missing_dependency", "dependency_cycle", "replace_path_scope"} <= kinds(report)
    assert all(edge["order_semantics"] == "unknown" for edge in report["graphs"]["package"])
    mask = next(issue for issue in report["findings"] if issue["kind"] == "replace_path_scope")
    assert len(mask["affected_file_ids"]) == 1
    disabled = ck3.analyze_ck3(inputs, ["A"])
    assert "disabled_dependency" in kinds(disabled)
    assert len(disabled["source_definitions"]) == 2
    assert not next(file for file in disabled["files"] if file["owner"] == "B")["active"]


def test_registry_metadata_overrides_payload_metadata_and_pins_manifest():
    inputs = [source("A", "descriptor.mod", 'name="Payload" dependencies={"Absent"}')]
    raw = b'name="Registry" dependencies={"Registry"}'
    metadata = [{"owner": "A", "descriptor_path": "/captured/mod/local.mod", "bytes_base64": base64.b64encode(raw).decode(), "sha256": digest(raw)}]
    before = copy.deepcopy(metadata)
    report = ck3.analyze_ck3(inputs, ["A"], package_metadata=metadata)
    assert report["package_metadata"][0]["data"]["name"] == ["Registry"]
    assert report["package_metadata"][0]["source"] == "registry_descriptor"
    assert "missing_dependency" not in kinds(report)
    assert report["files"][0]["metadata"]["name"] == ["Payload"]
    assert report["input_manifest_hash"] != ck3.analyze_ck3(inputs, ["A"])["input_manifest_hash"]
    assert metadata == before
    metadata[0]["sha256"] = "0" * 64
    assert "invalid_input" in kinds(ck3.analyze_ck3(inputs, ["A"], package_metadata=metadata))


def test_ambiguous_dependency_name_is_preserved_as_ambiguous():
    report = ck3.analyze_ck3([
        source("A", "descriptor.mod", 'name="Alpha" dependencies={"Shared"}'),
        source("B", "descriptor.mod", 'name="Shared"'),
        source("C", "descriptor.mod", 'name="Shared"'),
    ], ["A", "B", "C"])
    assert "ambiguous_dependency" in kinds(report)
    assert report["graphs"]["package"][0]["owners"] == ["B", "C"]


def test_localization_keeps_duplicate_keys_tiers_and_original_spelling():
    report = ck3.analyze_ck3([
        source("A", "localization/english/a_l_english.yml", b'\xef\xbb\xbfl_english:\r\n label:0 "A # quoted"\r\n label:0 "B"\r\n'),
        source("B", "localization/replace/b_l_english.yml", b'\xef\xbb\xbfl_english:\n label:0 "C"\n'),
    ], ["A", "B"])
    assert "localization_overlap" in kinds(report)
    assert report["files"][0]["newline"] == "CRLF"
    assert [entry["ordinal"] for entry in report["files"][0]["entries"]] == [0, 1]
    assert report["files"][0]["entries"][0]["value"] == "A # quoted"
    assert report["definitions"][0]["state"] == "unknown"


@pytest.mark.parametrize("platform", ["macos", "windows"])
def test_cross_platform_aliases_are_advisory_and_never_coalesce_source_bytes(platform):
    inputs = [source("A", "common/traits/A.txt", "a={}"), source("A", "common/traits/a.txt", "b={}"),
              source("A", "common/traits/CON.txt", "c={}"), source("A", "common/traits/a:b.txt", "d={}"),
              source("A", "common/traits/trailing .txt ", "e={}"), source("A", "other/back\\slash.txt", b"bytes")]
    report = ck3.analyze_ck3(inputs, ["A"], target_platform=platform)
    assert report["summary"]["files"] == len(inputs)
    assert {"portability", "windows_path_alias"} <= kinds(report)
    assert {file["path"] for file in report["files"]} == {item["path"] for item in inputs}
    assert not any(file["shadowed_by"] for file in report["files"])


@pytest.mark.parametrize("path", ["../outside.txt", "/absolute.txt", "a/../b.txt", "a//b.txt", "a/\x00.txt"])
def test_invalid_paths_fail_before_any_io(path):
    report = ck3.analyze_ck3([source("A", path, b"source")], ["A"])
    assert report["summary"]["state"] == "invalid_input"
    assert report["files"] == []


def test_invalid_hash_base64_duplicate_and_opaque_inputs_fail_closed():
    valid = source("A", "common/traits/a.txt", "a={}")
    wrong_hash = {**source("B", "a.txt", b"bad"), "sha256": "0" * 64}
    invalid_base64 = {"owner": "B", "path": "b.txt", "bytes_base64": "not base64"}
    opaque = {"owner": "C", "path": "gfx/a.dds", "sha256": "a" * 64, "opaque_blob": {"sha256": "a" * 64, "size": 5}}
    report = ck3.analyze_ck3([valid, valid, wrong_hash, invalid_base64, opaque], ["A", "B", "C"])
    assert len([issue for issue in report["findings"] if issue["kind"] == "invalid_input"]) == 3
    assert len(report["files"]) == 2
    assert report["files"][1]["opaque_blob"] == opaque["opaque_blob"]


def test_game_or_profile_context_changes_alter_manifest_and_zero_runtime_claims():
    inputs = [source("A", "common/traits/a.txt", "a={}")]
    mac = ck3.analyze_ck3(inputs, ["A"], "macos")
    windows = ck3.analyze_ck3(inputs, ["A"], "windows")
    assert mac["input_manifest_hash"] != windows["input_manifest_hash"]
    assert mac["profile"]["hash"] != windows["profile"]["hash"]
    assert mac["coverage"]["supported_families"] == []
    assert mac["coverage"]["conformed_rules"] == mac["coverage"]["game_runs"] == mac["summary"]["llm_calls"] == 0
    with pytest.raises(ValueError, match="unique"):
        ck3.analyze_ck3(inputs, ["A", "A"])
    with pytest.raises(ValueError, match="platform"):
        ck3.analyze_ck3(inputs, ["A"], "linux")


def test_missing_playset_owners_prevent_false_clean_inspection():
    report = ck3.analyze_ck3([], ["missing"])
    assert "playset_owner_unavailable" in kinds(report)
    assert report["summary"]["state"] == "needs_attention"


def test_gui_named_base_heads_are_indexed_and_history_dates_are_file_scoped():
    report = ck3.analyze_ck3([
        source("A", "gui/a.gui", 'types={type panel = base_window { name="a" }}'),
        source("B", "gui/b.gui", 'types={type panel = base_window { name="b" }}'),
        source("A", "history/titles/a.txt", "1066.1.1={holder=1}"),
        source("B", "history/titles/b.txt", "1066.1.1={holder=2}"),
    ], ["A", "B"])
    duplicates = [issue for issue in report["findings"] if issue["kind"] == "duplicate_definition"]
    assert [issue["target"] for issue in duplicates] == ["game/gui/type:panel"]
    history = [definition for definition in report["definitions"] if definition["family"] == "history/titles"]
    assert len(history) == 2
    assert all(definition["identity_state"] == "provisional" for definition in history)


def test_recovered_source_reference_cannot_claim_literal_target_is_missing():
    report = ck3.analyze_ck3([
        source("A", "common/traits/a.txt", "valid={}"),
        source("A", "common/traits/b.txt", "broken={parent=missing"),
    ], ["A"])
    assert report["graphs"]["definition"][0]["resolution_state"] == "source_unparsed"
    assert report["graphs"]["definition"][0]["certainty"] == "recovered"
    assert "literal_reference_advisory" not in kinds(report)


def test_oversized_symbols_remain_preserved_but_outside_semantic_index():
    raw = ("a" * 4097 + "={parent=" + "b" * 4097 + "}").encode()
    inputs = [source("A", "common/traits/a.txt", raw)]
    report = ck3.analyze_ck3(inputs, ["A"])
    assert report["definitions"] == []
    assert "symbol_coverage_unknown" in kinds(report)
    assert report["coverage"]["partially_indexed_files"] == [report["files"][0]["id"]]
    assert report["files"][0]["sha256"] == digest(raw)
    assert base64.b64decode(inputs[0]["bytes_base64"]) == raw


def test_coordinate_projection_size_does_not_duplicate_nested_script_bodies():
    reports = []
    for repetitions in (10, 10_000):
        raw = b"effect={nested={" + b" repeated={x=1 x=2} " * repetitions + b"}}\n"
        report = ck3.analyze_ck3([source("A", "common/scripted_effects/a.txt", raw)], ["A"])
        reports.append(report)
        record = report["source_definitions"][0]
        assert record["child_count"] == 1
        assert "occurrences" not in record and "children" not in record
        assert all("children" not in item for item in report["files"][0]["occurrences"])
        assert report["coverage"]["derived_projection"]["recursive_trees_stored"] is False
        assert report["coverage"]["cst_reconstruction"]["changes_semantic_coverage"] is False
        assert report["profile"]["adapter_version"] == "ck3-inspection-2"
    # The larger body has 1,000 times as many nested repetitions. Its derived
    # report grows only by bounded snippet/coordinate spelling, not body trees.
    assert len(json.dumps(reports[1])) < len(json.dumps(reports[0])) + 1024


def test_complete_definition_occurrences_reconstruct_from_hash_and_whole_document_coordinates():
    raw = b"\xef\xbb\xbfeffect={x=01 x=2 nested={y=3 y=4}}\r\neffect={x=5}\r\n"
    report = ck3.analyze_ck3([source("A", "common/scripted_effects/a.txt", raw)], ["A"])
    rebuilt = parse(raw)
    assert rebuilt.serialize() == raw
    records = report["source_definitions"]
    assert len(records) == 2
    assert [record["ordinal"] for record in records] == [0, 1]
    for record in records:
        reference = record["cst_reference"]
        assert reference["sha256"] == rebuilt.sha256 == digest(raw)
        assert reference["parser_version"] == PARSER_VERSION
        node = next(node for node in rebuilt.children if list(node.span) == reference["span"] and node.ordinal == reference["ordinal"])
        assert node.start == record["span"][0] and len(node.children) == record["child_count"]
        assert raw[node.start:node.end] == rebuilt.raw[node.start:node.end]
    assert [child.ordinal for child in rebuilt.children[0].children if child.key == "x"] == [0, 1]
    assert [child.value for child in rebuilt.children[0].children if child.key == "x"] == ["01", "2"]
    assert report["definitions"][0]["occurrences"] == [
        {"owner": "A", "file_id": records[0]["file_id"], "span": records[0]["span"], "ordinal": 0},
        {"owner": "A", "file_id": records[1]["file_id"], "span": records[1]["span"], "ordinal": 1},
    ]


def test_coordinate_preview_limit_never_removes_definition_records():
    raw = b"".join(f"effect_{index}={{x=1}}\n".encode() for index in range(257))
    report = ck3.analyze_ck3([source("A", "common/scripted_effects/a.txt", raw)], ["A"])
    assert len(report["definitions"]) == len(report["source_definitions"]) == 257
    file = report["files"][0]
    assert len(file["occurrences"]) == 200
    assert file["occurrence_count"] == 257 and file["occurrences_truncated"]
    assert report["source_definitions"][-1]["key"] == "game/scripted_effect/effect_256"
    assert file["cst_reference"]["span"] == [0, len(raw)]


def test_analyzer_descriptor_entries_are_shallow_but_standalone_api_remains_lossless():
    raw = b'name="Example" unknown={a={b=1 b=2}} replace_path="history" replace_path="common"'
    standalone = ck3.parse_descriptor(raw)
    assert standalone["document"].serialize() == raw
    assert standalone["entries"][1]["children"][0]["children"][1]["ordinal"] == 1
    report = ck3.analyze_ck3([source("A", "descriptor.mod", raw)], ["A"])
    entries = report["files"][0]["entries"]
    assert all("children" not in entry for entry in entries)
    assert entries[1]["child_count"] == 1
    assert entries[2]["ordinal"] == 0 and entries[3]["ordinal"] == 1
    assert report["files"][0]["metadata"]["replace_path"] == ["history", "common"]
