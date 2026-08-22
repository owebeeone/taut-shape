#!/usr/bin/env python3
"""Generate/check expiry-profile vectors through the canonical SWMR core."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swmr_gen import SwmrNode, _load_schema


CORPUS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_snapshot_delta"
OUT_JSON = CORPUS_DIR / "snapshot_delta.profile.v1.json"
VERSION = "snapshot_delta.profile/v1"


def _project(output: dict) -> dict:
    if output.get("type") != "read_response" or output.get("state") != "reset":
        return output
    reason = {
        "retention_exceeded": "retention_expired",
        "invalid_resume_seq": "invalid_cursor",
        "producer_requested": "source_changed",
    }[output.get("reset_reason") or "producer_requested"]
    return {
        "type": "refresh_required",
        "swmr_id": output["swmr_id"],
        "stream_id": output["stream_id"],
        "reason": reason,
    }


def generate() -> dict:
    schema = _load_schema()
    vectors = []
    for path in sorted(SCRIPTS_DIR.glob("*.json")):
        script = json.loads(path.read_text())
        node_config = script.get("node", {})
        node = SwmrNode(
            schema,
            node_config.get("stop_when", "last_reader"),
            node_config.get("max_deltas", 64),
        )
        steps = []
        for step in script["steps"]:
            steps.append(
                {
                    "in": step["in"],
                    "out": [_project(output) for output in node.send(step["in"])],
                }
            )
        vector = {
            "name": script["name"],
            "comment": script.get("comment", ""),
            "node": {
                "stop_when": node_config.get("stop_when", "last_reader"),
                "max_deltas": node_config.get("max_deltas", 64),
                "recovery": "expire",
            },
            "steps": steps,
        }
        vectors.append(vector)
    return {
        "shape": "snapshot_delta",
        "core": "swmr",
        "version": VERSION,
        "vectors": vectors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, sort_keys=False) + "\n"
    if args.check:
        if not OUT_JSON.exists() or OUT_JSON.read_text() != rendered:
            print(f"stale: {OUT_JSON}")
            return 1
        print(f"ok: {OUT_JSON}")
        return 0
    OUT_JSON.write_text(rendered)
    print(f"wrote: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
