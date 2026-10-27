#!/usr/bin/env python3
"""Read-only environment discovery / unrun probe evidence. Never edits playsets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from engine.runtime import RuntimeWorker, fingerprint_installation  # noqa: E402


def manual_observer(target: dict):
    """Operator observations are recorded explicitly, never invented by the CLI."""
    def observe(request: dict) -> dict:
        phase = request["phase"]
        recipe = request["recipe"]
        if phase == "observe":
            print("Observe the requested field/behavior in the game, then enter the observed sentinel as JSON.")
            sentinel = json.loads(input("Observed sentinel JSON: "))
            note = input("Direct observation (screen/command/save evidence): ").strip()
            control = input("Negative-control observation and result: ").strip()
            milestones = input("Milestones actually reached, comma separated: ").strip().split(",")
            passed = input("Did every requested assertion and negative control pass? [yes/no]: ").strip() == "yes"
            return {"direct_observation": {"method": "operator_ui", "note": note},
                    "sentinel": sentinel, "sentinel_confirmed": sentinel == recipe.get("expected_sentinel"),
                    "negative_control": control, "milestones": [item.strip() for item in milestones if item.strip()],
                    "assertions": [{"id": "operator-observed-probe", "outcome": "pass" if passed else "fail"}]}
        confirmed = input(f"[{phase}] Confirm actual active playset/order and sentinel configuration? [yes/no]: ").strip() == "yes"
        actual_hash = input("Actual playset manifest hash (from inspected state): ").strip()
        closed = input("Is the game fully closed? [yes/no]: ").strip() == "yes" if phase == "before" else False
        roots = {name: [Path(path) for path in target[name]] for name in
                 ("content_roots", "docs_roots", "dlc_roots") if name in target}
        captured = fingerprint_installation(Path(target["executable"]), **roots)
        return {"confirmed": confirmed and captured["complete"], "playset_hash": actual_hash,
                "game_closed": closed, "build_fingerprint": captured["build_fingerprint"],
                "method": "operator_confirmed_state_and_fresh_byte_fingerprints"}
    return observe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Managed evidence directory")
    parser.add_argument("--steam-root", type=Path, action="append")
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--recipe", type=Path, help="Capture a controlled recipe; launching stays disabled")
    parser.add_argument("--target-config", type=Path, help="JSON selection of executable/content/docs/DLC/log roots; any version")
    parser.add_argument("--launch", action="store_true", help="Explicitly enable selected Windows executable for this invocation")
    parser.add_argument("--manual-observations", action="store_true", help="Interactively record actual UI observations")
    args = parser.parse_args()
    worker = RuntimeWorker(args.output, launch_enabled=args.launch)
    if args.target_config:
        worker.configure_target(json.loads(args.target_config.read_text(encoding="utf-8")))
    if args.manual_observations:
        if not worker.target:
            parser.error("select a target with --target-config before recording game observations")
        worker.observer = manual_observer(worker.target)
    result = {"status": worker.status(),
              "discovery": worker.discover(steam_roots=args.steam_root, documents=args.documents)}
    if worker.target:
        result["target"] = worker.target
    if args.recipe:
        result["probe"] = worker.run_recipe(json.loads(args.recipe.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
