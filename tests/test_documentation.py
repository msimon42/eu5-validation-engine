import base64
import json

import pytest

from backend.engine.documentation import import_documents


def test_opaque_documents_do_not_invent_builtins():
    raw = b"effects unknown_format = { }\xff"
    result = import_documents([{"path": "effects.log", "bytes_base64": base64.b64encode(raw).decode()}], {"exe_sha256": "a" * 64, "content_manifest_hash": "b" * 64})
    assert result["vocabulary"] == []
    assert result["coverage"]["unknown"] == 1
    assert base64.b64decode(result["documents"][0]["bytes_base64"]) == raw


def test_structured_import_is_fingerprint_bound():
    raw = json.dumps({"documentation_schema": 1, "entries": [{"name": "test_effect", "kind": "effect", "scope": "country"}]}).encode()
    inputs = [{"path": "docs.json", "bytes_base64": base64.b64encode(raw).decode()}]
    first = import_documents(inputs, {"exe_sha256": "a", "content_manifest_hash": "b"})
    second = import_documents(inputs, {"exe_sha256": "c", "content_manifest_hash": "b"})
    assert first["hash"] != second["hash"]
    assert first["vocabulary"][0]["name"] == "test_effect"
    with pytest.raises(ValueError):
        import_documents(inputs, {})
