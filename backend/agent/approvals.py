"""User answers cross a separate trusted connector channel, never model arguments."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from backend.app.store import canonical


def signing_key(store):
    path = "agent/connector-key"
    with store.lock:
        if not store.fs.resolve(path).exists():
            store.fs.write_bytes(path, secrets.token_bytes(32), replace=False)
        return store.fs.read_bytes(path)


def sign(key, answer):
    return hmac.new(key, canonical(answer), hashlib.sha256).hexdigest()


def verify(key, answer, signature):
    if not isinstance(signature, str) or not hmac.compare_digest(sign(key, answer), signature):
        raise ValueError("Approval must come from your answer in Codex, not from the assistant.")
