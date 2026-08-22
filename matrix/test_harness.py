from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from matrix import harness
from matrix.driver import check_pairing
from matrix.shapes import MatrixCase, MatrixShape


_SMOKE_TOOL = Path(__file__).parent / "fixtures" / "smoke_tool.py"


def _canonicalize_smoke(transcript: str) -> list[dict]:
    return [json.loads(line) for line in transcript.splitlines() if line.strip()]


def _smoke_shape(case: MatrixCase) -> MatrixShape:
    def load_case(name: str) -> MatrixCase:
        if name != case.name:
            raise KeyError(name)
        return case

    return MatrixShape(
        name="smoke",
        scenario_names=(case.name,),
        load_case=load_case,
        canonicalize=_canonicalize_smoke,
    )


def test_second_shape_runs_through_the_generic_live_harness(tmp_path: Path) -> None:
    script = tmp_path / "smoke.json"
    script.write_text('{"response":"pong"}')
    case = MatrixCase(
        name="ping",
        node_options=("--script", str(script)),
        client_options=(),
        expected=[{"kind": "reply", "value": "pong"}],
    )
    shape = _smoke_shape(case)
    tool = [sys.executable, str(_SMOKE_TOOL)]
    ok, detail = check_pairing(
        "smoke",
        "fixture",
        "fixture",
        "ping",
        shapes={"smoke": shape},
        tools={"fixture": tool},
        env_for=lambda _language: dict(os.environ),
        timeout=3,
    )
    assert ok, detail


def test_client_start_failure_reaps_the_started_node(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNode:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.returncode: int | None = None
            self.killed = False
            self.waited = False

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int | None:
            self.waited = True
            return self.returncode

    node = FakeNode()
    launches = 0

    def fake_popen(*args, **kwargs):
        nonlocal launches
        launches += 1
        if launches == 1:
            return node
        raise FileNotFoundError("client tool missing")

    monkeypatch.setattr(harness.subprocess, "Popen", fake_popen)
    with pytest.raises(FileNotFoundError, match="client tool missing"):
        harness.run_pair(["node"], ["client"], timeout=0.2)

    assert node.killed and node.waited
    assert node.stdin.closed and node.stdout.closed and node.stderr.closed


def test_protocol_failure_reaps_a_hung_peer(tmp_path: Path) -> None:
    node_pid_file = tmp_path / "node.pid"
    client_pid_file = tmp_path / "client.pid"
    tool = [sys.executable, str(_SMOKE_TOOL)]
    case = MatrixCase(
        name="failure",
        node_options=("--pid-file", str(node_pid_file), "--hang-on-eof"),
        client_options=("--pid-file", str(client_pid_file), "--fail"),
        expected=[],
    )
    shape = _smoke_shape(case)

    with pytest.raises(subprocess.TimeoutExpired):
        harness.run_pair(
            shape.node_command(tool, case),
            shape.client_command(tool, case),
            timeout=0.5,
        )

    for pid_file in (node_pid_file, client_pid_file):
        pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
