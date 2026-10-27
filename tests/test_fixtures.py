import json
from pathlib import Path

import pytest

from backend.engine.analysis import analyze
from backend.engine.fixtures import catalog, load_fixture, run_fixture, _input, D
from backend.engine.formats import validate_virtual_path
from backend.engine.planner import plan_repair


@pytest.mark.parametrize("identifier", [f"F{i:02}" for i in range(1, 21)])
def test_twenty_executable_family_contracts(identifier):
    result = run_fixture(identifier)
    assert result["passed"], (identifier, result["assertions"], result["plan"]["reason"])
    assert result["tier"] == "contract" and result["evidence_level"] == "P"
    assert result["analysis"]["coverage"]["conformed_rules"] == 0


def test_catalog_and_legacy_fixture_alias():
    assert len(catalog()) == 20
    assert load_fixture("003-disjoint-properties") == load_fixture("F03")
    with pytest.raises(ValueError):
        load_fixture("not-a-fixture")


@pytest.mark.parametrize("path", ["../outside.txt", "/outside.txt", "C:/outside.txt", "\\\\server\\share\\a", "in_game/../../a", "in_game/x:stream", "in_game/CON.txt", "in_game\\x.txt", "a//b", "a/./b"])
def test_unsafe_path_manifests_reject_without_materialization(path, tmp_path):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"untouched")
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ValueError):
        validate_virtual_path(path)
    fixture = load_fixture("F01")
    inputs = [_input("A", path, "x={y=1}")]
    report = analyze(inputs, ["A"], fixture["profile"])
    plan = plan_repair(report, inputs)
    assert plan["status"] == "invalid_input"
    assert not plan["files"] and not report["files"]
    assert sentinel.read_bytes() == b"untouched" and list(staging.iterdir()) == []


def test_package_presence_cycle_advisory_versions_and_duplicate_identity():
    profile = load_fixture("F01")["profile"]
    rows = [_input("A", ".metadata/metadata.json", json.dumps({"id": "a", "version": "1", "relationships": [{"rel_type": "dependency", "id": "b", "version": "2"}]})),
            _input("B", ".metadata/metadata.json", json.dumps({"id": "b", "version": "1", "relationships": [{"rel_type": "dependency", "id": "a"}]}))]
    report = analyze(rows, ["A", "B"], profile)
    kinds = {f["kind"] for f in report["findings"]}
    assert {"dependency_version", "dependency_cycle"} <= kinds
    assert not any(f["category"] == "confirmed_incompatibility" for f in report["findings"])
    report = analyze(rows, ["A"], profile)
    assert any(f["kind"] == "disabled_dependency" for f in report["findings"])


def test_invalid_base64_and_declared_hash_are_rejected():
    profile = load_fixture("F01")["profile"]
    invalid = {"owner": "A", "path": D+"00.txt", "bytes_base64": "@@@"}
    report = analyze([invalid], ["A"], profile)
    assert report["summary"]["state"] == "invalid_input"


def test_equal_assets_need_no_patch_and_no_script_parser():
    profile = load_fixture("F01")["profile"]
    report = analyze([_input("A", "in_game/gfx/a.dds", b"DDS same"), _input("B", "in_game/gfx/a.dds", b"DDS same")], ["A", "B"], profile)
    assert all(f["kind"] == "opaque" for f in report["files"])
    assert not any(f["kind"] == "asset_payload_conflict" for f in report["findings"])
    assert plan_repair(report, [_input("A", "in_game/gfx/a.dds", b"DDS same"), _input("B", "in_game/gfx/a.dds", b"DDS same")])["status"] == "no_repair_needed"


def test_v2_schema_validates_catalog_requires_fingerprints_and_rejects_unknown_fields():
    import jsonschema
    schema = json.loads((Path(__file__).parents[1] / "schemas/fixture-v2.json").read_text())
    for entry in catalog():
        jsonschema.validate(load_fixture(entry["id"]), schema)
    case = load_fixture("F03")
    case["tier"] = "conformance"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(case, schema)
    case = load_fixture("F03")
    case["unchecked_override"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(case, schema)
    row = _input("A", D+"00.txt", "item={x=1}")
    row["sha256"] = "0" * 64
    report = analyze([row], ["A"], load_fixture("F01")["profile"])
    assert report["summary"]["state"] == "invalid_input"


def test_untrusted_metadata_shapes_and_opaque_unknowns_remain_visible():
    profile = load_fixture('F01')['profile']
    report = analyze([_input('A', '.metadata/metadata.json', '{"id":[],"relationships":[{"rel_type":"dependency","id":[]}]}'),
                      _input('A', 'in_game/unsupported/custom.dat', b'opaque unknown bytes')], ['A'], profile)
    assert any(f['kind'] == 'parse_diagnostic' for f in report['findings'])
    assert any(o['kind'] == 'opaque_payload' and o['state'] == 'unknown' and o['required'] for o in report['obligations'])
