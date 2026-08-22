#!/usr/bin/env python3
"""Generate (or --check) the committed behavioral oracle `corpus/atom.v1.json`.

The oracle (`../dev-docs/TautShapeOracle.md`) is the cross-language behavioral
contract: a pure `(input message sequence) -> (output message sequence)` golden.
The authored *inputs* live in `corpus/scripts_atom/*.json`; this script replays
each through a reference `atom` engine and fills in the observed outputs, then
writes `corpus/atom.v1.json` (Oracle §3 format).

`v1` (2026-07-19, PH0 review remediation — see `dev-docs/AtomSwmrNotes.md`):
bumped from `v0` because `AtomTimerExpired` now resolves through the same
canonical resolver as every other response path instead of echoing the
originally-requested `version` (PH0-D19, fixes review 56-F2), and any
timer-backed held read released for a reason other than `TimerExpired` now
cancels its timer before its response (fixes review 56-F4). Both are
behavioral changes to previously-committed vectors, hence the version bump
rather than an in-place edit.

Unlike `shape_log` (whose reference engine is the external Rust
`taut-shape-tool`) there is no per-language `atom` engine yet — `atom` is a new
shape, not yet implemented in any `taut-shape-<lang>` (`TautShapeRoadmap.md`
§1 is a design sketch, not code). Mirroring `value_gen.py`'s self-contained
precedent (a reference lives directly in this driver rather than shelling to
an external tool), this file embeds a small, hand-written reference `AtomNode`
mailbox engine — held reads, timers, and lifecycle included, since `atom`
(unlike `value`) is NOT a pure fold: it has state that outlives one message
(held reads, timer tokens, sealed/closed flags). This is a deliberate
divergence from both `gen.py` (external process) and `value_gen.py` (a pure
function import) — see `dev-docs/AtomSwmrNotes.md`. taut-shape still holds no
*shipped* engine of its own; this reference is corpus-generation tooling only,
exactly as `taut-shape-rs`'s tool is for `log`.

Every message is round-tripped through taut's real codecs (jsoncodec form <->
native <-> CBOR) so no bespoke corpus serializer exists and absent optionals
materialize as `null` exactly as the wire does (D17 / Oracle §3). Bytes ride
base64, i64s ride strings — taut's jsoncodec conventions.

Usage (run from the workspace or anywhere; paths resolve to this file):
    python3 corpus/atom_gen.py            # (re)write corpus/atom.v1.json
    python3 corpus/atom_gen.py --check    # exit nonzero if committed is stale
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_atom"
IR_JSON = REPO / "ir" / "shape_atom.ir.json"
OUT_JSON = CORPUS_DIR / "atom.v1.json"

VERSION = "atom.oracle/v1"

# Bootstrap the taut runtime (jsoncodec/codec/ir) from the sibling workspace
# member, mirroring ir/regen.py and gen.py.
sys.path.insert(0, str(REPO.parent / "taut" / "src"))

# `type` discriminator (== AtomMsgType member name) <-> schema message name.
_TYPE = {
    "replace": "AtomReplace",
    "seal": "AtomSeal",
    "close": "AtomClose",
    "read": "AtomReadRequest",
    "end_stream": "AtomEndStream",
    "timer_expired": "AtomTimerExpired",
    "read_response": "AtomReadResponse",
    "set_timer": "AtomSetTimer",
    "cancel_timer": "AtomCancelTimer",
    "producer_stop": "AtomProducerStop",
    "diagnostic": "AtomDiagnostic",
}
_MSG_TO_TYPE = {msg: kind for kind, msg in _TYPE.items()}


def _load_schema():
    from taut.ir.load import schema_from_json

    return schema_from_json(json.loads(IR_JSON.read_text()))


class _Held:
    """One stream's outstanding (held) AtomReadRequest.

    `atom_id` is tracked here (not just `version`/`timeout_ms`) because the
    wire response must be addressed with it, and a held read is answered
    later by a *different* input (a `replace`/`seal`/`close`/`timer_expired`)
    that has no reason to repeat it.
    """

    __slots__ = ("atom_id", "version", "timeout_ms", "timer_token")

    def __init__(self, atom_id: str, version: int, timeout_ms: int | None,
                 timer_token: int | None):
        self.atom_id = atom_id
        self.version = version
        self.timeout_ms = timeout_ms
        self.timer_token = timer_token


class AtomNode:
    """Reference `atom` engine: one slot, replace-only, held reads + timers.

    Mirrors the `LogNode` mailbox model (`TautClientImplPlan.md` D1) degenerated
    to window=1 (`TautShapeRoadmap.md` §1.3): no floor, no expiry, no
    max_records/max_bytes. See `dev-docs/AtomSwmrNotes.md` for every decision
    this engine had to make that the roadmap sketch left open.
    """

    def __init__(self, schema, stop_when: str):
        self.schema = schema
        self.stop_when = stop_when  # "last_reader" | "explicit_only"
        self.version = 0
        self.payload: bytes | None = None
        self.sealed = False
        self.closed = False
        self.close_error: dict | None = None
        self._streams: dict[str, _Held | None] = {}  # stream_id -> held read or None
        self._order: list[str] = []  # creation order (D16)
        self._next_token = 1

    # -- message <-> native round-trip through the real taut codecs -----------

    def _native(self, name: str, msg: dict):
        from taut.wire import jsoncodec

        jv = {k: v for k, v in msg.items() if k != "type"}
        return jsoncodec.from_json_value(self.schema, name, jv)

    def _out(self, name: str, jv: dict) -> dict:
        from taut.wire import codec, jsoncodec

        native = jsoncodec.from_json_value(self.schema, name, jv)
        body = codec.encode(self.schema, name, native)
        back = jsoncodec.to_json_value(self.schema, name, codec.decode(self.schema, name, body))
        return {"type": _MSG_TO_TYPE[name], **back}

    # -- dispatch ---------------------------------------------------------------

    def send(self, in_msg: dict) -> list[dict]:
        kind = in_msg["type"]
        if kind == "replace":
            return self._replace(in_msg)
        if kind == "seal":
            return self._seal()
        if kind == "close":
            return self._close(in_msg)
        if kind == "read":
            return self._read(in_msg)
        if kind == "end_stream":
            return self._end_stream(in_msg)
        if kind == "timer_expired":
            return self._timer_expired(in_msg)
        raise ValueError(f"unknown input type {kind!r}")

    # -- producer side ------------------------------------------------------

    def _is_terminal(self) -> bool:
        return self.sealed or self.closed

    def _replace(self, msg: dict) -> list[dict]:
        n = self._native("AtomReplace", msg)
        if self._is_terminal():
            return [self._out("AtomDiagnostic",
                              {"severity": "warn", "code": "replace_after_terminal"})]
        self.version += 1
        self.payload = n["payload"]
        return self._answer_all_held()

    def _seal(self) -> list[dict]:
        if self.sealed:
            return []
        self.sealed = True
        return self._answer_all_held()

    def _close(self, msg: dict) -> list[dict]:
        self._native("AtomClose", msg)  # validate against the schema; see close_error below
        if self.closed:
            return []
        self.closed = True
        # F5-07: capture in jsoncodec form (the raw input, before `_native`'s
        # round-trip), not native form -- `msg["error"]` is already
        # jsoncodec-shaped and is fed straight back into `_out(...)` by
        # `_resolve`, which expects jsoncodec-form fields throughout.
        self.close_error = msg.get("error")
        outs = self._answer_all_held()
        reason = "failed" if self.close_error else "closed"
        outs.append(self._out("AtomProducerStop", {"reason": reason}))
        return outs

    # -- stream side ----------------------------------------------------------

    def _ensure_stream(self, stream_id: str) -> None:
        if stream_id not in self._streams:
            self._streams[stream_id] = None
            self._order.append(stream_id)

    def _read(self, msg: dict) -> list[dict]:
        n = self._native("AtomReadRequest", msg)
        atom_id = n["atom_id"]
        stream_id = n["stream_id"]
        version = n["version"]["version"] if n["version"] is not None else 0
        timeout_ms = n["timeout_ms"]

        self._ensure_stream(stream_id)
        outs: list[dict] = []
        prior = self._streams[stream_id]
        if prior is not None and prior.timer_token is not None:
            outs.append(self._out("AtomCancelTimer", {"token": prior.timer_token}))
        self._streams[stream_id] = None

        resolved = self._resolve(atom_id, stream_id, version, timeout_ms)
        if resolved is None:
            token = None
            if timeout_ms is not None and timeout_ms > 0:
                token = self._next_token
                self._next_token += 1
                outs.append(self._out("AtomSetTimer", {"token": token, "ms": timeout_ms}))
            self._streams[stream_id] = _Held(atom_id, version, timeout_ms, token)
            return outs
        outs.append(resolved)
        return outs

    def _resolve(self, atom_id: str, stream_id: str, version: int,
                 timeout_ms: int | None) -> dict | None:
        """Resolve one AtomReadRequest against current state.

        Returns the jsoncodec-form AtomReadResponse output, or None if the
        read must be held (caller decides timer/hold bookkeeping).
        """
        # Defensive clamp: a version beyond current can never legitimately
        # arise (the engine is the sole source of truth on `version`); treat
        # it exactly like "caught up" rather than defining a new state, since
        # the roadmap sketch has no analogue to log's beyond-head `expired`
        # for atom (there is no floor/head distinction to misuse) — see
        # AtomSwmrNotes.md.
        if version < self.version:
            value = {"version": str(self.version),
                     "payload": base64.b64encode(self.payload).decode()}
            return self._out("AtomReadResponse", {
                "atom_id": atom_id, "stream_id": stream_id,
                "value": value, "next_version": {"version": str(self.version)},
                "state": "data",
            })
        # caught up (version == self.version, or version > self.version clamp)
        next_version = {"version": str(self.version)}
        if self.closed:
            state = "failed" if self.close_error else "closed"
            jv = {"atom_id": atom_id, "stream_id": stream_id, "value": None,
                  "next_version": next_version, "state": state}
            if self.close_error:
                jv["error"] = self.close_error
            return self._out("AtomReadResponse", jv)
        if self.sealed:
            return self._out("AtomReadResponse", {
                "atom_id": atom_id, "stream_id": stream_id, "value": None,
                "next_version": next_version, "state": "eof",
            })
        if timeout_ms == 0:
            return self._out("AtomReadResponse", {
                "atom_id": atom_id, "stream_id": stream_id, "value": None,
                "next_version": next_version, "state": "would_block",
            })
        return None  # hold (timeout_ms absent, or >0 — caller sets the timer)

    def _answer_all_held(self) -> list[dict]:
        outs: list[dict] = []
        for stream_id in self._order:
            held = self._streams.get(stream_id)
            if held is None:
                continue
            resolved = self._resolve(held.atom_id, stream_id, held.version, held.timeout_ms)
            if resolved is not None:
                # 56-F4: a timer-backed held read released for a reason other
                # than TimerExpired cancels its timer immediately before its
                # response, matching the three log engines' established
                # behavior (a real shell must not keep owning an unnecessary
                # timer).
                if held.timer_token is not None:
                    outs.append(self._out("AtomCancelTimer", {"token": held.timer_token}))
                outs.append(resolved)
                self._streams[stream_id] = None
        return outs

    def _end_stream(self, msg: dict) -> list[dict]:
        n = self._native("AtomEndStream", msg)
        stream_id = n["stream_id"]
        if stream_id not in self._streams:
            return []
        held = self._streams.pop(stream_id)
        self._order.remove(stream_id)
        outs: list[dict] = []
        if held is not None and held.timer_token is not None:
            outs.append(self._out("AtomCancelTimer", {"token": held.timer_token}))
        if not self._streams and self.stop_when == "last_reader":
            outs.append(self._out("AtomProducerStop", {"reason": "last_reader_gone"}))
        return outs

    def _timer_expired(self, msg: dict) -> list[dict]:
        n = self._native("AtomTimerExpired", msg)
        token = n["token"]
        for stream_id, held in self._streams.items():
            if held is not None and held.timer_token == token:
                self._streams[stream_id] = None
                # PH0-D19 (fixes review 56-F2): never echo the originally
                # requested `version` verbatim -- run the SAME canonical
                # resolver every other response path uses, in probe mode
                # (timeout_ms=0), so a beyond-current version is clamped
                # exactly as an immediate read would clamp it. timeout_ms=0
                # always resolves (never holds), so this is never None.
                resolved = self._resolve(held.atom_id, stream_id, held.version, 0)
                assert resolved is not None
                return [resolved]
        return []  # late/canceled token: no-op


def _replay_script(schema, script: dict) -> dict:
    node_cfg = script.get("node", {})
    stop_when = node_cfg.get("stop_when", "last_reader")
    node = AtomNode(schema, stop_when)
    steps_out = []
    for step in script["steps"]:
        in_msg = step["in"]
        outs = node.send(in_msg)
        steps_out.append({"in": in_msg, "out": outs})
    vector = {"name": script["name"], "node": {"stop_when": stop_when}, "steps": steps_out}
    if "comment" in script:
        vector["comment"] = script["comment"]
    return vector


def _corpus_text(schema) -> str:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts found under {SCRIPTS_DIR}")
    vectors = [_replay_script(schema, json.loads(p.read_text())) for p in scripts]
    corpus = {"shape": "atom", "version": VERSION, "vectors": vectors}
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if committed atom.v1.json differs from a fresh gen",
    )
    args = parser.parse_args(argv)

    schema = _load_schema()
    fresh = _corpus_text(schema)

    if args.check:
        committed = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        if committed != fresh:
            print(f"{OUT_JSON.relative_to(REPO)} is stale — run "
                  f"`python3 corpus/atom_gen.py` and commit the result.", file=sys.stderr)
            return 1
        print(f"{OUT_JSON.relative_to(REPO)} is in lockstep with the scripts.")
        return 0

    OUT_JSON.write_text(fresh)
    n = len(json.loads(fresh)["vectors"])
    print(f"wrote {OUT_JSON.relative_to(REPO)} ({n} vectors, {len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
