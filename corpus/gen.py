#!/usr/bin/env python3
"""Generate (or --check) the committed behavioral oracle `corpus/log.v0.json`.

The oracle (`../dev-docs/TautShapeOracle.md`) is the cross-language behavioral
contract: a pure `(input message sequence) -> (output message sequence)` golden.
The authored *inputs* live in `corpus/scripts/*.json`; this script replays each
through the reference engine (`taut-shape-rs`'s `taut-shape-tool node`) over the
real length-prefixed CBOR data channel and fills in the observed outputs, then
writes `corpus/log.v0.json` (§3 format). `taut-shape-rs` is the reference impl
(§5); its tool is the oracle generator.

Pipeline per message (jsoncodec form <-> CBOR), using taut's own codecs so no
bespoke corpus serializer exists (D17):

    jsoncodec form (JSON-safe, `type`-tagged)
        --strip type--> jsoncodec.from_json_value(schema, MsgName, jv)
        --native-->      codec.encode(schema, MsgName, native)  -> CBOR bytes
        --frame-->       u32-LE (1 + len(body)) | tag byte | CBOR body

and the reverse for outputs (frame -> tag -> MsgName -> codec.decode ->
jsoncodec.to_json_value -> attach `type`).

The `type` discriminator is the `LogMsgType` enum member name (push, read,
read_response, ...), which maps 1:1 to both the wire tag byte and the schema
message name (see `_TYPE`).

One-input-then-drain protocol: the tool flushes stdout synchronously after each
input frame (D15/D16 — outputs are a deterministic, immediate function of the
input). We feed one input frame, then drain output frames from a background
reader thread until a quiet gap (no further frame within `QUIET_S`). Because the
engine never defers work (no clock, no async), the drained frames are exactly
the outputs that input caused. Timers are scripted inputs (`timer_expired`), so
nothing is truly time-dependent; the quiet window only separates steps.

Usage (run from taut-dev/taut-shape or anywhere; paths resolve to this file):
    python3 corpus/gen.py            # (re)write corpus/log.v0.json
    python3 corpus/gen.py --check    # exit nonzero if committed JSON is stale
"""

from __future__ import annotations

import argparse
import json
import queue
import struct
import subprocess
import sys
import threading
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts"
IR_JSON = REPO / "ir" / "shape_log.ir.json"
OUT_JSON = CORPUS_DIR / "log.v0.json"

# The reference implementation (taut-shape-rs) sits beside this repo in the
# taut-dev workspace; its tool is the oracle generator.
RS_REPO = REPO.parent / "taut-shape-rs"
TOOL_BIN = RS_REPO / "target" / "debug" / "taut-shape-tool"

VERSION = "log.oracle/v0"

# Bootstrap the taut runtime (jsoncodec/codec/ir) from the sibling workspace
# member, mirroring ir/regen.py.
sys.path.insert(0, str(REPO.parent / "taut" / "src"))

# Quiet window (seconds) that separates one step's outputs from the next input's.
# Generous: the tool flushes synchronously so real latency is sub-millisecond.
QUIET_S = 0.30

# `type` discriminator (== LogMsgType member name) -> (wire tag, schema message).
# Both directions use this single table; the tag byte is authoritative on the
# wire and the message name drives the codec.
_TYPE = {
    # inputs
    "push":          (0, "LogPush"),
    "seal":          (1, "LogSeal"),
    "close":         (2, "LogClose"),
    "read":          (3, "LogReadRequest"),
    "end_stream":    (4, "LogEndStream"),
    "timer_expired": (5, "LogTimerExpired"),
    "evict":         (6, "LogEvict"),
    # outputs
    "read_response": (7, "LogReadResponse"),
    "set_timer":     (8, "LogSetTimer"),
    "cancel_timer":  (9, "LogCancelTimer"),
    "producer_stop": (10, "LogProducerStop"),
    "diagnostic":    (11, "LogDiagnostic"),
}
_TAG_TO_TYPE = {tag: name for name, (tag, _msg) in _TYPE.items()}


def _load_schema():
    from taut.ir.load import schema_from_json

    return schema_from_json(json.loads(IR_JSON.read_text()))


# ── message <-> frame ────────────────────────────────────────────────────────

def _msg_to_frame(schema, msg: dict) -> bytes:
    """jsoncodec-form message (with `type`) -> one wire frame."""
    from taut.wire import codec, jsoncodec

    kind = msg["type"]
    tag, name = _TYPE[kind]
    jv = {k: v for k, v in msg.items() if k != "type"}
    native = jsoncodec.from_json_value(schema, name, jv)
    body = codec.encode(schema, name, native)
    length = len(body) + 1  # tag byte + body
    return struct.pack("<I", length) + bytes([tag]) + body


def _frame_to_msg(schema, tag: int, body: bytes) -> dict:
    """Wire frame parts -> jsoncodec-form message (with `type`)."""
    from taut.wire import codec, jsoncodec

    kind = _TAG_TO_TYPE.get(tag)
    if kind is None:
        raise ValueError(f"output frame with unknown tag byte {tag}")
    _tag, name = _TYPE[kind]
    native = codec.decode(schema, name, body)
    jv = jsoncodec.to_json_value(schema, name, native)
    out = {"type": kind}
    out.update(jv)
    return out


# ── the node subprocess: feed one input, drain its outputs ───────────────────

class Node:
    """A spawned `taut-shape-tool node` with a background stdout-frame reader.

    `send(input_msg)` writes one input frame and returns the list of output
    messages the engine produced for it, drained by quiet gap.
    """

    def __init__(self, schema, stop_when: str):
        self.schema = schema
        arg = "last_reader" if stop_when == "last_reader" else "explicit"
        self.proc = subprocess.Popen(
            [str(TOOL_BIN), "node", "--stop-when", arg],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Background thread reads whole frames off stdout into a queue.
        self._frames: "queue.Queue[tuple[int, bytes] | None]" = queue.Queue()
        self._reader = threading.Thread(target=self._read_frames, daemon=True)
        self._reader.start()

    def _read_frames(self) -> None:
        f = self.proc.stdout
        try:
            while True:
                hdr = _read_exact(f, 4)
                if hdr is None:
                    break
                (length,) = struct.unpack("<I", hdr)
                rest = _read_exact(f, length)
                if rest is None:
                    break
                tag = rest[0]
                body = rest[1:]
                self._frames.put((tag, body))
        finally:
            self._frames.put(None)  # sentinel: stdout closed

    def send(self, input_msg: dict) -> list[dict]:
        self.proc.stdin.write(_msg_to_frame(self.schema, input_msg))
        self.proc.stdin.flush()
        outs: list[dict] = []
        while True:
            try:
                item = self._frames.get(timeout=QUIET_S)
            except queue.Empty:
                break  # quiet gap: this step's outputs are complete
            if item is None:
                break  # stdout closed
            tag, body = item
            outs.append(_frame_to_msg(self.schema, tag, body))
        return outs

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        stderr = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.returncode not in (0, None) and stderr:
            print(f"  node stderr: {stderr.strip()}", file=sys.stderr)


def _read_exact(f, n: int) -> bytes | None:
    """Read exactly n bytes, or None on EOF (incl. a truncated tail)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ── script -> vector ─────────────────────────────────────────────────────────

def _replay_script(schema, script: dict) -> dict:
    """Replay one authored script through a fresh node, building its vector."""
    node_cfg = script.get("node", {})
    stop_when = node_cfg.get("stop_when", "last_reader")
    node = Node(schema, stop_when)
    steps_out = []
    try:
        for step in script["steps"]:
            in_msg = step["in"]
            outs = node.send(in_msg)
            steps_out.append({"in": in_msg, "out": outs})
    finally:
        node.close()

    vector = {
        "name": script["name"],
        "node": {"stop_when": stop_when},
        "steps": steps_out,
    }
    if "comment" in script:
        vector["comment"] = script["comment"]
    return vector


def _build_corpus(schema) -> dict:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts found under {SCRIPTS_DIR}")
    vectors = [_replay_script(schema, json.loads(p.read_text())) for p in scripts]
    return {"shape": "log", "version": VERSION, "vectors": vectors}


def _corpus_text(schema) -> str:
    corpus = _build_corpus(schema)
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if committed log.v0.json differs from a fresh gen",
    )
    args = parser.parse_args(argv)

    if not TOOL_BIN.exists():
        print(
            f"reference tool not built: {TOOL_BIN}\n"
            f"  run: (cd {RS_REPO} && cargo build -p taut-shape-tool)",
            file=sys.stderr,
        )
        return 2

    schema = _load_schema()
    fresh = _corpus_text(schema)

    if args.check:
        committed = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        if committed != fresh:
            print(
                f"{OUT_JSON.relative_to(REPO)} is stale — run "
                f"`python3 corpus/gen.py` and commit the result.",
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
