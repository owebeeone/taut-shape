"""Log-specific scenarios and transcript normalization for the live matrix."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape


LOG_SCENARIOS = (
    "catchup_to_eof",
    "live_tail_to_eof",
    "close_mid_tail",
    "evict_expired_resume",
)


def _canonical_response(obj: dict) -> dict:
    return {
        "state": obj["state"],
        "next_seq": int(obj["next_cursor"]["seq"]),
        "records": [
            {"seq": int(record["seq"]), "payload": record["payload"]}
            for record in obj.get("records", [])
        ],
        "error": obj.get("error"),
    }


def canonicalize_log(transcript: str) -> dict:
    """Normalize the three clients' JSONL dialects into one log transcript."""
    responses: list[dict] = []
    final: str | None = None
    for line in transcript.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "read_response":
            responses.append(_canonical_response(obj))
        elif obj.get("type") == "client_final":
            final = obj.get("state")
        elif "final" in obj:
            value = obj["final"]
            final = "eof" if value == "eof_channel" else value
    return {"responses": responses, "final": final}


def build_log_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios"

    def load_case(name: str) -> MatrixCase:
        if name not in LOG_SCENARIOS:
            raise KeyError(f"unknown log matrix scenario {name!r}")
        raw = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        expected = {
            "responses": [
                {
                    "state": response["state"],
                    "next_seq": int(response["next_seq"]),
                    "records": [
                        {"seq": int(record["seq"]), "payload": record["payload"]}
                        for record in response["records"]
                    ],
                    "error": response.get("error"),
                }
                for response in raw["responses"]
            ],
            "final": raw["final"],
        }
        read_args = raw["read_args"]
        return MatrixCase(
            name=name,
            node_options=(
                "--stop-when",
                "last_reader",
                "--script",
                str(scenario_dir / f"{name}.script.json"),
            ),
            client_options=(
                "--stream-id",
                str(read_args["stream_id"]),
                "--from",
                str(read_args["from"]),
            ),
            expected=expected,
        )

    return MatrixShape(
        name="log",
        scenario_names=LOG_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_log,
    )
