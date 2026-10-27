import random

import pytest

from backend.engine.parser import Edit, apply_edits, digest, parse
from backend.engine.formats import parse_localization, parse_family


@pytest.mark.parametrize("raw", [
    b"", b"\xef\xbb\xbfitem={x=01 x=-2.500}\r\n# hi\n", b"item = { a b c x=2 }",
    b'item = { text = "a # }" x=2 }', b'item={text="C:\\test\\path"}',
    b"item={x!=1 y?={z=2} x<=5}", b"item={x=1", b"}", b'item={text="unfinished',
    b"\xffabc", b"\xff\xfea\x00", b"@x = @[ 1 + 2 * 3 ]\na={rgb { 1 2 3 }}",
    b'type panel = base_type { name="a/b" }', b"code [[ a { } # unknown ]]",
    b"scripted_trigger helper={x=yes}", b"item={ a = { b = 1 } }\r\n"
])
def test_exact_round_trip_and_token_coverage(raw):
    doc = parse(raw)
    assert doc.serialize() == raw
    assert b"".join(raw[t.start:t.end] for t in doc.tokens) == raw
    assert all(0 <= n.start <= n.end <= len(raw) for n in doc.root.walk())


def test_repeated_occurrence_and_operator_adjacency():
    doc = parse(b"item={x!=1 x?={y=2} x>=3 x==4}")
    nodes = doc.children[0].children
    assert [n.operator for n in nodes] == ["!=", "?=", ">=", "=="]
    assert [n.ordinal for n in nodes] == [0, 1, 2, 3]


def test_surgical_second_occurrence_edit_keeps_comments_and_spelling():
    raw = b"# section\r\nitem={x=01 # trailing\r\nx=2.500}\r\n"
    doc = parse(raw)
    second = doc.children[0].children[1]
    edit = Edit(second.value_start, second.value_end, b"3.125", digest(b"2.500"), 1)
    out = apply_edits(doc, [edit], doc.sha256)
    assert out == raw.replace(b"2.500", b"3.125")
    assert doc.raw == raw
    with pytest.raises(ValueError, match="stale document"):
        apply_edits(doc, [edit], "0" * 64)
    with pytest.raises(ValueError, match="occurrence"):
        apply_edits(doc, [Edit(second.value_start, second.value_end, b"9", digest(b"2.500"), 0)], doc.sha256)


def test_overlapping_and_recovered_edits_fail_closed():
    doc = parse(b"x=123")
    with pytest.raises(ValueError, match="overlapping"):
        apply_edits(doc, [Edit(2, 4, b"1", digest(b"12")), Edit(3, 5, b"2", digest(b"23"))], doc.sha256)
    malformed = parse(b"item={x=1")
    with pytest.raises(ValueError, match="recovered"):
        apply_edits(malformed, [], malformed.sha256)
    fixed = apply_edits(malformed, [Edit(len(malformed.raw), len(malformed.raw), b" }\n", digest(b""))], malformed.sha256, allow_syntax_repair=True)
    assert fixed == b"item={x=1 }\n"


def test_unicode_utf16_bom_and_crlf_coordinates():
    raw = '\ufeff# é😀\r\nx = 1\n'.encode()
    doc = parse(raw)
    pos = doc.position(raw.index(b"\r"))
    assert pos["byte"] != pos["character"]
    assert pos["utf16_column"] == 5
    assert pos["column"] == 5
    x = raw.index(b"x")
    assert doc.position(x)["line"] == 2
    assert doc.position(x)["utf16_column"] == 0
    assert doc.byte_offset(doc.position(x)["character"]) == x
    with pytest.raises((UnicodeDecodeError, ValueError)):
        doc.position(raw.index("😀".encode()) + 1)


def test_bounded_random_roundtrips_and_limits():
    rng = random.Random(187)
    atoms = [b"x=1", b"x?={a=2}", b'v="a # }"', b"#comment\n", b"a", b"{", b"}"]
    for _ in range(100):
        raw = b" ".join(rng.choice(atoms) for _ in range(30))
        assert parse(raw).serialize() == raw
    assert any(d["code"] == "depth_limit" for d in parse(b"{" * 30, max_depth=8).diagnostics)
    assert any(d["code"] == "token_limit" for d in parse(b"x=1 " * 30, max_tokens=10).diagnostics)
    assert any(d["code"] == "byte_limit" for d in parse(b"abc", max_bytes=2).diagnostics)


def test_localization_dedicated_parser_retains_hash_revision_bom_and_other_keys():
    raw = b'\xef\xbb\xbfl_english:\r\n item_name:0 "Alpha # label" # trailing\r\n other: "Keep"\r\n'
    parsed = parse_localization(raw, "a_l_english.yml")
    assert not parsed["diagnostics"]
    assert parsed["entries"][0]["value"] == "Alpha # label"
    assert parsed["entries"][0]["revision"] == "0"
    assert parsed["document"].serialize() == raw
    assert parsed["entries"][1]["revision"] == ""
    assert parse_localization(raw, "a_l_french.yml")["diagnostics"][0]["code"] == "language_filename_mismatch"


def test_dispatch_metadata_opaque_and_setup_bom_exception():
    assert parse_family(b'{"unknown":42}', ".metadata/metadata.json")["data"] == {"unknown": 42}
    assert "document" not in parse_family(b"DDS binary", "in_game/gfx/test.dds")
    assert parse_family(b"x=1", "main_menu/setup/countries/a.txt")["diagnostics"][0]["code"] == "documented_bom_required"
    assert parse_family(b"\xef\xbb\xbfx=1", "main_menu/setup/start/a.txt")["diagnostics"][0]["code"] == "documented_bom_forbidden"


def test_utf16_inverse_rejects_half_surrogates_and_honors_bom_crlf():
    raw = '\ufeff# 😀\r\nx=1'.encode()
    doc = parse(raw)
    for offset in [3, raw.index('😀'.encode()), raw.index(b'x'), len(raw)]:
        position = doc.position(offset)
        assert doc.byte_from_utf16(position['utf16_line'], position['utf16_column']) == offset
    with pytest.raises(ValueError, match='surrogate'):
        doc.byte_from_utf16(0, 3)


@pytest.mark.parametrize('payload', [
    {'start': 2.5, 'end': 3, 'replacement': b'2', 'expected_old_sha256': digest(b'1')},
    {'start': 2, 'end': 3, 'replacement': b'2', 'expected_old_sha256': digest(b'1'), 'delete_everything': True},
    {'start': True, 'end': 3, 'replacement': b'2', 'expected_old_sha256': digest(b'1')},
])
def test_structural_edit_schema_rejects_truncated_coordinates_and_unknown_fields(payload):
    doc = parse(b'x=1')
    with pytest.raises(ValueError):
        apply_edits(doc, [payload], doc.sha256)
