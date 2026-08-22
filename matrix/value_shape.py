"""Value-specific live scenarios and transcript normalization."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape


VALUE_SCENARIOS = (
    "empty",
    "lww_tiebreak",
    "same_origin_clock_reuse",
    "read_reflects_latest",
    "equivocation_rejected",
)


def canonicalize_value(transcript: str) -> dict:
    messages: list[dict] = []
    final: str | None = None
    for line in transcript.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("type") in ("read_response", "diagnostic"):
            messages.append(message)
        elif message.get("type") == "client_final":
            final = message.get("state")
    return {"messages": messages, "final": final}


def build_value_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios" / "value"

    def load_case(name: str) -> MatrixCase:
        if name not in VALUE_SCENARIOS:
            raise KeyError(f"unknown value matrix scenario {name!r}")
        expected = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        client = expected.pop("client")
        return MatrixCase(
            name=name,
            node_options=("--script", str(scenario_dir / f"{name}.script.json")),
            client_options=(
                "--stream-id",
                str(client["stream_id"]),
                "--value-id",
                str(client["value_id"]),
                "--reads",
                str(client["reads"]),
            ),
            expected=expected,
        )

    return MatrixShape(
        name="value",
        scenario_names=VALUE_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_value,
    )
