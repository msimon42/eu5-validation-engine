"""Start the real production app on an OS-assigned loopback port for one test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402
import uvicorn  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    # Bind once and hand the live socket to Uvicorn: no free-port/rebind race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        ready_temporary = args.ready.with_suffix(".tmp")
        ready_temporary.write_text(json.dumps({"url": url, "state": str(args.state)}))
        ready_temporary.replace(args.ready)
        config = uvicorn.Config(create_app(args.state), log_level="warning", access_log=False)
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    main()
