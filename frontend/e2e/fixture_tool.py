"""File/ZIP assertions for the browser suite; does not invoke app use cases."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.engine.fixture_directories import materialize_fixture  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["materialize", "inspect_zip"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--fixture", default="F03")
    args = parser.parse_args()
    if args.action == "materialize":
        result = materialize_fixture(args.fixture, args.path)
    else:
        with zipfile.ZipFile(args.path) as bundle:
            if bundle.testzip() is not None:
                raise ValueError("Downloaded bundle failed CRC validation")
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP entries")
            result = {"names": names, "manifest": json.loads(bundle.read("manifest.json")), "files": {}}
            for name in names:
                if name == "manifest.json":
                    continue
                raw = bundle.read(name)
                result["files"][name] = {"bytes_base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
