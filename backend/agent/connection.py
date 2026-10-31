"""Start or attach to one loopback-only headless engine per managed library."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import stat
import time
from urllib.parse import urlsplit

import httpx

from backend.engine.safety import ManagedFS, read_source_bytes, reject_link_components


class EngineClient:
    def __init__(self, data_dir):
        self.root = reject_link_components(Path(data_dir).absolute())
        self.http = httpx.Client(timeout=60, trust_env=False)
        self.url = None
        self.token = None

    def attach(self):
        try:
            endpoint = json.loads(read_source_bytes(self.root, "agent/engine.json", max_bytes=8192, native_paths=True))
            url = endpoint["url"]
            parsed = urlsplit(url)
            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or
                    parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
                return False
            identity = self.http.get(url + "/api/engine", timeout=1).json()
            if identity.get("id") != endpoint["id"] or identity.get("data_dir") != str(self.root):
                return False
            self.url = url
            self.token = read_source_bytes(self.root, "session-token", max_bytes=1024, native_paths=True).decode().strip()
            return True
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            return False

    def ensure(self):
        if self.attach():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        fs = ManagedFS(self.root)
        with fs._parent("agent-engine.log", create=True) as (parent, name):
            descriptor = os.open(name if parent != -1 else self.root / name,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
                **({"dir_fd": parent} if parent != -1 else {}))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                os.close(descriptor)
                raise ValueError("The engine log must be an unshared regular file.")
        with os.fdopen(descriptor, "ab") as output:
            process = subprocess.Popen([sys.executable, "-m", "backend.cli", "engine", "--data-dir", str(self.root)],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt", creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        for _ in range(100):
            if self.attach():
                return
            if process.poll() is not None:
                # Another connector can have won the startup race. Only attach
                # to a verified identity; never open a second SQLite coordinator.
                if self.attach():
                    return
                raise ValueError("The engine could not start. An older running instance may own this library; finish its jobs before switching to the agent.")
            time.sleep(.1)
        raise ValueError("The engine did not become ready. Its saved jobs have not been discarded.")

    def request(self, method, path, **kwargs):
        # Reattach before sending an operation, so a restarted engine keeps
        # existing conversations usable. Never replay an ambiguous mutation.
        self.ensure()
        response = self.http.request(method, self.url + path,
            headers={"X-Session-Token": self.token}, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "The operation could not be completed.")
            except ValueError:
                detail = "The engine returned an unreadable response."
            raise ValueError(detail)
        return response.json()

    def agent(self, operation, **payload):
        return self.request("POST", "/api/agent", json={"operation": operation, "payload": payload})

    def command(self, command, workspace_id=None, payload=None):
        import uuid
        return self.request("POST", "/api/commands", json={"command": command,
            "workspace_id": workspace_id, "payload": payload or {}, "idempotency_key": uuid.uuid4().hex})

    def connector_key(self):
        return read_source_bytes(self.root, "agent/connector-key", max_bytes=64, native_paths=True)

    def close(self):
        self.http.close()


def run_engine(data_dir, port=0):
    import secrets
    import socket
    import uvicorn
    from backend.app.main import create_app

    root = reject_link_components(Path(data_dir).absolute())
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    selected_port = sock.getsockname()[1]
    endpoint = {"id": secrets.token_urlsafe(24), "url": f"http://127.0.0.1:{selected_port}", "pid": os.getpid()}
    app = create_app(root, frontend=False, endpoint=endpoint)
    try:
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=selected_port)).run(sockets=[sock])
    finally:
        sock.close()
