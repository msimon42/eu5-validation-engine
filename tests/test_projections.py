import base64
import copy

from backend.app.projections import scan_projection, candidate_projection, discovery_projection


def test_scan_projection_is_paginated_but_retains_full_coverage_counts():
    raw = b"x" * 20000
    files = [{"id": str(index), "owner": "A", "path": f"{index}.txt"} for index in range(205)]
    record = {"analysis": {"files": files, "definitions": [], "findings": [], "obligations": [], "coverage": {"conformed_rules": 0}, "summary": {"files": 205}},
        "inputs": [{"owner": "A", "path": file["path"], "bytes_base64": base64.b64encode(raw).decode()} for file in files]}
    view = scan_projection(record)
    assert len(view["analysis"]["files"]) == 100
    assert view["analysis"]["summary"]["files"] == 205
    assert view["analysis"]["pagination"]["has_more"]
    assert len(base64.b64decode(view["inputs"][0]["bytes_base64"])) == 8192
    assert view["inputs"][0]["preview_only"]
    last = scan_projection(record, offset=200)
    assert len(last["analysis"]["files"]) == 5 and not last["analysis"]["pagination"]["has_more"]
    assert len(record["analysis"]["files"]) == 205


def test_candidate_display_does_not_send_entire_original_installation():
    candidate = {"inputs": [{"owner": "V", "path": "a", "sha256": "hash", "bytes_base64": "private"}],
        "plan": {"before": {"huge": "data"}, "after": {}, "files": []}}
    view = candidate_projection(candidate)
    assert "bytes_base64" not in view["inputs"][0]
    assert "before" not in view["plan"]
    assert "before" in candidate["plan"]


def test_ck3_display_bounds_descriptors_and_retains_complete_records():
    descriptor = {"owner": "A", "path": "descriptor.mod", "metadata": {"name": "x" * 300000},
                  "entries": [{"value": "y" * 300000}]}
    record = {"analysis": {"files": [descriptor], "package_metadata": [descriptor] * 150,
                          "graphs": {"package": [{"target": "z" * 300000}]}}, "inputs": []}
    view = scan_projection(record)
    assert view["analysis"]["files"][0]["display_truncated"]
    assert "entries" not in view["analysis"]["files"][0]
    assert len(view["analysis"]["package_metadata"]) == 100
    assert view["analysis"]["pagination"]["totals"]["package_metadata"] == 150
    assert len(view["analysis"]["graphs"]["package"][0]["target"]) < 9000
    assert len(record["analysis"]["package_metadata"]) == 150
    assert len(descriptor["metadata"]["name"]) == 300000
    discovery = {"mods": [{"name": "a" * 300000}] * 600,
                 "metadata_inputs": [{"bytes_base64": "private", "sha256": "hash"}]}
    display = discovery_projection(discovery)
    assert display["display_totals"]["mods"] == 600 and display["display_truncated"]
    assert len(display["mods"]) == 500 and len(display["mods"][0]["name"]) < 9000
    assert "bytes_base64" not in display["metadata_inputs"][0]


def test_ck3_finding_display_prioritizes_inventory_and_conflicts_before_pagination():
    findings = [
        {"id": "schema-first", "kind": "schema_type_advisory"},
        {"id": "reference", "kind": "literal_reference_advisory"},
        {"id": "overlap-first", "kind": "overlapping_path"},
        {"id": "missing", "kind": "mod_payload_unavailable", "coverage": "discovery"},
        {"id": "parser", "kind": "parse_diagnostic"},
        {"id": "overlap-second", "kind": "duplicate_definition"},
        {"id": "path", "kind": "portability"},
        {"id": "schema-second", "kind": "schema_missing_field"},
    ]
    record = {"game_id": "ck3", "analysis": {"findings": findings, "summary": {"findings": len(findings)}}, "inputs": []}
    expected = ["missing", "path", "overlap-first", "overlap-second", "parser", "schema-first", "reference", "schema-second"]
    paginated = [row["id"] for offset in range(0, len(findings), 3)
                 for row in scan_projection(record, offset=offset, limit=3)["analysis"]["findings"]]
    assert paginated == expected
    assert [row["id"] for row in findings] == [
        "schema-first", "reference", "overlap-first", "missing", "parser", "overlap-second", "path", "schema-second"]
    assert len(set(paginated)) == len(findings)
    assert scan_projection(record)["analysis"]["summary"] == {"findings": len(findings)}
    eu5 = {**record, "game_id": "eu5"}
    assert scan_projection(eu5)["analysis"]["findings"] == findings


def test_legacy_ck3_discovery_display_recovers_names_without_changing_ids_or_references():
    diagnostics = [{"code": "mod_payload_unavailable", "registry_path": f"mod/{name}.mod",
                    "severity": "error", "message": "directory is absent"} for name in ("one", "two")]
    rows = [{"id": "legacy-duplicate", "kind": "mod_payload_unavailable", "coverage": "discovery",
             "target": "CK3 launcher", "message": "directory is absent",
             "source_occurrences": [{"id": "retained-reference"}]} for _ in diagnostics]
    record = {"game_id": "ck3", "inputs": [], "analysis": {"findings": rows,
        "discovery": {"id": "discovery-old", "configuration_hash": "old-hash", "diagnostics": diagnostics},
        "package_metadata": [{"owner": f"ck3:mod/{name}.mod", "path": f"mod/{name}.mod", "sha256": name,
                              "data": {"name": [name.title()]}} for name in ("one", "two")]}}
    before = copy.deepcopy(record)
    displayed = scan_projection(record)["analysis"]["findings"]
    assert [row["id"] for row in displayed] == ["legacy-duplicate", "legacy-duplicate"]
    assert len({row["display_key"] for row in displayed}) == 2
    assert [row["display_title"] for row in displayed] == ["One · Mod payload unavailable", "Two · Mod payload unavailable"]
    assert [row["display_target"] for row in displayed] == ["mod/one.mod", "mod/two.mod"]
    for row, diagnostic in zip(displayed, diagnostics, strict=True):
        assert row["target"] == "CK3 launcher" and row["message"] == "directory is absent"
        assert row["source_occurrences"] == [{"id": "retained-reference"}]
        assert row["diagnostic"] == diagnostic and row["severity"] == "error"
    assert record == before
    assert scan_projection(record, offset=1, limit=1)["analysis"]["findings"] == displayed[1:]


def test_legacy_discovery_display_refuses_unproven_diagnostic_pairing():
    for diagnostics in ([{"code": "other_kind", "registry_path": "mod/one.mod"}], [],
                        [{"code": "mod_payload_unavailable"}, {"code": "mod_payload_unavailable"}]):
        record = {"game_id": "ck3", "inputs": [], "analysis": {"findings": [
            {"id": "retained", "kind": "mod_payload_unavailable", "coverage": "discovery", "target": "CK3 launcher"}],
            "discovery": {"diagnostics": diagnostics}}}
        before = copy.deepcopy(record)
        row = scan_projection(record)["analysis"]["findings"][0]
        assert row["id"] == "retained" and row["target"] == "CK3 launcher"
        assert "display_title" not in row and "diagnostic" not in row
        assert record == before
