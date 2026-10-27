import copy

import pytest

from backend.engine.analysis import analyze
from backend.engine.fixtures import _input, D, load_fixture
from backend.engine.loading import MODE_ORDER, SYNTHETIC_PROFILE, normalized_profile


def report(rows, playset=None, profile=None):
    return analyze([_input(*r) for r in rows], playset or ["A", "B"], profile or SYNTHETIC_PROFILE)


@pytest.mark.parametrize("mode", MODE_ORDER)
@pytest.mark.parametrize("present", [True, False])
def test_all_mode_presence_pairs(mode, present):
    rows = [("V", D+"00.txt", "item={x=1}\n")] if present else []
    rows.append(("A", D+"10.txt", f"{mode}:item={{y=2}}\n"))
    result = report(rows)
    definitions = result["definitions"]
    if not present and mode.startswith("TRY_"):
        assert definitions == []
        assert result["graphs"]["operation"][0]["outcome"] == "no_op"
    elif not present and mode in {"INJECT", "REPLACE"}:
        assert definitions == []
        assert any(f["kind"] == "missing_operation_target" for f in result["findings"])
    else:
        expected = {"x": "1", "y": "2"} if present and "INJECT" in mode else {"y": "2"}
        assert definitions[0]["value"] == expected
        assert definitions[0]["operations"][-1]["evidence_ids"]


@pytest.mark.parametrize("across_files", [True, False])
def test_bare_create_second_rejected(across_files):
    rows = [("A", D+"10.txt", "item={x=1}\n")]
    if across_files:
        rows.append(("B", D+"20.txt", "item={x=2}\n"))
    else:
        rows[0] = ("A", D+"10.txt", "item={x=1}\nitem={x=2}\n")
    result = report(rows)
    assert result["definitions"][0]["value"]["x"] == "1"
    assert result["definitions"][0]["transitions"][-1]["action"] == "reject_duplicate"
    assert any(f["kind"] == "duplicate_bare_definition" for f in result["findings"])


def test_vfs_selection_happens_before_mode_interpretation():
    rows = [("V", D+"base.txt", "item={x=0}\n"), ("A", D+"same.txt", "REPLACE:item={x=1}\n"), ("B", D+"same.txt", "REPLACE:item={x=2}\n")]
    first = report(rows, ["A", "B"])
    reverse = report(rows, ["B", "A"])
    assert first["definitions"][0]["value"]["x"] == "2"
    assert reverse["definitions"][0]["value"]["x"] == "1"
    assert any(f["shadowed_by"] for f in first["files"])
    assert len(first["source_definitions"]) == 3
    assert len(first["graphs"]["operation"]) == 2


def test_operation_phase_and_within_mode_filename_independent_from_playset():
    result = report([("V", D+"base.txt", "item={x=1}\n"), ("A", D+"zz.txt", "INJECT:item={y=2}\n"), ("B", D+"00.txt", "REPLACE:item={x=3}\n")])
    assert result["definitions"][0]["value"] == {"x": "3"}
    assert result["definitions"][0]["transitions"][-1]["erased"]
    rows = [("V", D+"base.txt", "item={x=1}\n"), ("A", D+"zz.txt", "REPLACE:item={x=2}\n"), ("B", D+"00.txt", "REPLACE:item={x=3}\n")]
    assert report(rows, ["A", "B"])["definitions"][0]["value"]["x"] == "2"
    assert report(rows, ["B", "A"])["definitions"][0]["value"]["x"] == "2"


def test_parent_before_child_and_stage_identity():
    result = report([("V", D+"00.txt", "item={x=0}\n"), ("A", D+"zz.txt", "REPLACE:item={x=1}\n"), ("B", D+"sub/aa.txt", "REPLACE:item={x=2}\n"), ("B", "main_menu/common/testdb/00.txt", "item={x=9}\n")])
    by_key = {d["key"]: d for d in result["definitions"]}
    assert by_key["in_game/testdb/item"]["value"]["x"] == "2"
    assert by_key["main_menu/testdb/item"]["value"]["x"] == "9"


def test_injection_preserves_repeated_nested_blocks_and_reader_unknown():
    result = report([("V", D+"00.txt", "item={nested={a=1 b=1}}\n"), ("A", D+"10.txt", "INJECT:item={nested={b=3}}\n")])
    d = result["definitions"][0]
    assert len(d["body"]) == 2
    assert d["state"] == "unknown"
    profile = copy.deepcopy(SYNTHETIC_PROFILE)
    profile["readers"]["nested"] = "named_members"
    known = report([("V", D+"00.txt", "item={nested={a=1 b=1}}\n"), ("A", D+"10.txt", "INJECT:item={nested={b=3}}\n")], profile=profile)
    assert known["definitions"][0]["value"]["nested"] == {"a": "1", "b": "3"}


def test_literal_missing_uses_and_dynamic_reference_are_distinct():
    case = load_fixture("F09")
    result = analyze(case["inputs"], case["playset"], case["profile"])
    assert sum(f["kind"] == "missing_reference" for f in result["findings"]) == 2
    dynamic = report([("A", D+"00.txt", 'item={ref="$computed$"}\n')])
    assert not any(f["kind"] == "missing_reference" for f in dynamic["findings"])
    assert dynamic["graphs"]["definition"][0]["certainty"] == "dynamic"


def test_default_and_forged_conformance_never_become_production_rules():
    inputs = [_input("A", D+"00.txt", "item={x=1}\n")]
    result = analyze(inputs, ["A"])
    assert result["definitions"][0]["state"] == "unknown"
    assert result["coverage"]["conformed_rules"] == 0
    forged = analyze(inputs, ["A"], {"kind": "conformed", "families": ["testdb"], "production_export_enabled": True, "conformed_rules": ["fake"]})
    assert not forged["profile"]["production_export_enabled"]
    assert forged["definitions"][0]["state"] == "unknown"
    p = normalized_profile(SYNTHETIC_PROFILE)
    assert normalized_profile(p)["hash"] == p["hash"]


def test_localization_ordinary_replace_and_replace_ties_are_explicit_profile_rules():
    profile = copy.deepcopy(SYNTHETIC_PROFILE)
    profile["families"].append("localization")
    profile["localization"] = {"ordinary_filename": "first", "replacement_filename": "last", "replace_priority": True}
    root = "main_menu/localization/english/"
    rows = [("A", root+"a_l_english.yml", b'\xef\xbb\xbfl_english:\n key:0 "Alpha"\n'),
            ("B", root+"z_l_english.yml", b'\xef\xbb\xbfl_english:\n key:0 "Zulu"\n')]
    first = report(rows, profile=profile)
    assert first["definitions"][0]["value"] == {"text": "Alpha"}
    rows.append(("B", root+"replace/m_l_english.yml", b'\xef\xbb\xbfl_english:\n key:0 "Replacement M"\n'))
    replacement = report(rows, profile=profile)
    assert replacement["definitions"][0]["value"] == {"text": "Replacement M"}
    rows.append(("A", root+"replace/z_l_english.yml", b'\xef\xbb\xbfl_english:\n key:0 "Replacement Z"\n'))
    assert report(rows, profile=profile)["definitions"][0]["value"] == {"text": "Replacement Z"}
    unknown = report(rows)
    assert unknown["definitions"][0]["state"] == "unknown"


def test_gui_grouping_identity_and_playlist_precedence_are_separate_from_filename():
    profile = copy.deepcopy(SYNTHETIC_PROFILE)
    profile["families"].append("gui")
    profile["readers"]["name"] = "scalar_last"
    profile["gui"] = {"duplicate_definition": "playset_last", "composition": "pinned_disjoint_fields"}
    rows = [("A", "in_game/gui/zz.gui", 'types = { type foo = base { name = "Alpha" } }\n'),
            ("B", "in_game/gui/aa.gui", 'type foo = base { name = "Beta" }\n')]
    first = report(rows, ["A", "B"], profile)
    reverse = report(rows, ["B", "A"], profile)
    assert len(first["definitions"]) == 1
    assert first["definitions"][0]["id"] == "foo"
    assert first["definitions"][0]["value"] == {"name": "Beta"}
    assert reverse["definitions"][0]["value"] == {"name": "Alpha"}
