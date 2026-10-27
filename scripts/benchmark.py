"""Measure the declared synthetic corpus; do not extrapolate to a full installation."""
from __future__ import annotations

import base64
import json
import platform
import time
import tracemalloc

from backend.engine.fixtures import catalog, load_fixture, run_fixture
from backend.engine.parsing_cache import clear_cache


def main():
    cases = [load_fixture(entry["id"]) for entry in catalog()]
    files = [item for case in cases for item in case["inputs"]]
    clear_cache()
    timings = []
    tracemalloc.start()
    for iteration in range(3):
        started = time.perf_counter()
        results = [run_fixture(case["id"]) for case in cases]
        assert all(result["passed"] for result in results)
        timings.append({"iteration": iteration + 1, "seconds": time.perf_counter() - started,
                        "cache": "empty application cache" if iteration == 0 else "warm application cache"})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"corpus": "F01–F20 exact synthetic catalog", "platform": platform.platform(), "python": platform.python_version(),
        "files_with_repetitions": len(files), "bytes_with_repetitions": sum(len(base64.b64decode(item["bytes_base64"])) for item in files),
        "timings": timings, "peak_traced_bytes": peak, "game_runs": 0,
        "limits": "Small contract corpus only; OS disk cache not controlled; no full-game performance claim"}, indent=2))


if __name__ == "__main__":
    main()
