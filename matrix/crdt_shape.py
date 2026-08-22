"""Live two-replica registrations for CRDT and its text specialization."""

from __future__ import annotations

import json
from pathlib import Path

from matrix.shapes import MatrixCase, MatrixShape

CRDT_SCENARIOS = ("concurrent", "causal_reorder", "equivocation", "bootstrap")
TEXT_SCENARIOS = ("sequential", "concurrent", "delete_before_insert", "bootstrap")


def canonicalize_crdt(transcript: str) -> dict:
    finals = [json.loads(line) for line in transcript.splitlines() if line.strip() and json.loads(line).get("type") == "replica_final"]
    if len(finals) != 1:
        return {"error": f"expected one replica_final, got {len(finals)}"}
    final = finals[0]
    final.pop("type", None)
    return final


def build_crdt_shape(matrix_dir: Path, *, text: bool = False) -> MatrixShape:
    name = "text_crdt" if text else "crdt"
    names = TEXT_SCENARIOS if text else CRDT_SCENARIOS
    directory = matrix_dir / "scenarios" / name

    def load_case(scenario: str) -> MatrixCase:
        if scenario not in names:
            raise KeyError(f"unknown {name} matrix scenario {scenario!r}")
        node = directory / f"{scenario}.node.json"
        client = directory / f"{scenario}.client.json"
        expected = json.loads((directory / f"{scenario}.expected.json").read_text())
        return MatrixCase(
            name=scenario,
            node_options=("--script", str(node)),
            client_options=("--stream-id", "replica-client", "--crdt-id", "crdt-A", "--replica-script", str(client)),
            expected=expected,
        )

    return MatrixShape(name=name, scenario_names=names, load_case=load_case, canonicalize=canonicalize_crdt)
