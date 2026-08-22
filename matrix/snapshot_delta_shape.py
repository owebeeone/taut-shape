"""Expiry-profile live rows over the shared SWMR transport/core."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape
from matrix.swmr_shape import _canonical_response


SNAPSHOT_DELTA_SCENARIOS = (
    "normal_delivery",
    "retention_refresh",
    "reset_between_polls_refresh",
)


def canonicalize_snapshot_delta(transcript: str) -> dict:
    responses: list[dict] = []
    refreshes: list[dict] = []
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
        elif message.get("type") == "refresh_required":
            refreshes.append(message)
        elif message.get("type") == "diagnostic":
            diagnostics.append(message)
        elif message.get("type") == "client_final":
            final = message.get("state")
    return {
        "responses": responses,
        "refreshes": refreshes,
        "diagnostics": diagnostics,
        "final": final,
    }


def build_snapshot_delta_shape(matrix_dir: Path) -> MatrixShape:
    scenario_dir = matrix_dir / "scenarios" / "snapshot_delta"

    def load_case(name: str) -> MatrixCase:
        if name not in SNAPSHOT_DELTA_SCENARIOS:
            raise KeyError(f"unknown snapshot_delta matrix scenario {name!r}")
        expected = json.loads((scenario_dir / f"{name}.expected.json").read_text())
        client = expected.pop("client")
        node = expected.pop("node")
        client_options = [
            "--stream-id",
            str(client["stream_id"]),
            "--swmr-id",
            str(client["swmr_id"]),
        ]
        if client.get("cursor") is not None:
            client_options.extend(("--from", str(client["cursor"]["seq"])))
            client_options.extend(("--epoch", str(client["cursor"]["epoch"])))
        node_options = [
            "--stop-when",
            "last_reader",
            "--max-deltas",
            str(node["max_deltas"]),
            "--script",
            str(scenario_dir / f"{name}.script.json"),
        ]
        return MatrixCase(
            name=name,
            node_options=tuple(node_options),
            client_options=tuple(client_options),
            expected=expected,
        )

    return MatrixShape(
        name="snapshot_delta",
        scenario_names=SNAPSHOT_DELTA_SCENARIOS,
        load_case=load_case,
        canonicalize=canonicalize_snapshot_delta,
    )
