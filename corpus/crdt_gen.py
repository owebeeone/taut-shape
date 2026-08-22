#!/usr/bin/env python3
"""Generate/check `crdt.oracle/v1` from authored mailbox scripts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = HERE / "scripts_crdt"
OUTPUT = HERE / "crdt.v1.json"
sys.path.insert(0, str(REPO.parent / "taut" / "src"))
sys.path.insert(0, str(HERE))

from crdt_model import CrdtModel

TYPE_TO_MSG = {
    "apply": "CrdtApply",
    "install_bootstrap": "CrdtInstallBootstrap",
    "seal": "CrdtSeal",
    "close": "CrdtClose",
    "read": "CrdtReadRequest",
    "read_response": "CrdtReadResponse",
    "diagnostic": "CrdtDiagnostic",
}


def schema():
    spec = importlib.util.spec_from_file_location("shape_crdt", REPO / "ir/shape_crdt.taut.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCHEMA


SCHEMA = schema()


def roundtrip(message: dict) -> dict:
    from taut.wire import codec, jsoncodec

    kind = message["type"]
    name = TYPE_TO_MSG[kind]
    value = {key: val for key, val in message.items() if key != "type"}
    native = jsoncodec.from_json_value(SCHEMA, name, value)
    body = codec.encode(SCHEMA, name, native)
    return {"type": kind, **jsoncodec.to_json_value(SCHEMA, name, codec.decode(SCHEMA, name, body))}


def corpus_text() -> str:
    vectors = []
    for path in sorted(SCRIPTS.glob("*.json")):
        script = json.loads(path.read_text())
        model = CrdtModel(int(script.get("node", {}).get("max_pending", 1024)))
        steps = []
        for raw in script["inputs"]:
            message = roundtrip(raw)
            outputs = [roundtrip(out) for out in model.send(message)]
            steps.append({"in": message, "out": outputs})
        vector = {"name": script["name"], "node": script.get("node", {}), "steps": steps}
        if "comment" in script:
            vector["comment"] = script["comment"]
        vectors.append(vector)
    if not vectors:
        raise SystemExit(f"no scripts under {SCRIPTS}")
    return json.dumps({"shape": "crdt", "version": "crdt.oracle/v1", "vectors": vectors}, sort_keys=True, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fresh = corpus_text()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != fresh:
            print("corpus/crdt.v1.json is stale; run corpus/crdt_gen.py", file=sys.stderr)
            return 1
        print("corpus/crdt.v1.json is in lockstep with authored scripts.")
        return 0
    OUTPUT.write_text(fresh)
    print(f"wrote {OUTPUT.relative_to(REPO)} ({len(json.loads(fresh)['vectors'])} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
