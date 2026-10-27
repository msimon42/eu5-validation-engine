"""Twenty executable synthetic families; none is an EU5 conformance observation."""
from __future__ import annotations

import base64
import copy
import json

from .loading import SYNTHETIC_PROFILE
from .parser import digest

D = "in_game/common/testdb/"


def _input(owner, name, text):
    raw = text.encode() if isinstance(text, str) else text
    return {"owner": owner, "path": name, "bytes_base64": base64.b64encode(raw).decode(), "sha256": digest(raw)}


def _seed_case(number, title, rows, *, playset=None, pinned=False, profile=None, expected=None):
    inputs = [_input(*row) for row in rows]
    selected = copy.deepcopy(profile or SYNTHETIC_PROFILE)
    selected.pop("hash", None)
    case = {"schema_version": 2, "id": f"F{number:02}", "title": title, "name": title,
            "tier": "contract", "profile": selected, "inputs": inputs,
            "playset": playset or ["A", "B", "generated_patch"], "baselines": {},
            "expected": {"disposition": "no_repair_needed", "finding_kinds": [], "effective": {},
                         "assertions": ["source_files_unchanged", "zero_llm_calls", "zero_game_runs"], **(expected or {})}}
    if pinned:
        base_inputs = [i for i in inputs if i["owner"] == "V"]
        for source in base_inputs:
            raw = base64.b64decode(source["bytes_base64"])
            from .parser import parse
            for node in parse(raw).children:
                if node.key and node.is_block:
                    from .formats import classify
                    family = classify(source["path"])["family"]
                    key = source["path"].split("/")[0] + "/" + family + "/" + node.key
                    case["baselines"][key] = {"source_hash": digest(raw),
                                              "author_base_hashes": {owner: digest(raw) for owner in ["A", "B"]}}
    return case


def _all():
    base = ("V", D + "00.txt", "item = { x = 1 y = 1 }\n")
    a = ("A", D + "10.txt", "REPLACE:item = { x = 2 y = 1 }\n")
    b = ("B", D + "20.txt", "REPLACE:item = { x = 1 y = 3 }\n")
    cases = []
    cases.append(_seed_case(1, "Independent mods", [("A", D+"10_a.txt", "alpha = { x = 1 }\n"), ("B", D+"20_b.txt", "beta = { y = 2 }\n")], expected={"effective": {"alpha": {"x": "1"}, "beta": {"y": "2"}}}))
    cases.append(_seed_case(2, "Identical overrides", [base, a, ("B", D+"20.txt", "REPLACE:item = { x = 2 y = 1 }\n")], pinned=True, expected={"finding_kinds": ["independent_intents"], "effective": {"item": {"x": "2", "y": "1"}}}))
    cases.append(_seed_case(3, "Disjoint properties", [base, a, b], pinned=True, expected={"disposition": "repair_expected", "effective_before_patch": {"item": {"x": "1", "y": "3"}}, "effective": {"item": {"x": "2", "y": "3"}}, "finding_kinds": ["independent_intents"]}))
    cases.append(_seed_case(4, "Contradictory scalar values", [base, a, ("B", D+"20.txt", "REPLACE:item = { x = 5 y = 1 }\n")], pinned=True, expected={"disposition": "blocked_design", "finding_kinds": ["contradictory_intents"]}))
    cases.append(_seed_case(5, "Nested reader remains unknown", [("V", D+"00.txt", "item = { nested = { a = 1 b = 1 } }\n"), ("A", D+"10.txt", "REPLACE_OR_CREATE:item = { nested = { a = 2 b = 1 } }\n"), ("B", D+"20.txt", "INJECT:item = { nested = { b = 3 } }\n")], pinned=True, expected={"disposition": "blocked_unknown", "finding_kinds": ["unproven_ancestry_or_reader"]}))
    sequence_profile = copy.deepcopy(SYNTHETIC_PROFILE)
    cases.append(_seed_case(6, "Ordered repeated occurrence merge", [("V", D+"00.txt", "item = { effect = { add = 1 multiply = 2 add = 3 } }\n"), ("A", D+"10.txt", "REPLACE:item = { effect = { add = 4 multiply = 2 add = 3 } }\n"), ("B", D+"20.txt", "REPLACE:item = { effect = { add = 1 multiply = 2 add = 5 } }\n")], pinned=True, profile=sequence_profile, expected={"disposition": "repair_expected", "finding_kinds": ["independent_intents"]}))
    cases.append(_seed_case(7, "Strict missing mode target", [("A", D+"10.txt", "INJECT:item = { y = 2 }\n")], expected={"disposition": "blocked_unknown", "finding_kinds": ["missing_operation_target"]}))
    cases.append(_seed_case(8, "Operation phase beats filename", [("V", D+"00_base.txt", "item = { x = 1 }\n"), ("A", D+"zz.txt", "INJECT:item = { y = 2 }\n"), ("B", D+"00b.txt", "REPLACE:item = { x = 3 }\n")], expected={"disposition": "blocked_unknown", "effective_before_patch": {"item": {"x": "3"}}}))
    cases.append(_seed_case(9, "Hidden helper reference loss", [("V", D+"00.txt", "helper = { x = 1 } item = { ref = helper }\n"), ("A", D+"00.txt", "item = { ref = helper }\n"), ("B", D+"20.txt", "second = { ref = helper }\n")], expected={"disposition": "blocked_unknown", "finding_kinds": ["missing_reference"]}))
    cases.append(_seed_case(10, "Required package absent", [("A", ".metadata/metadata.json", json.dumps({"id": "a", "version": "1", "relationships": [{"rel_type": "dependency", "id": "c", "version": "1.*"}]})), ("A", D+"10.txt", "alpha = { x = 1 }\n")], expected={"disposition": "blocked_unknown", "finding_kinds": ["missing_dependency"]}))
    cases.append(_seed_case(11, "Competing localization labels", [("A", "main_menu/localization/english/a_l_english.yml", b'\xef\xbb\xbfl_english:\n item_name:0 "Alpha # label"\n retained:0 "Keep"\n'), ("B", "main_menu/localization/english/b_l_english.yml", b'\xef\xbb\xbfl_english:\n item_name:0 "Beta"\n')], expected={"disposition": "blocked_design", "finding_kinds": ["localization_labels"]}))
    cases.append(_seed_case(12, "GUI whole-file hidden content", [("V", "in_game/gui/test.gui", 'type foo = default_block_window { name = "base" }\ntype bar = default_block_window { name = "bar" }\n'), ("A", "in_game/gui/test.gui", 'type foo = default_block_window { name = "changed" }\ntype bar = default_block_window { name = "bar" }\n'), ("B", "in_game/gui/test.gui", 'type foo = default_block_window { name = "base" }\n')], expected={"disposition": "blocked_unknown", "finding_kinds": ["exact_path_shadow"]}))
    cases.append(_seed_case(13, "Malformed syntax is byte-preserved", [("A", D+"10.txt", "item = { x = 1")], expected={"disposition": "blocked_unknown", "finding_kinds": ["parse_diagnostic"]}))
    cases.append(_seed_case(14, "Unsupported encoding blocks edits", [("A", D+"10.txt", b"\xff\xfei\x00t\x00e\x00m\x00")], expected={"disposition": "blocked_unknown", "finding_kinds": ["parse_diagnostic"]}))
    cases.append(_seed_case(15, "Windows filename aliases", [("A", D+"Foo.txt", "item = { x = 1 }\n"), ("B", D+"foo.txt", "item = { x = 2 }\n")], expected={"finding_kinds": ["windows_path_alias"], "disposition": "blocked_unknown"}))
    cases.append(_seed_case(16, "Unsafe manifest paths rejected", [("A", "../outside.txt", "item = { x = 1 }\n")], expected={"disposition": "invalid_input", "finding_kinds": ["invalid_input"]}))
    case17 = _seed_case(17, "Unsupported model repair cannot waive intent", [base, a, ("B", D+"20.txt", "REPLACE:item = { x = 5 y = 1 }\n")], pinned=True, expected={"disposition": "blocked_design", "finding_kinds": ["contradictory_intents"]})
    case17["agent_replay"] = {"proposal": {"tool": "shell", "arguments": {"command": "delete source"}}, "expected": "reject"}
    cases.append(case17)
    cases.append(_seed_case(18, "Unrelated contributions survive", [("V", D+"00.txt", "item = { x = 1 y = 1 } other = { y = 1 }\n"), ("A", D+"10.txt", "# preserve this comment\nREPLACE:item = { x = 2 y = 1 }\nREPLACE:other = { y = 7 mystery = opaque }\n"), b], pinned=True, expected={"disposition": "repair_expected", "finding_kinds": ["independent_intents"], "assertions": ["unrelated_unknown_obligation_retained", "source_files_unchanged"]}))
    case19 = _seed_case(19, "Stale source invalidates repair", [base, a, b], pinned=True, expected={"disposition": "repair_expected", "finding_kinds": ["independent_intents"]})
    case19["updates"] = [_input("A", D+"10.txt", "REPLACE:item = { x = 8 y = 1 }\n")]
    cases.append(case19)
    cases.append(_seed_case(20, "Opaque assets and shared rewards", [("A", "in_game/gfx/icon.dds", b"DDS \x00alpha"), ("B", "in_game/gfx/icon.dds", b"DDS \x00beta"), ("A", D+"10.txt", "hook_a = { effect = { add_reward = 1 } }\n"), ("B", D+"20.txt", "hook_b = { effect = { add_reward = 1 } }\n")], expected={"disposition": "blocked_design", "finding_kinds": ["asset_payload_conflict", "shared_reward_effects"]}))
    return cases


def catalog() -> list[dict]:
    return [{"id": case["id"], "title": case["title"], "name": case["title"], "tier": "contract",
             "description": case["title"], "expected_disposition": case["expected"]["disposition"]} for case in _all()]


def load_fixture(identifier: str = "003-disjoint-properties") -> dict:
    aliases = {"003-disjoint-properties": "F03", "fixture-003-disjoint-properties": "F03", "003": "F03", "3": "F03", "demo": "F03"}
    key = aliases.get(str(identifier), str(identifier).upper())
    if key.isdigit():
        key = "F" + key.zfill(2)
    for case in _all():
        if case["id"] == key:
            return copy.deepcopy(case)
    raise ValueError("unknown fixture ID")


def run_fixture(identifier: str) -> dict:
    """Run an actual deterministic analysis/planner, never count catalog labels as tests."""
    from .analysis import analyze
    from .planner import plan_repair
    case = load_fixture(identifier)
    before_bytes = copy.deepcopy(case["inputs"])
    report = analyze(case["inputs"], case["playset"], case["profile"], case["baselines"])
    plan = plan_repair(report, case["inputs"])
    kinds = {f["kind"] for f in report["findings"]}
    assertions = [{"name": "disposition", "pass": plan["status"] == case["expected"]["disposition"]},
                  {"name": "required_findings", "pass": set(case["expected"]["finding_kinds"]) <= kinds},
                  {"name": "source_bytes_unchanged", "pass": case["inputs"] == before_bytes},
                  {"name": "no_game_or_model_execution", "pass": report["summary"]["game_runs"] == report["summary"]["llm_calls"] == 0}]
    actual = {d["id"]: d["value"] for d in (plan["after"] or report)["definitions"]}
    for key, expected in case["expected"].get("effective", {}).items():
        assertions.append({"name": "effective:" + key, "pass": actual.get(key) == expected})
    return {"id": case["id"], "tier": "contract", "passed": all(a["pass"] for a in assertions),
            "assertions": assertions, "analysis": report, "plan": plan, "evidence_level": "P", "game_runs": 0}
