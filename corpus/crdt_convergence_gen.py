#!/usr/bin/env python3
"""Generate/check N-replica CRDT convergence and text-profile corpora."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from crdt_model import CrdtModel, text_projection


def build(directory: Path, shape: str, version: str, text: bool) -> str:
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        script = json.loads(path.read_text())
        results = []
        for replica in script["replicas"]:
            model = CrdtModel(int(script.get("max_pending", 1024)))
            diagnostics = []
            if script.get("bootstrap") is not None:
                diagnostics.extend(model.install_bootstrap(script["bootstrap"]))
            for index in replica["order"]:
                diagnostics.extend(model.apply(script["ops"][index]))
            canonical = model.canonical()
            canonical["diagnostics"] = sorted(
                {
                    (d["code"], d.get("origin"), d.get("seq"))
                    for d in diagnostics
                }
            )
            if text:
                canonical["projection"] = text_projection(model)
            results.append(canonical)
        if any(result != results[0] for result in results[1:]):
            raise ValueError(f"authored replicas do not converge in {path.name}")
        scenarios.append({
            "name": script["name"],
            "max_pending": int(script.get("max_pending", 1024)),
            "bootstrap": script.get("bootstrap"),
            "ops": script["ops"],
            "replicas": script["replicas"],
            "expect": results[0],
        })
    if not scenarios:
        raise SystemExit(f"no scripts under {directory}")
    return json.dumps({"shape": shape, "version": version, "scenarios": scenarios}, sort_keys=True, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    targets = [
        (HERE / "scripts_crdt_convergence", HERE / "crdt.convergence.v1.json", "crdt", "crdt.convergence/v1", False),
        (HERE / "scripts_text_crdt", HERE / "text_crdt.profile.v1.json", "text_crdt", "text_crdt.profile/v1", True),
    ]
    rc = 0
    for directory, output, shape, version, is_text in targets:
        fresh = build(directory, shape, version, is_text)
        if args.check:
            if not output.exists() or output.read_text() != fresh:
                print(f"{output.name} is stale", file=sys.stderr)
                rc = 1
            else:
                print(f"corpus/{output.name} is in lockstep with authored scripts.")
        else:
            output.write_text(fresh)
            print(f"wrote {output.name} ({len(json.loads(fresh)['scenarios'])} scenarios)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
