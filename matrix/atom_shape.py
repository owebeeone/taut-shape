"""Atom-specific live scenarios and transcript normalization."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape


ATOM_SCENARIOS = (
    "held_replacement_to_eof",
    "timer_expiry",
    "terminal_drain",
    "close_failed",
    "multi_reader",
)


def _canonical_response(message: dict) -> dict:
    value = message.get("value")
    return {
        "atom_id": message["atom_id"],
        "stream_id": message["stream_id"],
        "value": None
        if value is None
        else {"version": int(value["version"]), "payload": value["payload"]},
        "next_version": int(message["next_version"]["version"]),
        "state": message["state"],
        "error": message.get("error"),
    }


def canonicalize_atom(transcript: str) -> dict:
    responses: list[dict] = []
    diagnostics: list[dict] = []
    final: str | None = None
    for line in transcript.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("type") == "read_response":
            responses.append(_canonical_response(message))
        elif message.get("type") == "diagnostic":
            diagnostics.append(message)
        elif message.get("type") == "client_final":
            final = message.get("state")
    return {"responses": responses, "diagnostics": diagnostics, "final": final}


def build_atom_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios" / "atom"

    def load_case(name: str) -> MatrixCase:
        if name not in ATOM_SCENARIOS:
            raise KeyError(f"unknown atom matrix scenario {name!r}")
        expected = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        client = expected.pop("client")
        client_options = [
            "--stream-id",
            str(client["stream_ids"][0]),
            "--atom-id",
            str(client["atom_id"]),
            "--from",
            str(client["from"]),
        ]
        for stream_id in client["stream_ids"][1:]:
            client_options.extend(("--extra-stream-id", str(stream_id)))
        if client.get("timeout_ms") is not None:
            client_options.extend(("--timeout-ms", str(client["timeout_ms"])))
        return MatrixCase(
            name=name,
            node_options=(
                "--stop-when",
                "last_reader",
                "--script",
                str(scenario_dir / f"{name}.script.json"),
            ),
            client_options=tuple(client_options),
            expected=expected,
        )

    return MatrixShape(
        name="atom",
        scenario_names=ATOM_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_atom,
    )
