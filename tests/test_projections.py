import base64

from backend.app.projections import scan_projection, candidate_projection


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
