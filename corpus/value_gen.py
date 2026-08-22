#!/usr/bin/env python3
"""Generate (or --check) the committed value oracle `corpus/value.v0.json`.

The oracle (`../dev-docs/TautShapeOracle.md`) is the cross-language behavioral
contract: a pure `(input message sequence) -> (output message sequence)` golden.
The authored *inputs* live in `corpus/scripts_value/*.json`; this script replays
each through the reference `value` fold and fills in the observed outputs, then
writes `corpus/value.v0.json` (§3 format).

Unlike `shape_log` — whose reference engine is the external Rust
`taut-shape-tool` (`gen.py` shells to it) — the `value` fold is small and its
canonical reference already lives in the taut runtime:
`taut.crdt.glade_fold.fold_value` (glade's lww oracle: winner = max by
`(lamport, origin, seq)`; dedup by `(origin, seq)`; a forked `(origin, seq)` is
equivocation). This driver imports that reference, so value corpus generation is
self-contained in the taut-dev workspace with no per-language build. The
register-shell glue (accumulate ops, answer reads) is driver code, not a shipped
engine — taut-shape still holds no engine of its own; `fold_value` is the
authority (`fold_value(ops)` is asserted to agree with the driver's winner).

Every message is round-tripped through taut's real codecs
(jsoncodec form <-> native <-> CBOR) so no bespoke corpus serializer exists and
absent optionals materialize as `null` exactly as the wire does (D17 /
Oracle §3). Bytes ride base64, i64s ride strings — taut's jsoncodec conventions.

Usage (run from the workspace or anywhere; paths resolve to this file):
    python3 corpus/value_gen.py            # (re)write corpus/value.v0.json
    python3 corpus/value_gen.py --check    # exit nonzero if committed is stale
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_value"
IR_JSON = REPO / "ir" / "shape_value.ir.json"
OUT_JSON = CORPUS_DIR / "value.v0.json"

VERSION = "value.oracle/v0"

# Bootstrap the taut runtime (jsoncodec/codec/ir + the fold reference) from the
# sibling workspace member, mirroring ir/regen.py and gen.py.
sys.path.insert(0, str(REPO.parent / "taut" / "src"))

# `type` discriminator (== ValueMsgType member name) <-> schema message name.
_TYPE = {
    "set": "ValueSet",
    "read": "ValueReadRequest",
    "read_response": "ValueReadResponse",
    "diagnostic": "ValueDiagnostic",
}
_MSG_TO_TYPE = {msg: kind for kind, msg in _TYPE.items()}


def _load_schema():
    from taut.ir.load import schema_from_json

    return schema_from_json(json.loads(IR_JSON.read_text()))


class Register:
    """The reference `value` register: a set of lww writes answering reads.

    Mirrors `fold_value` semantics; `fold_value` itself is the winner authority.
    """

    def __init__(self, schema):
        self.schema = schema
        self.ops: list[dict] = []  # accepted: origin/seq/lamport/prev/payload

    # -- message <-> value round-trip through the real taut codecs ------------

    def _native(self, name: str, msg: dict):
        from taut.wire import jsoncodec

        jv = {k: v for k, v in msg.items() if k != "type"}
        return jsoncodec.from_json_value(self.schema, name, jv)

    def _out(self, name: str, jv: dict) -> dict:
        """jsoncodec-form output -> normalized (codec-round-tripped) + `type`."""
        from taut.wire import codec, jsoncodec

        native = jsoncodec.from_json_value(self.schema, name, jv)
        body = codec.encode(self.schema, name, native)
        back = jsoncodec.to_json_value(self.schema, name, codec.decode(self.schema, name, body))
        return {"type": _MSG_TO_TYPE[name], **back}

    # -- the engine -----------------------------------------------------------

    def send(self, in_msg: dict) -> list[dict]:
        kind = in_msg["type"]
        if kind == "set":
            return self._set(in_msg)
        if kind == "read":
            return self._read(in_msg)
        raise ValueError(f"unknown input type {kind!r}")

    def _set(self, msg: dict) -> list[dict]:
        n = self._native("ValueSet", msg)
        op = {"origin": n["origin"], "seq": n["seq"], "lamport": n["lamport"],
              "prev": n["prev"], "payload": n["payload"]}
        for ex in self.ops:
            if (ex["origin"], ex["seq"]) == (op["origin"], op["seq"]):
                if ex["payload"] != op["payload"] or ex["prev"] != op["prev"]:
                    # forked per-origin chain: reject, surface, leave register.
                    return [self._out("ValueDiagnostic",
                                      {"severity": "error", "code": "equivocation"})]
                return []  # exact re-send: idempotent, dropped
        self.ops.append(op)
        return []

    def _read(self, msg: dict) -> list[dict]:
        from taut.crdt.glade_fold import fold_value

        n = self._native("ValueReadRequest", msg)
        base = {"value_id": n["value_id"], "stream_id": n["stream_id"]}
        if not self.ops:
            return [self._out("ValueReadResponse", {**base, "state": "empty"})]
        winner = max(self.ops, key=lambda o: (o["lamport"], o["origin"], o["seq"]))
        assert winner["payload"] == fold_value(self.ops), \
            "driver winner disagrees with fold_value reference"
        jv = {**base,
              "value": base64.b64encode(winner["payload"]).decode(),
              "winner": {"origin": winner["origin"],
                         "seq": str(winner["seq"]),
                         "lamport": str(winner["lamport"])},
              "state": "data"}
        return [self._out("ValueReadResponse", jv)]


def _replay_script(schema, script: dict) -> dict:
    reg = Register(schema)
    steps_out = []
    for step in script["steps"]:
        in_msg = step["in"]
        steps_out.append({"in": in_msg, "out": reg.send(in_msg)})
    vector = {"name": script["name"], "steps": steps_out}
    if "comment" in script:
        vector["comment"] = script["comment"]
    return vector


def _corpus_text(schema) -> str:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts found under {SCRIPTS_DIR}")
    vectors = [_replay_script(schema, json.loads(p.read_text())) for p in scripts]
    corpus = {"shape": "value", "version": VERSION, "vectors": vectors}
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if committed value.v0.json differs from a fresh gen",
    )
    args = parser.parse_args(argv)

    schema = _load_schema()
    fresh = _corpus_text(schema)

    if args.check:
        committed = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        if committed != fresh:
            print(
                f"{OUT_JSON.relative_to(REPO)} is stale — run "
                f"`python3 corpus/value_gen.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT_JSON.relative_to(REPO)} is in lockstep with the scripts.")
        return 0

    OUT_JSON.write_text(fresh)
    n = len(json.loads(fresh)["vectors"])
    print(f"wrote {OUT_JSON.relative_to(REPO)} ({n} vectors, {len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
