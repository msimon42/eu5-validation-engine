"""Reusable evidence views and bounded, honest concern packages; synthetic only."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.agent import projection
from backend.agent.investigation import _Snapshot
from backend.agent.reviews import build_concerns
from backend.app.store import Conflict, canonical, digest
from test_agent_investigation import captured as captured_fixture, source


@pytest.fixture
def captured(tmp_path):
    yield from captured_fixture.__wrapped__(tmp_path)


def _concern(service, index_id, target="game/character_interaction/call_ally_interaction"):
    index = service.store.get("agent_index", index_id)
    issue = next(item for item in index["issues"] if item["target"] == target)
    return next(item for item in build_concerns(index) if issue["id"] in item["issue_ids"])


def test_warm_requests_do_not_deserialize_scan_or_index_and_reload_projection(captured, monkeypatch):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    projection.clear_projection_cache(service)
    original = service.store.get
    kinds = []

    def read(kind, *args, **kwargs):
        kinds.append(kind)
        if kind in {"scan", "agent_index", "discovery"}:
            pytest.fail("Saved projection should avoid full captured record loading")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(service.store, "get", read)
    first = api.read_source(workspace["id"], index_id, selected["source_id"])
    second = api.read_source(workspace["id"], index_id, selected["source_id"])
    assert first == second
    assert kinds.count("investigation_projection") == 1
    metrics = projection.projection_metrics(service)
    assert metrics["disk_loads"] >= 1 and metrics["hits"] >= 1
    assert metrics["cache_bytes"] <= metrics["max_cache_bytes"]


def test_projection_record_integrity_checked_after_revision_change(captured):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    record = service.store.list("investigation_projection", workspace["id"])[0]
    record["projection"]["files"][0]["path"] = "changed.txt"
    service.store.put("investigation_projection", record)
    with pytest.raises(Conflict, match="projection changed"):
        api.read_source(workspace["id"], index_id, selected["source_id"])


def test_concurrent_projection_builds_are_shared_and_oversized_views_uncached(captured, monkeypatch):
    service, _, workspace, index_id, _ = captured
    # A new index revision needs one new projection even with concurrent callers.
    index = service.store.get("agent_index", index_id)
    service.store.put("agent_index", index)
    before = projection.projection_metrics(service)["builds"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        views = list(executor.map(lambda _: _Snapshot(service, workspace["id"], index_id), range(4)))
    assert all(view.files is views[0].files for view in views)
    assert projection.projection_metrics(service)["builds"] == before + 1
    projection.clear_projection_cache(service)
    monkeypatch.setattr(projection, "MAX_CACHE_BYTES", 1)
    _Snapshot(service, workspace["id"], index_id)
    assert projection.projection_metrics(service)["cache_entries"] == 0
    assert projection.projection_metrics(service)["cache_bytes"] == 0


def test_batch_reads_verify_each_blob_once_per_request_and_again_next_request(captured, monkeypatch):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    reads = []
    original = service.store.fs.read_bytes

    def read(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(service.store.fs, "read_bytes", read)
    requests = [{"source_id": selected["source_id"], "offset": i, "limit": 8} for i in (0, 8, 16)]
    batch = api.read_sources(workspace["id"], index_id, requests)
    assert len(batch["results"]) == 3 and batch["requested_bytes"] == 24
    blob_reads = [path for path in reads if path.startswith("blobs/")]
    assert len(blob_reads) == 1
    api.read_sources(workspace["id"], index_id, requests)
    assert len([path for path in reads if path.startswith("blobs/")]) == 2
    with pytest.raises(ValueError, match="65536"):
        api.read_sources(workspace["id"], index_id, [{"source_id": selected["source_id"]}] * 9)
    with pytest.raises(ValueError):
        api.read_sources(workspace["id"], index_id, [{"source_id": selected["source_id"], "limit": True}])


def test_concern_package_combines_evidence_and_keeps_game_claims_unknown(captured):
    service, api, workspace, index_id, _ = captured
    concern = _concern(service, index_id)
    result = api.concern_evidence(workspace["id"], index_id, concern["id"])
    assert len(canonical(result)) <= 128 * 1024
    assert result["contributions"] and result["knowledge"] and result["descriptors"]
    assert result["related"]
    assert result["comparisons"]
    assert all(item.get("game_selected_winner") == "unknown" for item in result["comparisons"])
    assert result["coverage"]["game_behavior"] == "not_tested"
    assert not result["capabilities"]["game_test"]["available"]
    assert any(ref.get("source_id") and ref.get("span") for ref in result["evidence_refs"])
    assert any(ref.get("entry_id") for ref in result["evidence_refs"])
    assert any(ref.get("issue_id") for ref in result["evidence_refs"])


def _large_concern(service, workspace, index_id):
    scan = service.store.get("scan", workspace["generation"])
    index = service.store.get("agent_index", index_id)
    issue = next(item for item in index["issues"] if item["target"] == "game/character_interaction/call_ally_interaction")
    original = issue["sources"][0]
    analyzed = next(item for item in scan["analysis"]["files"] if (item["owner"], item["path"]) == (original["owner"], original["path"]))
    raw = b"x = { y = 123 }\n" * 600
    checksum = digest(raw)
    service.store.fs.write_bytes(f"blobs/sha256/{checksum[:2]}/{checksum}", raw)
    issue["sources"] = []
    for number in range(20):
        path = f"common/synthetic/large_{number}.txt"
        file = {**analyzed, "id": f"synthetic_{number}", "path": path, "sha256": checksum, "size": len(raw)}
        scan["inputs"].append({"owner": file["owner"], "path": path, "sha256": checksum, "size": len(raw)})
        scan["analysis"]["files"].append(file)
        issue["sources"].append({**original, "path": path, "sha256": checksum, "span": [0, len(raw)]})
    service.store.put("scan", scan)
    service.store.put("agent_index", index)
    return _concern(service, index_id)


def test_large_packages_have_bound_continuations_and_explicit_source_gaps(captured):
    service, api, workspace, index_id, _ = captured
    concern = _large_concern(service, workspace, index_id)
    pages = [api.concern_evidence(workspace["id"], index_id, concern["id"])]
    while pages[-1]["continuation"]:
        pages.append(api.concern_evidence(workspace["id"], index_id, concern["id"], continuation=pages[-1]["continuation"]))
        assert len(pages) < 20
    assert len(pages) > 1
    contributions = [item for page in pages for item in page["contributions"]]
    assert len(contributions) >= 20
    assert all(len(canonical(page)) <= 128 * 1024 and page["coverage"]["source_bytes"] <= 65536 for page in pages)
    assert any(page["coverage"]["gaps"] for page in pages)
    assert any(item["continuation"] for item in contributions)
    assert not all(page["coverage"]["complete_source_text_on_page"] for page in pages)
    service.store.put("configuration", {"id": "inference-policy", "policy": {"excluded_patterns": ["*large_*"]}})
    with pytest.raises(Conflict, match="permissions"):
        api.concern_evidence(workspace["id"], index_id, concern["id"], continuation=pages[0]["continuation"])
    excluded = api.concern_evidence(workspace["id"], index_id, concern["id"])
    assert excluded["coverage"]["excluded_findings"]
    assert all("large_" not in item["source"]["path"] for item in excluded["contributions"])


def test_changed_scan_or_index_invalidates_metadata_cache(captured):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    index = service.store.get("agent_index", index_id)
    index["schema_hash"] = "wrong"
    service.store.put("agent_index", index)
    with pytest.raises(Conflict, match="current tools"):
        api.read_source(workspace["id"], index_id, selected["source_id"])


def test_projection_cache_evicts_old_views_at_entry_limit(captured, monkeypatch):
    service, _, workspace, index_id, _ = captured
    monkeypatch.setattr(projection, "MAX_ENTRIES", 2)
    original = service.store.get("agent_index", index_id)
    for number in range(3):
        clone = service.store.put("agent_index", {**original, "id": f"synthetic_index_{number}"})
        _Snapshot(service, workspace["id"], clone["id"])
    metrics = projection.projection_metrics(service)
    assert metrics["cache_entries"] == 2
    assert metrics["cache_bytes"] <= metrics["max_cache_bytes"]


def test_comparison_keeps_repeated_statement_order_and_has_no_merge_authority(captured):
    from backend.agent.evidence import _comparison
    service, _, workspace, index_id, _ = captured
    concern = _large_concern(service, workspace, index_id)
    view = _Snapshot(service, workspace["id"], index_id)
    issue = next(item for item in view.index["issues"] if item["id"] in concern["issue_ids"] and len(item["sources"]) == 20)
    comparison = _comparison(view, issue["sources"][0], issue["sources"][1])
    assert comparison["byte_relation"] == "identical"
    assert comparison["historical_common_ancestor"] == "not_established"
    assert comparison["game_selected_winner"] == "unknown"


@pytest.mark.parametrize("operation", ["batch", "evidence", "single", "search"])
def test_mid_request_policy_change_refuses_all_source_output(captured, monkeypatch, operation):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    concern = _concern(service, index_id)
    original = _Snapshot.raw
    changed = False

    def read(view, item):
        nonlocal changed
        result = original(view, item)
        if not changed:
            changed = True
            service.store.put("configuration", {"id": "inference-policy", "policy": {"excluded_patterns": ["*"]}})
        return result

    monkeypatch.setattr(_Snapshot, "raw", read)
    with pytest.raises(Conflict, match="permissions changed"):
        if operation == "batch":
            api.read_sources(workspace["id"], index_id, [{"source_id": selected["source_id"]}])
        elif operation == "evidence":
            api.concern_evidence(workspace["id"], index_id, concern["id"])
        elif operation == "single":
            api.read_source(workspace["id"], index_id, selected["source_id"])
        else:
            api.search_sources(workspace["id"], index_id, "call_friends_effect")


def test_mid_request_generation_change_refuses_source_output(captured, monkeypatch):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    original = _Snapshot.raw

    def read(view, item):
        result = original(view, item)
        service.store.put("workspace", {**service.store.get("workspace", workspace["id"]), "generation": "changed"})
        return result

    monkeypatch.setattr(_Snapshot, "raw", read)
    with pytest.raises(Conflict, match="newer scan"):
        api.read_sources(workspace["id"], index_id, [{"source_id": selected["source_id"]}])


def test_oversized_first_source_is_an_explicit_gap_not_stalled_cursor(captured):
    service, api, workspace, index_id, _ = captured
    scan = service.store.get("scan", workspace["generation"])
    index = service.store.get("agent_index", index_id)
    issue = next(item for item in index["issues"] if item["target"] == "game/character_interaction/call_ally_interaction")
    first = issue["sources"][0]
    identity = first["owner"], first["path"]
    for item in scan["inputs"] + scan["analysis"]["files"]:
        if (item["owner"], item["path"]) == identity:
            item["size"] = 32 * 1024 * 1024
    service.store.put("scan", scan)
    concern = _concern(service, index_id)
    page = api.concern_evidence(workspace["id"], index_id, concern["id"])
    assert page["coverage"]["gaps"]
    assert any(item.get("status") == "unavailable" for item in page["contributions"])
    assert not page["coverage"]["complete_source_text_on_page"]
    assert page["coverage"]["units_returned"][1] > 0


def test_warm_scope_checks_read_revisions_without_reparsing_large_json(captured):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    statements = []
    service.store.connection.set_trace_callback(statements.append)
    try:
        api.read_source(workspace["id"], index_id, selected["source_id"])
    finally:
        service.store.connection.set_trace_callback(None)
    assert any("SELECT revision,workspace_id" in sql for sql in statements)
    assert not any("json_extract(payload" in sql for sql in statements)
    previous_loads = projection.projection_metrics(service)["header_json_loads"]
    index = service.store.get("agent_index", index_id)
    service.store.put("agent_index", index)
    api.read_source(workspace["id"], index_id, selected["source_id"])
    assert projection.projection_metrics(service)["header_json_loads"] > previous_loads


def test_header_cache_is_bounded_and_checks_ownership_after_replacement(captured, monkeypatch):
    service, api, workspace, index_id, _ = captured
    selected = source(captured, "helpers.txt")
    monkeypatch.setattr(projection, "MAX_HEADERS", 2)
    projection.clear_projection_cache(service)
    for number in range(4):
        record = service.store.put("header_fixture", {"id": f"header-{number}", "workspace_id": workspace["id"], "name": "bounded"})
        projection._header(service.store, "header_fixture", record["id"], ("name",))
    assert len(service.store._investigation_header_cache) == 2
    assert service.store._investigation_header_bytes <= projection.MAX_HEADER_BYTES
    index = service.store.get("agent_index", index_id)
    service.store.put("agent_index", {**index, "workspace_id": "foreign"})
    with pytest.raises((Conflict, ValueError), match="selection|belong"):
        api.read_source(workspace["id"], index_id, selected["source_id"])


def test_oversized_headers_are_used_without_caching(captured, monkeypatch):
    service, _, workspace, _, _ = captured
    projection.clear_projection_cache(service)
    monkeypatch.setattr(projection, "MAX_HEADER_BYTES", 1)
    projection._header(service.store, "workspace", workspace["id"], ("name",))
    assert not service.store._investigation_header_cache
    assert service.store._investigation_header_bytes == 0
