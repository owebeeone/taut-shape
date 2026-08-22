"""SWMR-specific live scenarios and transcript normalization."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape


SWMR_SCENARIOS = (
    "initial_snapshot_delta_eof",
    "retained_resume",
    "reset_between_polls",
    "timer_expiry",
    "writer_conflict",
)


def _cursor(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {"seq": int(value["seq"]), "epoch": int(value["epoch"])}


def _canonical_response(message: dict) -> dict:
    snapshot = message.get("snapshot")
    return {
        "swmr_id": message["swmr_id"],
        "stream_id": message["stream_id"],
        "snapshot": None
        if snapshot is None
        else {"seq": int(snapshot["seq"]), "payload": snapshot["payload"]},
        "deltas": [
            {
                "base_seq": int(delta["base_seq"]),
                "seq": int(delta["seq"]),
                "payload": delta["payload"],
            }
            for delta in message.get("deltas", [])
        ],
        "next_cursor": _cursor(message.get("next_cursor")),
        "state": message["state"],
        "reset_reason": message.get("reset_reason"),
        "error": message.get("error"),
        "reset_detail": message.get("reset_detail"),
    }


def canonicalize_swmr(transcript: str) -> dict:
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


def build_swmr_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios" / "swmr"

    def load_case(name: str) -> MatrixCase:
        if name not in SWMR_SCENARIOS:
            raise KeyError(f"unknown swmr matrix scenario {name!r}")
        expected = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        client = expected.pop("client")
        node = expected.pop("node")
        client_options = [
            "--stream-id",
            str(client["stream_ids"][0]),
            "--swmr-id",
            str(client["swmr_id"]),
        ]
        for stream_id in client["stream_ids"][1:]:
            client_options.extend(("--extra-stream-id", str(stream_id)))
        cursor = client.get("cursor")
        if cursor is not None:
            client_options.extend(("--from", str(cursor["seq"])))
            client_options.extend(("--epoch", str(cursor["epoch"])))
        if client.get("timeout_ms") is not None:
            client_options.extend(("--timeout-ms", str(client["timeout_ms"])))
        node_options = [
            "--stop-when",
            "last_reader",
            "--script",
            str(scenario_dir / f"{name}.script.json"),
        ]
        if node.get("max_deltas") is not None:
            node_options.extend(("--max-deltas", str(node["max_deltas"])))
        return MatrixCase(
            name=name,
            node_options=tuple(node_options),
            client_options=tuple(client_options),
            expected=expected,
        )

    return MatrixShape(
        name="swmr",
        scenario_names=SWMR_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_swmr,
    )
