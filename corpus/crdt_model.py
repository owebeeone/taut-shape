"""Small independent reference model used only to generate CRDT corpora."""

from __future__ import annotations

import base64
import json
from typing import Any


def op_key(op: dict[str, Any]) -> tuple[str, int]:
    return str(op["origin"]), int(op["seq"])


def clock_dict(clock: dict[str, Any] | None) -> dict[str, int] | None:
    if clock is None:
        return None
    entries = clock.get("entries")
    if not isinstance(entries, list):
        return None
    result: dict[str, int] = {}
    previous: str | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        origin = entry.get("origin")
        try:
            seq = int(entry.get("seq"))
        except (TypeError, ValueError):
            return None
        if not isinstance(origin, str) or not origin or seq <= 0:
            return None
        if previous is not None and origin <= previous:
            return None
        previous = origin
        result[origin] = seq
    return result


def clock_wire(clock: dict[str, int]) -> dict[str, Any]:
    return {
        "entries": [
            {"origin": origin, "seq": str(seq)}
            for origin, seq in sorted(clock.items())
            if seq > 0
        ]
    }


def _op_variant(op: dict[str, Any]) -> tuple[tuple[tuple[str, int], ...], str]:
    deps = clock_dict(op["deps"])
    assert deps is not None
    return tuple(sorted(deps.items())), str(op["payload"])


class CrdtModel:
    def __init__(self, max_pending: int = 1024) -> None:
        if max_pending < 0:
            raise ValueError("max_pending must be non-negative")
        self.max_pending = max_pending
        self.clock: dict[str, int] = {}
        self.floor: dict[str, int] = {}
        self.bootstrap: dict[str, Any] | None = None
        self.ops: dict[tuple[str, int], dict[str, Any]] = {}
        self.integrated: set[tuple[str, int]] = set()
        self.equivocated: set[tuple[str, int]] = set()
        self.sealed = False
        self.closed = False
        self.error: dict[str, Any] | None = None

    def send(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        kind = message["type"]
        if kind == "apply":
            return self.apply(message["op"])
        if kind == "install_bootstrap":
            return self.install_bootstrap(message["bootstrap"])
        if kind == "read":
            return [self.read(message)]
        if kind == "seal":
            if not self.closed:
                self.sealed = True
            return []
        if kind == "close":
            if not self.closed:
                self.closed = True
                self.error = message.get("error")
            return []
        raise ValueError(f"unknown CRDT input {kind!r}")

    def diagnostic(
        self, code: str, op: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "diagnostic",
            "severity": "error" if code != "apply_after_terminal" else "warn",
            "code": code,
            "origin": None if op is None else op.get("origin"),
            "seq": None if op is None else op.get("seq"),
        }

    def _valid_op(self, op: dict[str, Any]) -> bool:
        origin = op.get("origin")
        try:
            seq = int(op.get("seq"))
        except (TypeError, ValueError):
            return False
        deps = clock_dict(op.get("deps"))
        if not isinstance(origin, str) or not origin or seq <= 0 or deps is None:
            return False
        return deps.get(origin, 0) < seq

    def apply(self, op: dict[str, Any]) -> list[dict[str, Any]]:
        if self.sealed or self.closed:
            return [self.diagnostic("apply_after_terminal", op)]
        if not self._valid_op(op):
            return [self.diagnostic("invalid_operation", op)]
        key = op_key(op)
        if key[1] <= self.floor.get(key[0], 0):
            return []
        previous = self.ops.get(key)
        if previous is not None:
            if previous == op:
                return []
            outputs: list[dict[str, Any]] = []
            if key not in self.equivocated:
                self.equivocated.add(key)
                outputs.append(self.diagnostic("equivocation", op))
            if _op_variant(op) < _op_variant(previous):
                self.ops[key] = op
            self._drain()
            return outputs
        pending_count = len(self.ops) - len(self.integrated)
        if not self._ready(op) and pending_count >= self.max_pending:
            return [self.diagnostic("pending_bound_exceeded", op)]
        self.ops[key] = op
        self._drain()
        return []

    def _ready(self, op: dict[str, Any]) -> bool:
        origin, seq = op_key(op)
        if seq > self.clock.get(origin, 0) + 1:
            return False
        deps = clock_dict(op["deps"])
        assert deps is not None
        return all(self.clock.get(dep_origin, 0) >= dep_seq for dep_origin, dep_seq in deps.items())

    def _drain(self) -> None:
        while True:
            ready = [
                key
                for key, op in self.ops.items()
                if key not in self.integrated and self._ready(op)
            ]
            if not ready:
                return
            for key in sorted(ready):
                self.integrated.add(key)
                self.clock[key[0]] = max(self.clock.get(key[0], 0), key[1])

    def install_bootstrap(self, bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
        if self.sealed or self.closed:
            return [self.diagnostic("apply_after_terminal")]
        parsed = clock_dict(bootstrap.get("clock"))
        if parsed is None:
            return [self.diagnostic("invalid_operation")]
        if self.bootstrap == bootstrap:
            return []
        if self.bootstrap is not None or self.ops:
            return [self.diagnostic("bootstrap_conflict")]
        self.bootstrap = bootstrap
        self.floor = dict(parsed)
        self.clock = dict(parsed)
        return []

    def read(self, message: dict[str, Any]) -> dict[str, Any]:
        cursor_wire = message.get("cursor")
        cursor = {} if cursor_wire is None else clock_dict(cursor_wire)
        common = {
            "type": "read_response",
            "crdt_id": message["crdt_id"],
            "stream_id": message["stream_id"],
            "bootstrap": None,
            "ops": [],
            "next_cursor": clock_wire(self.clock),
            "state": "empty",
            "error": None,
        }
        if cursor is None or any(seq > self.clock.get(origin, 0) for origin, seq in cursor.items()):
            return {**common, "state": "invalid_cursor"}
        below_floor = any(cursor.get(origin, 0) < seq for origin, seq in self.floor.items())
        if cursor_wire is not None and below_floor:
            returned_bootstrap = self.bootstrap
            base = self.floor
            state = "bootstrap_required"
        else:
            returned_bootstrap = self.bootstrap if cursor_wire is None else None
            base = cursor
            state = "data"
        ops = [
            self.ops[key]
            for key in sorted(self.integrated)
            if key[1] > base.get(key[0], 0)
        ]
        if returned_bootstrap is not None or ops:
            return {**common, "bootstrap": returned_bootstrap, "ops": ops, "state": state}
        if self.closed:
            return {**common, "state": "failed" if self.error else "closed", "error": self.error}
        if self.sealed:
            return {**common, "state": "eof"}
        return common

    def canonical(self) -> dict[str, Any]:
        return {
            "clock": clock_wire(self.clock),
            "ops": [self.ops[key] for key in sorted(self.integrated)],
            "diagnostics": [
                {"code": "equivocation", "origin": origin, "seq": str(seq)}
                for origin, seq in sorted(self.equivocated)
            ],
        }


def decode_bytes(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def text_projection(model: CrdtModel) -> dict[str, Any]:
    atoms: dict[str, tuple[str | None, str, tuple[str, int]]] = {}
    deleted: set[str] = set()
    diagnostics: set[str] = set()

    if model.bootstrap is not None:
        try:
            state = json.loads(decode_bytes(model.bootstrap["state"]))
            rows = state["atoms"]
            if not isinstance(rows, list):
                raise ValueError
            for row in rows:
                atom_id = row["atom_id"]
                after = row["after"]
                text = row["text"]
                is_deleted = row["deleted"]
                if not isinstance(atom_id, str) or not atom_id or (
                    after is not None and not isinstance(after, str)
                ) or not isinstance(text, str) or not text or not isinstance(is_deleted, bool):
                    raise ValueError
                atoms[atom_id] = (after, text, ("", 0))
                if is_deleted:
                    deleted.add(atom_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            diagnostics.add("invalid_bootstrap")

    for key in sorted(model.integrated):
        op = model.ops[key]
        try:
            payload = json.loads(decode_bytes(op["payload"]))
            kind = payload["kind"]
            atom_id = payload["atom_id"]
            if not isinstance(atom_id, str) or not atom_id:
                raise ValueError
            if kind == "delete":
                if set(payload) != {"kind", "atom_id"}:
                    raise ValueError
                deleted.add(atom_id)
            elif kind == "insert":
                if set(payload) != {"kind", "atom_id", "after", "text"}:
                    raise ValueError
                after = payload["after"]
                text = payload["text"]
                if (after is not None and not isinstance(after, str)) or not isinstance(text, str) or not text:
                    raise ValueError
                candidate = (after, text, key)
                previous = atoms.get(atom_id)
                if previous is not None and previous != candidate:
                    diagnostics.add(f"atom_equivocation:{atom_id}")
                    atoms[atom_id] = min(previous, candidate, key=lambda item: (
                        "" if item[0] is None else item[0], item[1], item[2]
                    ))
                else:
                    atoms[atom_id] = candidate
            else:
                raise ValueError
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            diagnostics.add(f"invalid_payload:{key[0]}:{key[1]}")

    children: dict[str | None, list[str]] = {}
    for atom_id, (after, _text, _key) in atoms.items():
        if after is not None and after not in atoms:
            diagnostics.add(f"missing_parent:{atom_id}:{after}")
            continue
        children.setdefault(after, []).append(atom_id)
    for ids in children.values():
        ids.sort()

    visiting: set[str] = set()
    visited: set[str] = set()
    output: list[str] = []

    def visit(atom_id: str) -> None:
        if atom_id in visiting:
            diagnostics.add(f"cycle:{atom_id}")
            return
        if atom_id in visited:
            return
        visiting.add(atom_id)
        if atom_id not in deleted:
            output.append(atoms[atom_id][1])
        for child in children.get(atom_id, []):
            visit(child)
        visiting.remove(atom_id)
        visited.add(atom_id)

    for root in children.get(None, []):
        visit(root)
    for atom_id in sorted(set(atoms) - visited):
        # Orphans and cycles stay invisible but receive stable diagnostics.
        if atom_id not in visited and atoms[atom_id][0] in atoms:
            visit(atom_id)
    return {"text": "".join(output), "diagnostics": sorted(diagnostics)}
