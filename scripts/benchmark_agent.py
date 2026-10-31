"""Reproducible investigation lookup benchmark; synthetic, managed, game runs zero.

58,000 metadata entries exercise projection overhead without copying private game
files. A few real synthetic files supply valid parser/index/blob data. This is
not a 58,000-file scanner benchmark or a real-game performance qualification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import statistics
import tempfile
import time

from backend.agent.investigation import Investigation, _Snapshot
from backend.agent.projection import projection_metrics
from backend.agent.reviews import build_concerns
from backend.agent.workflow import AgentWorkflow
from backend.app.service import Service


def benchmark(*, files=58000, iterations=20, baseline=None):
    with tempfile.TemporaryDirectory(prefix="ck3-evidence-benchmark-") as temporary:
        # macOS /var is a link; resolve only this newly-created disposable root.
        root = Path(temporary).resolve()
        originals = root / "originals"
        contents = {
            ("V", "common/character_interactions/allies.txt"): b"call_ally_interaction={ effect={ base=yes } }\n",
            ("one", "common/character_interactions/allies.txt"): b"call_ally_interaction={ effect={ base=yes } }\n",
            ("two", "common/character_interactions/allies.txt"): b"call_ally_interaction={ effect={ base=yes added=yes } }\n",
            ("one", "descriptor.mod"): b'name="First synthetic mod"\n',
            ("two", "descriptor.mod"): b'name="Second synthetic mod"\n',
        }
        for (owner, path), raw in contents.items():
            target = originals / owner / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        service = Service(root / "managed")
        try:
            workspace = service.create_workspace({"name": "Synthetic projection benchmark", "game_id": "ck3",
                "target_platform": "macos", "mode": "game", "sources": [
                    {"owner": owner, "path": str(originals / owner)} for owner in ("V", "one", "two")]})
            scan_id = service._scan(workspace, {}, lambda *args: None)["scan_id"]
            workspace = service.store.get("workspace", workspace["id"])
            index_id = AgentWorkflow(service).index(workspace, {"scan_id": scan_id}, lambda *args: None)["index_id"]
            scan = service.store.get("scan", scan_id)
            seed = scan["inputs"][0]
            analyzed = next(item for item in scan["analysis"]["files"] if
                            (item["owner"], item["path"]) == (seed["owner"], seed["path"]))
            for number in range(files - len(scan["inputs"])):
                path, file_id = f"common/synthetic/fixture_{number:05}.txt", f"synthetic-file-{number}"
                scan["inputs"].append({**seed, "path": path})
                scan["analysis"]["files"].append({**analyzed, "path": path, "id": file_id})
                scan["analysis"]["source_definitions"].append({"file_id": file_id,
                    "key": f"game/synthetic/fixture_{number}", "span": [0, 1]})
            service.store.put("scan", scan)
            api = Investigation(service)
            concern = next(item for item in build_concerns(service.store.get("agent_index", index_id))
                           if not item["identical"])
            start = time.perf_counter()
            view = _Snapshot(service, workspace["id"], index_id)
            cold = time.perf_counter() - start
            source = next(item for item in view.files if item["path"].endswith("allies.txt"))
            timings = {"view": [], "evidence": [], "follow_up_sequence": []}
            before = projection_metrics(service)
            for _ in range(iterations):
                start = time.perf_counter()
                _Snapshot(service, workspace["id"], index_id)
                timings["view"].append(time.perf_counter() - start)
                start = time.perf_counter()
                result = api.concern_evidence(workspace["id"], index_id, concern["id"])
                timings["evidence"].append(time.perf_counter() - start)
                start = time.perf_counter()
                for _ in range(4):
                    api.read_source(workspace["id"], index_id, source["source_id"])
                timings["follow_up_sequence"].append(time.perf_counter() - start)
            after = projection_metrics(service)
            summary = {name: {"median_seconds": statistics.median(values),
                              "p95_seconds": sorted(values)[max(0, int(len(values) * .95) - 1)]}
                       for name, values in timings.items()}
            return {"format": "ck3-investigation-benchmark-1", "files": len(view.files),
                "iterations": iterations, "machine": platform.machine(), "platform": platform.system(),
                "python": platform.python_version(), "cold_projection_seconds": cold, "warm": summary,
                "projection": after, "warm_projection_builds": after["builds"] - before["builds"],
                "last_evidence_bytes": len(json.dumps(result).encode()),
                "baseline_view_seconds": baseline,
                "view_speedup": baseline / summary["view"]["median_seconds"] if baseline else None,
                "synthetic": True, "game_runs": 0,
                "originals_unchanged": all((originals / owner / path).read_bytes() == raw
                                           for (owner, path), raw in contents.items()),
                "limits": "Synthetic lookup metadata only; no full-install scanner or game-performance claim."}
        finally:
            service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=58000)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--baseline", type=float)
    args = parser.parse_args()
    if not 5 <= args.files <= 100000 or not 3 <= args.iterations <= 100:
        parser.error("Use 5–100000 files and 3–100 iterations.")
    print(json.dumps(benchmark(files=args.files, iterations=args.iterations, baseline=args.baseline), indent=2))
