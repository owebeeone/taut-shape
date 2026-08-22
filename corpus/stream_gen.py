#!/usr/bin/env python3
"""Generate/check `stream.v1.json` from authored stream scripts.

The embedded engine is corpus tooling only. It implements the bounded,
drop-slow-reader policy frozen in `TautShapeStreamDecision.md` and round-trips
every message through Taut's real schema codec/jsoncodec path.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_stream"
IR_JSON = REPO / "ir" / "shape_stream.ir.json"
OUT_JSON = CORPUS_DIR / "stream.v1.json"
VERSION = "stream.oracle/v1"

sys.path.insert(0, str(REPO.parent / "taut" / "src"))

_TYPE = {
    "push": "StreamPush",
    "seal": "StreamSeal",
    "close": "StreamClose",
    "read": "StreamReadRequest",
    "end_stream": "StreamEndStream",
    "timer_expired": "StreamTimerExpired",
    "read_response": "StreamReadResponse",
    "set_timer": "StreamSetTimer",
    "cancel_timer": "StreamCancelTimer",
    "producer_stop": "StreamProducerStop",
    "diagnostic": "StreamDiagnostic",
}
_MSG_TO_TYPE = {message: kind for kind, message in _TYPE.items()}


def _load_schema():
    from taut.ir.load import schema_from_json

    return schema_from_json(json.loads(IR_JSON.read_text()))


class Held:
    def __init__(
        self,
        max_records: int | None,
        max_bytes: int | None,
        timeout_ms: int | None,
        timer_token: int | None,
    ):
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.timeout_ms = timeout_ms
        self.timer_token = timer_token


class Reader:
    def __init__(self, cursor: int):
        self.cursor = cursor
        self.held: Held | None = None


class StreamNode:
    def __init__(self, schema, capacity_records: int, stop_when: str):
        if capacity_records <= 0:
            raise ValueError("capacity_records must be positive")
        self.schema = schema
        self.capacity = capacity_records
        self.stop_when = stop_when
        self.head = 0
        self.records: list[tuple[int, bytes]] = []
        self.sealed = False
        self.closed = False
        self.close_error: dict | None = None
        self.readers: dict[str, Reader] = {}
        self.order: list[str] = []
        self.next_token = 1

    def _native(self, name: str, message: dict):
        from taut.wire import jsoncodec

        return jsoncodec.from_json_value(
            self.schema,
            name,
            {key: value for key, value in message.items() if key != "type"},
        )

    def _out(self, name: str, value: dict) -> dict:
        from taut.wire import codec, jsoncodec

        native = jsoncodec.from_json_value(self.schema, name, value)
        body = codec.encode(self.schema, name, native)
        roundtrip = jsoncodec.to_json_value(
            self.schema, name, codec.decode(self.schema, name, body)
        )
        return {"type": _MSG_TO_TYPE[name], **roundtrip}

    def send(self, message: dict) -> list[dict]:
        return getattr(self, f"_{message['type']}")(message)

    @property
    def floor(self) -> int:
        return self.records[0][0] if self.records else self.head + 1

    def _push(self, message: dict) -> list[dict]:
        native = self._native("StreamPush", message)
        if self.sealed or self.closed:
            return [
                self._out(
                    "StreamDiagnostic",
                    {"severity": "warn", "code": "push_after_terminal"},
                )
            ]
        self.head += 1
        self.records.append((self.head, native["payload"]))
        if len(self.records) > self.capacity:
            self.records = self.records[-self.capacity :]
        return self._answer_all_held()

    def _seal(self, message: dict) -> list[dict]:
        self._native("StreamSeal", message)
        if self.sealed or self.closed:
            return []
        self.sealed = True
        return self._answer_all_held()

    def _close(self, message: dict) -> list[dict]:
        self._native("StreamClose", message)
        if self.closed:
            return []
        self.closed = True
        self.close_error = message.get("error")
        outputs = self._answer_all_held()
        outputs.append(
            self._out(
                "StreamProducerStop",
                {"reason": "failed" if self.close_error else "closed"},
            )
        )
        return outputs

    def _ensure_reader(self, stream_id: str) -> Reader:
        reader = self.readers.get(stream_id)
        if reader is None:
            reader = Reader(self.head)
            self.readers[stream_id] = reader
            self.order.append(stream_id)
        return reader

    def _read(self, message: dict) -> list[dict]:
        native = self._native("StreamReadRequest", message)
        stream_id = native["stream_id"]
        reader = self._ensure_reader(stream_id)
        outputs: list[dict] = []
        if reader.held is not None and reader.held.timer_token is not None:
            outputs.append(
                self._out("StreamCancelTimer", {"token": reader.held.timer_token})
            )
        reader.held = None
        response = self._resolve(
            stream_id,
            reader,
            native["max_records"],
            native["max_bytes"],
            native["timeout_ms"],
        )
        if response is not None:
            outputs.append(response)
            if response["state"] == "dropped":
                outputs.extend(self._remove_reader(stream_id))
            return outputs
        token = None
        timeout_ms = native["timeout_ms"]
        if timeout_ms is not None and timeout_ms > 0:
            token = self.next_token
            self.next_token += 1
            outputs.append(
                self._out("StreamSetTimer", {"token": token, "ms": timeout_ms})
            )
        reader.held = Held(
            native["max_records"],
            native["max_bytes"],
            timeout_ms,
            token,
        )
        return outputs

    def _resolve(
        self,
        stream_id: str,
        reader: Reader,
        max_records: int | None,
        max_bytes: int | None,
        timeout_ms: int | None,
    ) -> dict | None:
        if reader.cursor < self.floor - 1:
            return self._response(
                stream_id,
                [],
                self.head,
                "dropped",
                {"code": "slow_consumer", "message": None},
            )
        available = [(seq, payload) for seq, payload in self.records if seq > reader.cursor]
        selected: list[tuple[int, bytes]] = []
        used = 0
        for record in available:
            if max_records is not None and max_records > 0 and len(selected) >= max_records:
                break
            payload_size = len(record[1])
            if (
                max_bytes is not None
                and max_bytes >= 0
                and selected
                and used + payload_size > max_bytes
            ):
                break
            selected.append(record)
            used += payload_size
        if selected:
            reader.cursor = selected[-1][0]
            return self._response(stream_id, selected, reader.cursor, "data", None)
        if self.closed:
            return self._response(
                stream_id,
                [],
                reader.cursor,
                "failed" if self.close_error else "closed",
                self.close_error,
            )
        if self.sealed:
            return self._response(stream_id, [], reader.cursor, "eof", None)
        if timeout_ms == 0:
            return self._response(stream_id, [], reader.cursor, "would_block", None)
        return None

    def _response(
        self,
        stream_id: str,
        records: list[tuple[int, bytes]],
        next_seq: int,
        state: str,
        error: dict | None,
    ) -> dict:
        value = {
            "stream_id": stream_id,
            "records": [
                {
                    "seq": str(seq),
                    "payload": base64.b64encode(payload).decode(),
                }
                for seq, payload in records
            ],
            "next_position": {"seq": str(next_seq)},
            "state": state,
            "error": error,
        }
        return self._out("StreamReadResponse", value)

    def _answer_all_held(self) -> list[dict]:
        outputs: list[dict] = []
        for stream_id in list(self.order):
            reader = self.readers.get(stream_id)
            if reader is None or reader.held is None:
                continue
            held = reader.held
            response = self._resolve(
                stream_id,
                reader,
                held.max_records,
                held.max_bytes,
                held.timeout_ms,
            )
            if response is None:
                continue
            if held.timer_token is not None:
                outputs.append(
                    self._out("StreamCancelTimer", {"token": held.timer_token})
                )
            reader.held = None
            outputs.append(response)
            if response["state"] == "dropped":
                outputs.extend(self._remove_reader(stream_id))
        return outputs

    def _remove_reader(self, stream_id: str) -> list[dict]:
        if stream_id not in self.readers:
            return []
        self.readers.pop(stream_id)
        self.order.remove(stream_id)
        if not self.readers and self.stop_when == "last_reader":
            return [
                self._out(
                    "StreamProducerStop", {"reason": "last_reader_gone"}
                )
            ]
        return []

    def _end_stream(self, message: dict) -> list[dict]:
        native = self._native("StreamEndStream", message)
        reader = self.readers.get(native["stream_id"])
        if reader is None:
            return []
        outputs: list[dict] = []
        if reader.held is not None and reader.held.timer_token is not None:
            outputs.append(
                self._out("StreamCancelTimer", {"token": reader.held.timer_token})
            )
        outputs.extend(self._remove_reader(native["stream_id"]))
        return outputs

    def _timer_expired(self, message: dict) -> list[dict]:
        native = self._native("StreamTimerExpired", message)
        for stream_id in self.order:
            reader = self.readers[stream_id]
            if reader.held is None or reader.held.timer_token != native["token"]:
                continue
            held = reader.held
            reader.held = None
            response = self._resolve(
                stream_id,
                reader,
                held.max_records,
                held.max_bytes,
                0,
            )
            assert response is not None
            return [response]
        return []


def _replay(schema, script: dict) -> dict:
    node_config = script.get("node", {})
    node = StreamNode(
        schema,
        int(node_config.get("capacity_records", 4)),
        node_config.get("stop_when", "last_reader"),
    )
    steps = [
        {"in": step["in"], "out": node.send(step["in"])}
        for step in script["steps"]
    ]
    vector = {
        "name": script["name"],
        "node": {
            "capacity_records": node.capacity,
            "stop_when": node.stop_when,
        },
        "steps": steps,
    }
    if "comment" in script:
        vector["comment"] = script["comment"]
    return vector


def _fresh_text(schema) -> str:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts under {SCRIPTS_DIR}")
    corpus = {
        "shape": "stream",
        "version": VERSION,
        "vectors": [_replay(schema, json.loads(path.read_text())) for path in scripts],
    }
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    fresh = _fresh_text(_load_schema())
    if args.check:
        if (OUT_JSON.read_text() if OUT_JSON.exists() else "") != fresh:
            print("corpus/stream.v1.json is stale", file=sys.stderr)
            return 1
        print("corpus/stream.v1.json is in lockstep with the scripts.")
        return 0
    OUT_JSON.write_text(fresh)
    print(f"wrote corpus/stream.v1.json ({len(json.loads(fresh)['vectors'])} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
