import base64
import copy

import pytest

from backend.engine.analysis import analyze
from backend.engine.fixtures import load_fixture, _input, D
from backend.engine.planner import plan_repair


def run(case, decisions=None):
    analysis = analyze(case["inputs"], case["playset"], case["profile"], case.get("baselines"))
    return analysis, plan_repair(analysis, case["inputs"], decisions)


def test_disjoint_exact_ancestry_merges_full_stack_without_mutating_sources():
    case = load_fixture("F03")
    original = copy.deepcopy(case["inputs"])
    before, plan = run(case)
    assert before["definitions"][0]["value"] == {"x": "1", "y": "3"}
    assert plan["status"] == "repair_expected"
    assert base64.b64decode(plan["files"][0]["bytes_base64"]) == b"REPLACE:item = { x = 2 y = 3 }\n"
    assert plan["after"]["definitions"][0]["value"] == {"x": "2", "y": "3"}
    assert {o["owner"] for o in plan["obligations"]} == {"A", "B"}
    assert all(o["state"] == "satisfied" for o in plan["obligations"])
    assert case["inputs"] == original
    assert len(plan["read_set"]) == 3 and len(plan["write_set"]) == 1
    assert not plan["production_export_enabled"]


@pytest.mark.parametrize("missing", ["baseline", "owner_ancestry", "independence"])
def test_missing_proof_never_writes(missing):
    case = load_fixture("F03")
    if missing == "baseline":
        case["baselines"] = {}
    elif missing == "owner_ancestry":
        case["baselines"]["in_game/testdb/item"]["author_base_hashes"].pop("A")
    else:
        case["profile"]["independent_fields"] = []
    _, plan = run(case)
    assert plan["status"] in {"blocked_unknown", "blocked_design"}
    assert not plan["files"] and not plan["write_set"]


def test_concrete_conflict_choice_requires_current_hashes_and_exact_waiver():
    case = load_fixture("F04")
    analysis, blocked = run(case)
    assert blocked["status"] == "blocked_design"
    a_obligation = next(o for o in analysis["obligations"] if o["owner"] == "A")
    decision = {"in_game/testdb/item": {"values": {"x": "5"}, "waive": [a_obligation["id"]],
                 "input_manifest_hash": analysis["input_manifest_hash"], "profile_hash": analysis["profile"]["hash"], "reason": "Choose B's exact target"}}
    approved = plan_repair(analysis, case["inputs"], decision)
    assert approved["status"] == "repair_expected"
    assert approved["after"]["definitions"][0]["value"] == {"x": "5", "y": "1"}
    assert next(o for o in approved["obligations"] if o["owner"] == "A")["state"] == "waived_by_user"
    assert next(o for o in approved["obligations"] if o["owner"] == "B")["state"] == "satisfied"
    decision["in_game/testdb/item"]["input_manifest_hash"] = "stale"
    assert plan_repair(analysis, case["inputs"], decision)["status"] == "blocked_design"


def test_repeated_occurrence_alignment_preserves_execution_order():
    case = load_fixture("F06")
    _, plan = run(case)
    assert plan["status"] == "repair_expected"
    sequence = plan["after"]["definitions"][0]["value"]["effect"]
    assert [(n["key"], n["value"]) for n in sequence] == [("add", "4"), ("multiply", "2"), ("add", "5")]
    value = 0
    for node in sequence:
        value = value + int(node["value"]) if node["key"] == "add" else value * int(node["value"])
    assert value == 13
    case["inputs"][1] = _input("A", D+"10.txt", "REPLACE:item={effect={add=4 add=3 multiply=2}}\n")
    _, ambiguous = run(case)
    assert ambiguous["status"] in {"blocked_unknown", "blocked_design"}
    assert not ambiguous["files"]


def test_source_update_invalidates_plan_including_unaffected_other_input():
    case = load_fixture("F19")
    analysis, plan = run(case)
    assert plan["status"] == "repair_expected"
    updated = [case["updates"][0] if item["owner"] == "A" else item for item in case["inputs"]]
    stale = plan_repair(analysis, updated)
    assert stale["status"] == "blocked_unknown"
    assert "Stale" in stale["reason"]
    assert stale["files"] == []


def test_downstream_replacement_can_erase_generated_patch_and_is_detected():
    case = load_fixture("F03")
    case["inputs"].append(_input("C", D+"zzzz_after.txt", "REPLACE:item={x=1 y=3}\n"))
    case["playset"].insert(2, "C")
    base = case["baselines"]["in_game/testdb/item"]
    base["author_base_hashes"]["C"] = base["source_hash"]
    analysis, plan = run(case)
    assert plan["status"] in {"blocked_design", "blocked_unknown"}
    assert not plan["files"]


def test_unknown_unrelated_obligations_are_retained_and_never_downgraded_optional():
    case = load_fixture("F18")
    before, plan = run(case)
    unknowns = [o for o in before["obligations"] if o["state"] == "unknown"]
    assert unknowns
    assert plan["status"] == "repair_expected"
    assert plan["validation_blockers"]
    assert {o["id"] for o in unknowns} <= {o["id"] for o in plan["obligations"]}
    assert all(o["required"] for o in plan["obligations"])
    assert not plan["production_export_enabled"]


def test_known_nested_reader_and_approved_combined_intent_remain_distinct_from_injection():
    case = load_fixture("F05")
    case["profile"]["readers"]["nested"] = "named_members"
    original, no_patch = run(case)
    assert original["definitions"][0]["value"]["nested"] == {"a": "2", "b": "3"}
    assert no_patch["status"] == "no_repair_needed"
    case["inputs"][1] = _input("A", D+"10.txt", "REPLACE:item = { nested = { a = 2 b = 1 } }\n")
    before, blocked = run(case)
    assert before["definitions"][0]["value"]["nested"] == {"a": "2", "b": "1"}
    assert blocked["status"] == "blocked_design"
    decision = {"in_game/testdb/item": {"values": {"nested": {"a": "2", "b": "3"}}, "waive": [],
                 "input_manifest_hash": before["input_manifest_hash"], "profile_hash": before["profile"]["hash"],
                 "reason": "Approve this concrete combined nested intent"}}
    plan = plan_repair(before, case["inputs"], decision)
    assert plan["status"] == "repair_expected"
    assert plan["after"]["definitions"][0]["value"]["nested"] == {"a": "2", "b": "3"}


def test_localization_approved_text_uses_separate_bom_replace_artifact():
    case = load_fixture("F11")
    case["profile"]["families"].append("localization")
    case["profile"]["localization"] = {"ordinary_filename": "first", "replacement_filename": "last", "replace_priority": True}
    before, blocked = run(case)
    assert blocked["status"] == "blocked_design"
    key = "main_menu/localization/english:item_name"
    a_obligation = next(o for o in before["obligations"] if o["owner"] == "A" and o["target"] == key)
    decision = {key: {"values": {"text": "Beta"}, "waive": [a_obligation["id"]],
                     "input_manifest_hash": before["input_manifest_hash"], "profile_hash": before["profile"]["hash"], "reason": "Choose Beta label"}}
    plan = plan_repair(before, case["inputs"], decision)
    assert plan["status"] == "repair_expected", plan["reason"]
    assert base64.b64decode(plan["files"][0]["bytes_base64"]).startswith(b'\xef\xbb\xbfl_english:\n item_name:0 "Beta"')
    assert "/replace/" in plan["files"][0]["path"]
    retained = next(d for d in plan["after"]["definitions"] if d["localization_key"] == "retained")
    assert retained["value"] == {"text": "Keep"}


def test_gui_three_way_same_file_preserves_unrelated_widget_and_exact_layout():
    from backend.engine.fixtures import _seed_case
    profile = load_fixture("F01")["profile"]
    profile["families"].append("gui")
    profile["readers"]["name"] = "scalar_last"
    profile["independent_fields"].append("name")
    profile["gui"] = {"duplicate_definition": "playset_last", "composition": "pinned_disjoint_fields"}
    case = _seed_case(12, "Known disjoint GUI", [
        ("V", "in_game/gui/test.gui", 'type foo = base { name = "foo" }\ntype bar = base { name = "bar" }\n'),
        ("A", "in_game/gui/test.gui", 'type foo = base { name = "foo A" }\ntype bar = base { name = "bar" }\n'),
        ("B", "in_game/gui/test.gui", '# keep B layout\ntype foo = base { name = "foo" }\ntype bar = base { name = "bar B" }\n')
    ], profile=profile, pinned=True)
    before, plan = run(case)
    assert plan["status"] == "repair_expected", plan["reason"]
    assert plan["files"][0]["path"] == "in_game/gui/test.gui"
    raw = base64.b64decode(plan["files"][0]["bytes_base64"])
    assert raw == b'# keep B layout\ntype foo = base { name = "foo A" }\ntype bar = base { name = "bar B" }\n'
    assert {d["id"]: d["value"] for d in plan["after"]["definitions"]} == {"foo": {"name": "foo A"}, "bar": {"name": "bar B"}}
    assert all(o["state"] == "satisfied" for o in plan["obligations"])


def test_pinned_field_deletion_is_an_intent_and_removes_only_its_statement():
    from backend.engine.fixtures import _seed_case
    case = _seed_case(3, "Disjoint deletion", [
        ("V", D+"00.txt", "item={x=1 y=1}\n"),
        ("A", D+"10.txt", "REPLACE:item={x=1}\n"),
        ("B", D+"20.txt", "REPLACE:item={x=2 y=1 # keep the comment\n}\n")
    ], pinned=True)
    before, plan = run(case)
    deletion = next(o for o in before["obligations"] if o["owner"] == "A")
    assert deletion["kind"] == "field_absence" and deletion["expected"] is None
    assert plan["status"] == "repair_expected", plan["reason"]
    assert plan["after"]["definitions"][0]["value"] == {"x": "2"}
    assert b"# keep the comment" in base64.b64decode(plan["files"][0]["bytes_base64"])
