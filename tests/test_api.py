import time
import uuid
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app
from backend.app.service import Service


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(tmp_path / "state", testing=True)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        client.headers["X-Session-Token"] = bootstrap["session_token"]
        yield client, bootstrap, tmp_path / "state"


def command(client, workspace, name, payload, **kwargs):
    response = client.post("/api/commands", json={"command": name, "workspace_id": workspace, "payload": payload, "idempotency_key": kwargs.pop("key", uuid.uuid4().hex), **kwargs})
    assert response.status_code == 202, response.text
    result = response.json()
    if result.get("job_id"):
        for _ in range(500):
            job = client.get(f"/api/jobs/{result['job_id']}").json()
            if job["state"] in {"completed", "failed", "cancelled"}:
                assert job["state"] == "completed", job
                return job["result"]
            time.sleep(0.01)
        pytest.fail("Job did not finish within bounded test wait")
    return result


def test_full_synthetic_scan_stage_validate_export_preserves_inactive_state(api):
    client, bootstrap, root = api
    workspace = bootstrap["workspaces"][0]["id"]
    scan = command(client, workspace, "scan", {"fixture_id": "003-disjoint-properties"})
    record = client.get(f"/api/scans/{scan['scan_id']}").json()
    assert record["status"] == "complete"
    assert record["analysis"]["profile"]["kind"] == "synthetic"
    staged = command(client, workspace, "stage", {"scan_id": scan["scan_id"]})
    validated = command(client, workspace, "validate", {"candidate_id": staged["candidate_id"]})
    assert validated["validation"]["experimental_eligible"]
    assert not validated["validation"]["validated_promotion_eligible"]
    exported = command(client, workspace, "export", {"candidate_id": staged["candidate_id"], "kind": "experimental_bundle"})
    download = client.get(f"/api/artifacts/{exported['artifact_id']}")
    assert download.status_code == 200
    with zipfile.ZipFile(BytesIO(download.content)) as bundle:
        assert "manifest.json" in bundle.namelist()
        assert b"x = 2" in b"\n".join(bundle.read(name) for name in bundle.namelist() if name.endswith(".txt"))
    assert not (root / "managed" / "active-release.json").exists()
    assert not (root / "managed" / "playsets.json").exists()


def test_auth_origin_schema_and_request_idempotency(api):
    client, bootstrap, _ = api
    workspace = bootstrap["workspaces"][0]["id"]
    body = {"command": "scan", "workspace_id": workspace, "payload": {"fixture_id": "003-disjoint-properties"}, "idempotency_key": "same"}
    token = client.headers.pop("X-Session-Token")
    assert client.post("/api/commands", json=body).status_code == 403
    client.headers["X-Session-Token"] = token
    assert client.post("/api/commands", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/bootstrap", headers={"Host": "evil.example"}).status_code == 403
    first = client.post("/api/commands", json=body)
    assert first.status_code == 202
    assert client.post("/api/commands", json=body).json() == first.json()
    assert client.post("/api/commands", json={**body, "payload": {"fixture_id": "other"}}).status_code == 409
    assert client.post("/api/commands", json={**body, "idempotency_key": "bad", "payload": {"shell": "echo forbidden"}}).status_code == 422


def test_rescan_stales_candidates_and_decisions(api):
    client, bootstrap, _ = api
    workspace = bootstrap["workspaces"][0]["id"]
    first = command(client, workspace, "scan", {"fixture_id": "003-disjoint-properties"})
    candidate = command(client, workspace, "stage", {"scan_id": first["scan_id"]})
    command(client, workspace, "scan", {"fixture_id": "003-disjoint-properties"})
    assert client.get(f"/api/candidates/{candidate['candidate_id']}").json()["status"] == "stale"
    stale = client.post("/api/commands", json={"command": "decision", "workspace_id": workspace, "payload": {"scan_id": first["scan_id"], "choice": "A", "reason": "stale"}, "idempotency_key": "stale"})
    assert stale.status_code == 409


def test_design_decision_is_narrow_and_revalidated(api):
    client, bootstrap, _ = api
    workspace = bootstrap["workspaces"][0]["id"]
    scan = command(client, workspace, "scan", {"fixture_id": "F04"})
    blocked = command(client, workspace, "stage", {"scan_id": scan["scan_id"]})
    assert blocked["status"] == "blocked"
    command(client, workspace, "decision", {"scan_id": scan["scan_id"], "choice": "B", "reason": "Retain B's cost target and waive only A's competing exact value"})
    staged = command(client, workspace, "stage", {"scan_id": scan["scan_id"]})
    validated = command(client, workspace, "validate", {"candidate_id": staged["candidate_id"]})
    assert validated["validation"]["experimental_eligible"]
    waived = [entry for entry in validated["validation"]["obligations"] if entry["state"] == "waived_by_user"]
    assert len(waived) == 1 and waived[0]["owner"] == "A"
    assert waived[0]["decision_id"]


def test_valid_syntax_cannot_hide_lost_contribution_or_omit_obligation(api):
    import base64
    import hashlib
    client, bootstrap, _ = api
    workspace = bootstrap["workspaces"][0]["id"]
    scan = command(client, workspace, "scan", {"fixture_id": "F03"})
    staged = command(client, workspace, "stage", {"scan_id": scan["scan_id"]})
    store = client.app.state.service.store
    candidate = store.get("candidate", staged["candidate_id"])
    raw = b"REPLACE:item = { x = 1 y = 3 }\n"
    candidate["plan"]["files"][0].update(bytes_base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
    candidate["plan"]["obligations"] = []
    store.put("candidate", candidate)
    validation = command(client, workspace, "validate", {"candidate_id": candidate["id"]})["validation"]
    assert not validation["experimental_eligible"]
    assert any(entry["owner"] == "A" and entry["state"] == "violated" for entry in validation["obligations"])
    assert next(gate for gate in validation["gates"] if gate["id"] == "obligation_closure")["outcome"] == "fail"


def test_single_coordinator_and_restart_job_reconciliation(tmp_path):
    root = tmp_path / "state"
    first = Service(root)
    with pytest.raises((ValueError, TimeoutError, OSError)):
        Service(root)
    first.store.put("job", {"id": "interrupted", "state": "running", "phase": "scan"})
    first.close()
    second = Service(root)
    assert second.store.get("job", "interrupted")["state"] == "failed"
    second.close()
