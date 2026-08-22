#!/usr/bin/env python3
"""Generate (or --check) the committed behavioral oracle `corpus/swmr.v1.json`.

The oracle (`../dev-docs/TautShapeOracle.md`) is the cross-language behavioral
contract: a pure `(input message sequence) -> (output message sequence)` golden.
The authored *inputs* live in `corpus/scripts_swmr/*.json`; this script replays
each through a reference `swmr` engine and fills in the observed outputs, then
writes `corpus/swmr.v1.json` (Oracle §3 format).

`v1` (2026-07-19, PH0 review remediation — see `dev-docs/AtomSwmrNotes.md`):
bumped from `v0` for four behavioral fixes, all to previously-committed
vectors (hence a version bump, not an in-place edit):
  * PH0-D20 — `SwmrSnapshotPush` now establishes its snapshot at the
    PRE-push `head` (consuming no delivery-sequence slot) instead of
    `head+1`; deltas still run `base+1`.
  * PH0-D24 — because of D20, a reader already caught up at the pre-push
    head stays caught up (not reset) across a compaction/re-basing push
    (fixes the spurious-reset cost `AtomSwmrNotes.md` #6 used to document).
  * PH0-D19 — `SwmrTimerExpired` and `SwmrReset` now compute `next_cursor`
    through the same canonical resolver as every other response path
    instead of echoing/hardcoding a position (fixes review 56-F2 and
    F5-03's `next_cursor={seq:0}` reset contradiction); an absent-cursor
    held read is never force-answered `reset` by a producer `SwmrReset`
    (fixes review F5-02).
  * review F5-13 — `SwmrReset.reason` is normalized to `producer_requested`
    before being echoed, even if the wire-legal input named an engine-only
    reason (`retention_exceeded`/`invalid_resume_seq`).

Phase 1 pre-freeze correction (2026-08-22) keeps the draft at `v1` because it
is still uncommitted/unreleased: cursors now include a node-owned reset epoch,
producer reset reason/detail remain available to readers that were between
polls, and vector 33 pins stale-epoch repair when sequence values overlap.

Like `atom_gen.py` (see its docstring), there is no per-language `swmr` engine
yet — `swmr` is a new shape (`TautShapeRoadmap.md` §3 is a design sketch, not
code) — so this file embeds a hand-written reference `SwmrNode` mailbox
engine: a snapshot+delta store core (roadmap §3.3), held reads, timers, and
lifecycle, simplified to ONE mechanism relative to the sketch (see
`dev-docs/AtomSwmrNotes.md` for the full reasoning):

  * `SwmrSnapshotPush` ALWAYS establishes a brand-new snapshot at the PRE-push
    `head` (consuming no delivery-sequence slot — PH0-D20) and clears the
    retained delta window. This unifies "the first-ever snapshot" and
    "periodic re-basing/compaction" into one operation, because a generic
    engine cannot itself fold opaque delta payloads into a snapshot — only the
    producer (who understands the payload) can, and it does so by simply
    pushing a fresh snapshot.
  * A cursor is `(epoch, seq)`. The node-owned epoch starts at 0 and increments
    on producer reset, but not on snapshot compaction. A reader whose cursor
    has an older epoch, is below the new snapshot's `seq`, or is past `head`
    gets `state=reset` alongside any fresh `snapshot`+`deltas` — engine-
    repaired in-band, never a client-decided `expired` (roadmap §3.2). An
    ABSENT cursor never produces `reset` (there is nothing to have been reset
    FROM) — see the schema docstring's cursor-semantics note.
  * `writer_id` enforcement and the `max_deltas` retention/backpressure bound
    are NEW mechanisms beyond the roadmap sketch, added to satisfy the
    swmr shape's `writers="single"` registry constraint and the datascad
    consumer's bounded-retention requirement at the wire level — recorded as
    decisions in `dev-docs/AtomSwmrNotes.md`.

Every message is round-tripped through taut's real codecs (jsoncodec form <->
native <-> CBOR) so no bespoke corpus serializer exists and absent optionals
materialize as `null` exactly as the wire does (D17 / Oracle §3). Bytes ride
base64, i64s ride strings — taut's jsoncodec conventions.

Usage (run from the workspace or anywhere; paths resolve to this file):
    python3 corpus/swmr_gen.py            # (re)write corpus/swmr.v1.json
    python3 corpus/swmr_gen.py --check    # exit nonzero if committed is stale
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_swmr"
IR_JSON = REPO / "ir" / "shape_swmr.ir.json"
OUT_JSON = CORPUS_DIR / "swmr.v1.json"

VERSION = "swmr.oracle/v1"

# Bootstrap the taut runtime (jsoncodec/codec/ir) from the sibling workspace
# member, mirroring ir/regen.py and gen.py.
sys.path.insert(0, str(REPO.parent / "taut" / "src"))

# `type` discriminator (== SwmrMsgType member name) <-> schema message name.
_TYPE = {
    "snapshot_push": "SwmrSnapshotPush",
    "delta_push": "SwmrDeltaPush",
    "reset": "SwmrReset",
    "seal": "SwmrSeal",
    "close": "SwmrClose",
    "read": "SwmrReadRequest",
    "end_stream": "SwmrEndStream",
    "timer_expired": "SwmrTimerExpired",
    "read_response": "SwmrReadResponse",
    "set_timer": "SwmrSetTimer",
    "cancel_timer": "SwmrCancelTimer",
    "producer_stop": "SwmrProducerStop",
    "diagnostic": "SwmrDiagnostic",
}
_MSG_TO_TYPE = {msg: kind for kind, msg in _TYPE.items()}


def _load_schema():
    from taut.ir.load import schema_from_json

    return schema_from_json(json.loads(IR_JSON.read_text()))


class _Held:
    """One stream's outstanding (held) SwmrReadRequest.

    `cursor` is the ORIGINAL request's cursor (`None` if absent) — re-resolved
    verbatim when a later input wakes it, which is what makes an absent cursor
    never resolve to `reset` even after the wake (see schema docstring).
    """

    __slots__ = ("swmr_id", "cursor", "timeout_ms", "timer_token")

    def __init__(self, swmr_id: str, cursor: tuple[int, int] | None,
                 timeout_ms: int | None,
                 timer_token: int | None):
        self.swmr_id = swmr_id
        self.cursor = cursor
        self.timeout_ms = timeout_ms
        self.timer_token = timer_token


class SwmrNode:
    """Reference `swmr` engine: snapshot+delta store core, held reads, timers.

    See `dev-docs/AtomSwmrNotes.md` for every decision this engine had to make
    that `TautShapeRoadmap.md` §3 left open.
    """

    def __init__(self, schema, stop_when: str, max_deltas: int | None):
        self.schema = schema
        self.stop_when = stop_when  # "last_reader" | "explicit_only"
        self.max_deltas = max_deltas
        self.snapshot: tuple[int, bytes] | None = None  # (seq, payload)
        self.deltas: list[tuple[int, bytes]] = []  # ordered, contiguous seqs
        self.sealed = False
        self.closed = False
        self.close_error: dict | None = None
        self.writer_id: str | None = None
        # Node-owned durable reset generation. Sequence numbers may restart and
        # overlap after reset; epoch makes an old cursor unambiguous. `swmr_id`
        # identifies this node incarnation, so shells must not reuse an id after
        # recreation unless they also persist/restore this epoch.
        self.epoch = 0
        self.reset_reason: str | None = None
        # jsoncodec-form base64 string, retained verbatim for stale-epoch reads.
        self.reset_detail: str | None = None
        self._streams: dict[str, _Held | None] = {}
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

    def _head(self) -> int:
        return self.snapshot[0] + len(self.deltas) if self.snapshot else 0

    # -- dispatch ---------------------------------------------------------------

    def send(self, in_msg: dict) -> list[dict]:
        kind = in_msg["type"]
        if kind == "snapshot_push":
            return self._snapshot_push(in_msg)
        if kind == "delta_push":
            return self._delta_push(in_msg)
        if kind == "reset":
            return self._reset(in_msg)
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

    def _check_writer(self, writer_id: str) -> bool:
        if self.writer_id is None:
            self.writer_id = writer_id
            return True
        return writer_id == self.writer_id

    def _snapshot_push(self, msg: dict) -> list[dict]:
        n = self._native("SwmrSnapshotPush", msg)
        if self._is_terminal():
            return [self._out("SwmrDiagnostic",
                              {"severity": "warn", "code": "push_after_terminal"})]
        if not self._check_writer(n["writer_id"]):
            return [self._out("SwmrDiagnostic",
                              {"severity": "error", "code": "writer_conflict"})]
        # PH0-D20: a snapshot consumes NO delivery-sequence slot -- its
        # resume position is the pre-push base (== head), not head+1. This
        # is what makes compaction/re-basing transparent to a reader already
        # caught up at that base (PH0-D24): their stored cursor still equals
        # the new snapshot's seq, so the next resolve sees them as caught up
        # rather than stale/reset.
        base = self._head()
        self.snapshot = (base, n["payload"])
        self.deltas = []
        return self._answer_all_held()

    def _delta_push(self, msg: dict) -> list[dict]:
        n = self._native("SwmrDeltaPush", msg)
        if self._is_terminal():
            return [self._out("SwmrDiagnostic",
                              {"severity": "warn", "code": "push_after_terminal"})]
        if not self._check_writer(n["writer_id"]):
            return [self._out("SwmrDiagnostic",
                              {"severity": "error", "code": "writer_conflict"})]
        if self.snapshot is None:
            return [self._out("SwmrDiagnostic",
                              {"severity": "error", "code": "delta_before_snapshot"})]
        if self.max_deltas is not None and len(self.deltas) >= self.max_deltas:
            return [self._out("SwmrDiagnostic",
                              {"severity": "error", "code": "retention_bound_exceeded"})]
        new_seq = self._head() + 1
        self.deltas.append((new_seq, n["payload"]))
        return self._answer_all_held()

    def _reset(self, msg: dict) -> list[dict]:
        n = self._native("SwmrReset", msg)
        if self._is_terminal():
            return [self._out("SwmrDiagnostic",
                              {"severity": "warn", "code": "push_after_terminal"})]
        if not self._check_writer(n["writer_id"]):
            return [self._out("SwmrDiagnostic",
                              {"severity": "error", "code": "writer_conflict"})]
        reason = n["reason"]
        if reason in ("retention_exceeded", "invalid_resume_seq"):
            # F5-13: those two reasons are assigned by the engine's own read
            # resolution (a stale/invalid cursor); a producer-declared
            # SwmrReset is always `producer_requested` regardless of what
            # its wire-legal `reason` field happens to name.
            reason = "producer_requested"
        self.epoch += 1
        self.snapshot = None
        self.deltas = []
        self.reset_reason = reason
        # Capture jsoncodec form, not native bytes: `_mk_response` feeds this
        # back through jsoncodec and the field must not be base64-decoded twice.
        self.reset_detail = msg.get("detail")
        outs: list[dict] = []
        for stream_id in self._order:
            held = self._streams.get(stream_id)
            if held is None:
                continue
            if held.cursor is None:
                # PH0-D19 (fixes review F5-02): an absent-cursor held read
                # NEVER receives `reset` -- there is nothing to have been
                # reset FROM. Re-resolve it against the fresh (now-empty)
                # post-reset state via the ordinary canonical resolver
                # instead; with no snapshot it simply keeps holding until a
                # real one arrives.
                resolved = self._resolve(held.swmr_id, stream_id, None, held.timeout_ms)
                if resolved is not None:
                    if held.timer_token is not None:
                        outs.append(self._out("SwmrCancelTimer", {"token": held.timer_token}))
                    outs.append(resolved)
                    self._streams[stream_id] = None
                continue
            # 56-F4: cancel a positioned hold's timer before its response.
            if held.timer_token is not None:
                outs.append(self._out("SwmrCancelTimer", {"token": held.timer_token}))
            # PH0-D19 (fixes review F5-03): next_cursor is ABSENT, never a
            # hardcoded `{seq: 0}` -- no snapshot survives a reset, and
            # next_cursor is present iff a snapshot currently exists.
            outs.append(self._mk_response(held.swmr_id, stream_id, snapshot=None, deltas=[],
                                           next_cursor=None, state="reset", reset_reason=reason,
                                           reset_detail=self.reset_detail))
            self._streams[stream_id] = None
        return outs

    def _seal(self) -> list[dict]:
        if self.sealed:
            return []
        self.sealed = True
        return self._answer_all_held()

    def _close(self, msg: dict) -> list[dict]:
        self._native("SwmrClose", msg)  # validate against the schema; see close_error below
        if self.closed:
            return []
        self.closed = True
        # F5-07: capture in jsoncodec form (the raw input, before `_native`'s
        # round-trip), not native form -- `msg["error"]` is already
        # jsoncodec-shaped and is fed straight back into `_out(...)` by
        # `_mk_response`/`_caught_up`, which expect jsoncodec-form fields
        # throughout (a future BYTES field would otherwise be silently
        # corrupted by a second, wrong-direction codec conversion).
        self.close_error = msg.get("error")
        outs = self._answer_all_held()
        reason = "failed" if self.close_error else "closed"
        outs.append(self._out("SwmrProducerStop", {"reason": reason}))
        return outs

    # -- response construction -----------------------------------------------

    def _mk_response(self, swmr_id: str, stream_id: str,
                      snapshot: tuple[int, bytes] | None,
                      deltas: list[tuple[int, bytes]],
                      next_cursor: tuple[int, int] | None, state: str,
                      reset_reason: str | None = None,
                      reset_detail: str | None = None,
                      error: dict | None = None) -> dict:
        jv = {
            "swmr_id": swmr_id,
            "stream_id": stream_id,
            "snapshot": (
                {"seq": str(snapshot[0]), "payload": base64.b64encode(snapshot[1]).decode()}
                if snapshot is not None else None
            ),
            "deltas": [
                {"base_seq": str(seq - 1), "seq": str(seq),
                 "payload": base64.b64encode(payload).decode()}
                for seq, payload in deltas
            ],
            "next_cursor": (
                {"epoch": str(next_cursor[0]), "seq": str(next_cursor[1])}
                if next_cursor is not None else None
            ),
            "state": state,
            "reset_reason": reset_reason,
            "reset_detail": reset_detail,
            "error": error,
        }
        return self._out("SwmrReadResponse", jv)

    # -- stream side ----------------------------------------------------------

    def _ensure_stream(self, stream_id: str) -> None:
        if stream_id not in self._streams:
            self._streams[stream_id] = None
            self._order.append(stream_id)

    def _read(self, msg: dict) -> list[dict]:
        n = self._native("SwmrReadRequest", msg)
        swmr_id = n["swmr_id"]
        stream_id = n["stream_id"]
        cursor = (
            (n["cursor"]["epoch"], n["cursor"]["seq"])
            if n["cursor"] is not None else None
        )
        timeout_ms = n["timeout_ms"]

        self._ensure_stream(stream_id)
        outs: list[dict] = []
        prior = self._streams[stream_id]
        if prior is not None and prior.timer_token is not None:
            outs.append(self._out("SwmrCancelTimer", {"token": prior.timer_token}))
        self._streams[stream_id] = None

        resolved = self._resolve(swmr_id, stream_id, cursor, timeout_ms)
        if resolved is None:
            token = None
            if timeout_ms is not None and timeout_ms > 0:
                token = self._next_token
                self._next_token += 1
                outs.append(self._out("SwmrSetTimer", {"token": token, "ms": timeout_ms}))
            self._streams[stream_id] = _Held(swmr_id, cursor, timeout_ms, token)
            return outs
        outs.append(resolved)
        return outs

    def _resolve(self, swmr_id: str, stream_id: str,
                 cursor: tuple[int, int] | None,
                 timeout_ms: int | None) -> dict | None:
        """Resolve one SwmrReadRequest against current state.

        Returns the jsoncodec-form SwmrReadResponse output, or None if the
        read must be held (caller decides timer/hold bookkeeping).
        """
        if cursor is not None:
            cursor_epoch, _ = cursor
            if cursor_epoch < self.epoch:
                # Durable reset: the reader may have been between polls when
                # SwmrReset happened. Sequence comparison is deliberately
                # skipped because the new epoch may reuse the same seq values.
                next_cursor = (
                    (self.epoch, self._head()) if self.snapshot is not None else None
                )
                return self._mk_response(
                    swmr_id, stream_id, self.snapshot,
                    list(self.deltas) if self.snapshot is not None else [],
                    next_cursor=next_cursor, state="reset",
                    reset_reason=self.reset_reason or "producer_requested",
                    reset_detail=self.reset_detail,
                )
            if cursor_epoch > self.epoch:
                # A future epoch was never issued by this node incarnation.
                next_cursor = (
                    (self.epoch, self._head()) if self.snapshot is not None else None
                )
                return self._mk_response(
                    swmr_id, stream_id, self.snapshot,
                    list(self.deltas) if self.snapshot is not None else [],
                    next_cursor=next_cursor, state="reset",
                    reset_reason="invalid_resume_seq",
                )
        if self.snapshot is None:
            return self._caught_up(swmr_id, stream_id, next_cursor=None, timeout_ms=timeout_ms)
        snap_seq, _ = self.snapshot
        head = self._head()
        if cursor is None:
            # Fresh subscribe: never `reset` (nothing was reset FROM).
            return self._mk_response(swmr_id, stream_id, self.snapshot, list(self.deltas),
                                      next_cursor=(self.epoch, head), state="data")
        _, c = cursor
        if c < snap_seq:
            return self._mk_response(swmr_id, stream_id, self.snapshot, list(self.deltas),
                                      next_cursor=(self.epoch, head), state="reset",
                                      reset_reason="retention_exceeded")
        if c == head:
            return self._caught_up(swmr_id, stream_id,
                                   next_cursor=(self.epoch, c), timeout_ms=timeout_ms)
        if c > head:
            return self._mk_response(swmr_id, stream_id, self.snapshot, list(self.deltas),
                                      next_cursor=(self.epoch, head), state="reset",
                                      reset_reason="invalid_resume_seq")
        # snap_seq <= c < head: incremental catch-up, no fresh snapshot
        # needed. Deltas are contiguous (F5 §4.6), so the tail is index
        # arithmetic, not a linear scan: delta seq snap_seq+1 lives at index
        # 0, so seq c+1 lives at index c-snap_seq.
        tail = self.deltas[c - snap_seq:]
        return self._mk_response(swmr_id, stream_id, None, tail,
                                 next_cursor=(self.epoch, head), state="data")

    def _caught_up(self, swmr_id: str, stream_id: str,
                    next_cursor: tuple[int, int] | None,
                    timeout_ms: int | None) -> dict | None:
        if self.closed:
            error = self.close_error
            state = "failed" if error else "closed"
            return self._mk_response(swmr_id, stream_id, None, [], next_cursor, state,
                                      error=error)
        if self.sealed:
            return self._mk_response(swmr_id, stream_id, None, [], next_cursor, "eof")
        if timeout_ms == 0:
            return self._mk_response(swmr_id, stream_id, None, [], next_cursor, "would_block")
        return None  # hold (timeout_ms absent, or >0 — caller sets the timer)

    def _answer_all_held(self) -> list[dict]:
        outs: list[dict] = []
        for stream_id in self._order:
            held = self._streams.get(stream_id)
            if held is None:
                continue
            resolved = self._resolve(held.swmr_id, stream_id, held.cursor, held.timeout_ms)
            if resolved is not None:
                # 56-F4: a timer-backed held read released for a reason other
                # than TimerExpired cancels its timer immediately before its
                # response, matching the three log engines' established
                # behavior (a real shell must not keep owning an unnecessary
                # timer).
                if held.timer_token is not None:
                    outs.append(self._out("SwmrCancelTimer", {"token": held.timer_token}))
                outs.append(resolved)
                self._streams[stream_id] = None
        return outs

    def _end_stream(self, msg: dict) -> list[dict]:
        n = self._native("SwmrEndStream", msg)
        stream_id = n["stream_id"]
        if stream_id not in self._streams:
            return []
        held = self._streams.pop(stream_id)
        self._order.remove(stream_id)
        outs: list[dict] = []
        if held is not None and held.timer_token is not None:
            outs.append(self._out("SwmrCancelTimer", {"token": held.timer_token}))
        if not self._streams and self.stop_when == "last_reader":
            outs.append(self._out("SwmrProducerStop", {"reason": "last_reader_gone"}))
        return outs

    def _timer_expired(self, msg: dict) -> list[dict]:
        n = self._native("SwmrTimerExpired", msg)
        token = n["token"]
        for stream_id, held in self._streams.items():
            if held is not None and held.timer_token == token:
                self._streams[stream_id] = None
                # PH0-D19 (fixes review 56-F2): never echo the originally
                # requested `cursor` verbatim -- run the SAME canonical
                # resolver every other response path uses, in probe mode
                # (timeout_ms=0), so next_cursor is normalized exactly as an
                # immediate read would normalize it (e.g. absent when no
                # snapshot exists yet, instead of manufacturing a position
                # that was never valid). timeout_ms=0 always resolves (never
                # holds), so this is never None.
                resolved = self._resolve(held.swmr_id, stream_id, held.cursor, 0)
                assert resolved is not None
                return [resolved]
        return []  # late/canceled token: no-op


def _replay_script(schema, script: dict) -> dict:
    node_cfg = script.get("node", {})
    stop_when = node_cfg.get("stop_when", "last_reader")
    max_deltas = node_cfg.get("max_deltas")
    node = SwmrNode(schema, stop_when, max_deltas)
    steps_out = []
    for step in script["steps"]:
        in_msg = step["in"]
        outs = node.send(in_msg)
        steps_out.append({"in": in_msg, "out": outs})
    node_out: dict = {"stop_when": stop_when}
    if max_deltas is not None:
        node_out["max_deltas"] = max_deltas
    vector = {"name": script["name"], "node": node_out, "steps": steps_out}
    if "comment" in script:
        vector["comment"] = script["comment"]
    return vector


def _corpus_text(schema) -> str:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts found under {SCRIPTS_DIR}")
    vectors = [_replay_script(schema, json.loads(p.read_text())) for p in scripts]
    corpus = {"shape": "swmr", "version": VERSION, "vectors": vectors}
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if committed swmr.v1.json differs from a fresh gen",
    )
    args = parser.parse_args(argv)

    schema = _load_schema()
    fresh = _corpus_text(schema)

    if args.check:
        committed = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        if committed != fresh:
            print(f"{OUT_JSON.relative_to(REPO)} is stale — run "
                  f"`python3 corpus/swmr_gen.py` and commit the result.", file=sys.stderr)
            return 1
        print(f"{OUT_JSON.relative_to(REPO)} is in lockstep with the scripts.")
        return 0

    OUT_JSON.write_text(fresh)
    n = len(json.loads(fresh)["vectors"])
    print(f"wrote {OUT_JSON.relative_to(REPO)} ({n} vectors, {len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
