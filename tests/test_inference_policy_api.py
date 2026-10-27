import uuid

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_policy_configuration_is_explicit_bounded_and_never_returns_credentials(tmp_path, monkeypatch):
    secret = "sk-or-v1-dummy-test-secret"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    with TestClient(create_app(tmp_path, testing=True)) as client:
        bootstrap = client.get("/api/bootstrap").json()
        workspace = bootstrap["workspaces"][0]["id"]
        assert bootstrap["inference"]["key_configured"]
        assert secret not in str(bootstrap)
        client.headers["X-Session-Token"] = bootstrap["session_token"]
        def configure(payload):
            return client.post("/api/commands", json={"command": "configure_inference", "workspace_id": workspace, "payload": payload, "idempotency_key": uuid.uuid4().hex})
        assert configure({"enabled": True}).status_code == 422
        assert configure({"enabled": False, "api_key": secret}).status_code == 422
        assert configure({"budgets": {"max_calls": True}}).status_code == 422
        assert configure({"budgets": {"max_calls": 100000}}).status_code == 422
        policy = {"enabled": True, "model": "test/model", "allowed_providers": ["Test provider"], "excluded_patterns": ["private/**"],
            "source_policy_confirmed": True, "provider_policy_confirmed": True, "tools_supported": True}
        saved = configure(policy)
        assert saved.status_code == 202, saved.text
        assert secret not in saved.text
        assert client.get("/api/bootstrap").json()["inference"]["model"] == "test/model"


def test_bare_ipv6_host_parses_correctly_and_unknown_host_is_denied(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        assert client.get("/api/health", headers={"Host": "[::1]"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "[::1]:8765"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "[::1"}).status_code == 403
