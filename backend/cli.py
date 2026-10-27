from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(prog="eu5", description="Local EU5 mod analysis workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local API and built frontend")
    serve.add_argument("--data-dir", type=Path, default=Path.cwd() / ".workspace")
    serve.add_argument("--port", type=int, default=8765)
    fixtures = sub.add_parser("fixtures", help="Run executable synthetic contracts")
    fixtures.add_argument("--id", default=None)
    materialize = sub.add_parser("materialize", help="Create a new synthetic mod folder tree for offline testing")
    materialize.add_argument("fixture_id")
    materialize.add_argument("destination", type=Path)
    scan = sub.add_parser("scan", help="Analyze a synthetic fixture and print JSON")
    scan.add_argument("fixture_id", nargs="?", default="003-disjoint-properties")
    backup = sub.add_parser("backup", help="Consistently back up local state and blobs")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--data-dir", type=Path, default=Path.cwd() / ".workspace")
    restore = sub.add_parser("restore", help="Verify a complete backup and restore into a new/empty managed root")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from backend.app.main import create_app
        uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, workers=1)
    elif args.command == "materialize":
        from backend.engine.fixture_directories import materialize_fixture
        print(json.dumps(materialize_fixture(args.fixture_id, args.destination), indent=2))
    elif args.command == "scan":
        from backend.engine.analysis import analyze
        from backend.engine.fixtures import load_fixture
        case = load_fixture(args.fixture_id)
        print(json.dumps(analyze(case["inputs"], case["playset"], case.get("profile"), case.get("baselines")), indent=2))
    elif args.command == "fixtures":
        from backend.engine.fixtures import catalog, run_fixture
        failures = []
        cases = [entry for entry in catalog() if args.id is None or entry["id"] == args.id]
        for entry in cases:
            try:
                result = run_fixture(entry["id"])
                if not result["passed"]:
                    raise ValueError(f"Contract assertions failed: {result['assertions']}")
                print(f"{entry['id']}: PASS {result['plan']['status']}")
            except Exception as exception:
                failures.append(entry["id"])
                print(f"{entry['id']}: FAIL {exception}", file=sys.stderr)
        if not cases:
            parser.error("No matching fixture")
        if failures:
            sys.exit(1)
        print(f"Executed {len(cases)} synthetic contracts; no EU5 observations made.")
    elif args.command == "backup":
        from backend.app.store import Store
        store = Store(args.data_dir)
        try:
            print(store.backup(args.destination))
        finally:
            store.close()
    elif args.command == "restore":
        from backend.engine.backups import BackupManager
        print(json.dumps(BackupManager.restore(args.source, args.destination), indent=2))


if __name__ == "__main__":
    main()
