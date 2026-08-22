#!/usr/bin/env python3
"""Live cross-language matrix over a shape-neutral process harness.

The corpus proves each engine independently. This runner proves every selected
node/client language pair over the real framing while delegating commands,
scenarios, and transcript canonicalization to the selected shape registration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

if not __package__:  # make the local package importable for `python3 matrix/driver.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matrix.harness import run_pair
from matrix.atom_shape import build_atom_shape
from matrix.log_shape import build_log_shape
from matrix.shapes import MatrixShape, ShapeRegistry
from matrix.value_shape import build_value_shape
from matrix.stream_shape import build_stream_shape
from matrix.swmr_shape import build_swmr_shape
from matrix.snapshot_delta_shape import build_snapshot_delta_shape
from matrix.crdt_shape import build_crdt_shape


_MATRIX_DIR = Path(__file__).resolve().parent
_TAUT_DEV = _MATRIX_DIR.parents[1]
_RS_BIN = os.environ.get(
    "TAUT_SHAPE_RS",
    str(_TAUT_DEV / "taut-shape-rs" / "target" / "debug" / "taut-shape-tool"),
)
_TS_CLI = str(_TAUT_DEV / "taut-shape-ts" / "src" / "cli.ts")
_PY_SRC = str(_TAUT_DEV / "taut-shape-py" / "src")
_TAUT_SRC = str(_TAUT_DEV / "taut" / "src")

TOOLS: dict[str, list[str]] = {
    "rs": [_RS_BIN],
    "ts": ["node", "--experimental-strip-types", _TS_CLI],
    "py": [sys.executable, "-m", "taut_shape.tool"],
}
LANGUAGES = ("rs", "ts", "py")
SHAPES: dict[str, MatrixShape] = {
    "atom": build_atom_shape(_MATRIX_DIR),
    "crdt": build_crdt_shape(_MATRIX_DIR),
    "log": build_log_shape(_MATRIX_DIR),
    "snapshot_delta": build_snapshot_delta_shape(_MATRIX_DIR),
    "stream": build_stream_shape(_MATRIX_DIR),
    "swmr": build_swmr_shape(_MATRIX_DIR),
    "text_crdt": build_crdt_shape(_MATRIX_DIR, text=True),
    "value": build_value_shape(_MATRIX_DIR),
}
TIMEOUT_SECONDS = 30


def environment_for(language: str) -> dict[str, str]:
    env = dict(os.environ)
    if language == "py":
        previous = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            _PY_SRC
            + os.pathsep
            + _TAUT_SRC
            + (os.pathsep + previous if previous else "")
        )
    return env


def _preflight_python_env() -> str | None:
    if "py" not in LANGUAGES:
        return None
    env = environment_for("py")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import taut_shape.tool"],
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except OSError as error:
        return f"preflight: could not launch {sys.executable!r}: {error}"
    except subprocess.TimeoutExpired:
        return "preflight: import check of 'taut_shape.tool' timed out"
    if proc.returncode == 0:
        return None
    lines = [line for line in proc.stderr.strip().splitlines() if line.strip()]
    last_line = lines[-1] if lines else "(no stderr captured)"
    return (
        "preflight FAILED: cannot import 'taut_shape.tool' in the py child "
        "environment used by the matrix.\n"
        f"  error: {last_line}\n"
        f"  PYTHONPATH attempted: {env.get('PYTHONPATH', '(unset)')}\n"
        f"    - taut-shape-py src: {_PY_SRC}\n"
        f"    - sibling taut src:  {_TAUT_SRC}"
    )


def check_pairing(
    shape_name: str,
    node_language: str,
    client_language: str,
    scenario_name: str,
    *,
    shapes: ShapeRegistry = SHAPES,
    tools: Mapping[str, Sequence[str]] = TOOLS,
    env_for: Callable[[str], Mapping[str, str]] = environment_for,
    timeout: float = TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Run and compare one registered shape/language/scenario cell."""
    try:
        shape = shapes[shape_name]
        case = shape.load_case(scenario_name)
        result = run_pair(
            shape.node_command(tools[node_language], case),
            shape.client_command(tools[client_language], case),
            node_env=env_for(node_language),
            client_env=env_for(client_language),
            timeout=timeout,
        )
    except OSError as error:
        return False, f"FAIL (tool missing): {error}"

    problems: list[str] = []
    if result.client_rc != 0:
        problems.append(f"client exit {result.client_rc}")
    if result.node_rc != 0:
        problems.append(f"node exit {result.node_rc}")
    actual = shape.canonicalize(result.transcript)
    if actual != case.expected:
        problems.append(
            "transcript differs:\n  want="
            + json.dumps(case.expected, sort_keys=True)
            + "\n  got ="
            + json.dumps(actual, sort_keys=True)
        )
    if problems:
        detail = "; ".join(problems)
        if result.node_err.strip():
            detail += "\n  node stderr: " + result.node_err.strip()
        return False, detail
    return True, ""


def matrix_cases(
    shapes: ShapeRegistry = SHAPES,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (shape_name, scenario_name)
        for shape_name, shape in shapes.items()
        for scenario_name in shape.scenario_names
    )


try:
    import pytest

    @pytest.fixture(scope="session", autouse=True)
    def _matrix_preflight():
        error = _preflight_python_env()
        if error:
            pytest.exit(error, returncode=1)

    @pytest.mark.parametrize(("shape_name", "scenario_name"), matrix_cases())
    @pytest.mark.parametrize("client_language", LANGUAGES)
    @pytest.mark.parametrize("node_language", LANGUAGES)
    def test_matrix(
        shape_name: str,
        scenario_name: str,
        node_language: str,
        client_language: str,
    ) -> None:
        ok, detail = check_pairing(
            shape_name,
            node_language,
            client_language,
            scenario_name,
        )
        assert ok, (
            f"shape={shape_name} node={node_language} client={client_language} "
            f"scenario={scenario_name}: {detail}"
        )
except ImportError:  # pragma: no cover - pytest is optional for the plain runner
    pass


def _main() -> int:
    error = _preflight_python_env()
    if error:
        print(error, file=sys.stderr)
        return 1

    rc = 0
    for shape_name, scenario_name in matrix_cases():
        print(f"\n=== shape: {shape_name}; scenario: {scenario_name} ===")
        print("node\\client  " + "  ".join(f"{lang:>6}" for lang in LANGUAGES))
        for node_language in LANGUAGES:
            cells: list[str] = []
            for client_language in LANGUAGES:
                try:
                    ok, detail = check_pairing(
                        shape_name,
                        node_language,
                        client_language,
                        scenario_name,
                    )
                except subprocess.TimeoutExpired:
                    ok, detail = False, "TIMEOUT"
                cells.append("  PASS" if ok else "  FAIL")
                if not ok:
                    rc = 1
                    print(
                        f"  ! {shape_name} {node_language}->{client_language}: {detail}",
                        file=sys.stderr,
                    )
            print(f"  {node_language:<9} " + "  ".join(cells))
    print("\nOK" if rc == 0 else "\nFAILURES (see stderr)")
    return rc


if __name__ == "__main__":
    raise SystemExit(_main())
