"""Stream-specific live scenarios and transcript normalization."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape


STREAM_SCENARIOS = (
    "live_tail_to_eof",
    "timer_expiry",
    "close_failed",
    "slow_reader_drop",
    "dropped_reconnect",
)


def _canonical_response(message: dict) -> dict:
    return {
        "stream_id": message["stream_id"],
        "records": [
            {"seq": int(record["seq"]), "payload": record["payload"]}
            for record in message["records"]
        ],
        "next_position": int(message["next_position"]["seq"]),
        "state": message["state"],
        "error": message.get("error"),
    }


def canonicalize_stream(transcript: str) -> dict:
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


def build_stream_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios" / "stream"

    def load_case(name: str) -> MatrixCase:
        if name not in STREAM_SCENARIOS:
            raise KeyError(f"unknown stream matrix scenario {name!r}")
        expected = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        client = expected.pop("client")
        node = expected.pop("node")
        client_options = ["--stream-id", str(client["stream_ids"][0])]
        for stream_id in client["stream_ids"][1:]:
            client_options.extend(("--extra-stream-id", str(stream_id)))
        for key, option in (
            ("max_records", "--max-records"),
            ("max_bytes", "--max-bytes"),
            ("timeout_ms", "--timeout-ms"),
            ("resume_after_data", "--resume-after-data"),
        ):
            if client.get(key) is not None:
                client_options.extend((option, str(client[key])))
        for stream_id in client.get("pause_stream_ids", []):
            client_options.extend(("--pause-stream-id", str(stream_id)))
        if client.get("reconnect_dropped"):
            client_options.append("--reconnect-dropped")
        return MatrixCase(
            name=name,
            node_options=(
                "--stop-when",
                "last_reader",
                "--capacity-records",
                str(node["capacity_records"]),
                "--script",
                str(scenario_dir / f"{name}.script.json"),
            ),
            client_options=tuple(client_options),
            expected=expected,
        )

    return MatrixShape(
        name="stream",
        scenario_names=STREAM_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_stream,
    )
