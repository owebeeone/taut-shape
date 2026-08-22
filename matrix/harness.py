"""Shape-neutral crossed-pipe process orchestration for the live matrix."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import threading
from typing import BinaryIO, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PairResult:
    client_rc: int
    node_rc: int
    transcript: str
    node_err: str


def _relay(src: BinaryIO, dst: BinaryIO) -> None:
    """Copy bytes until EOF, then half-close the destination."""
    reader = src.read1 if hasattr(src, "read1") else src.read
    try:
        while chunk := reader(4096):
            dst.write(chunk)
            dst.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass
    finally:
        try:
            dst.close()
        except (OSError, ValueError):
            pass


def _drain(pipe: BinaryIO, sink: list[bytes]) -> None:
    try:
        sink.append(pipe.read())
    except (OSError, ValueError):
        sink.append(b"")


def _terminate_started(proc: subprocess.Popen[bytes] | None, timeout: float) -> None:
    """Stop, reap, and close every pipe owned by a started child."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
            proc.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for name in ("stdin", "stdout", "stderr"):
        pipe = getattr(proc, name, None)
        if pipe is not None:
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


def run_pair(
    node_command: Sequence[str],
    client_command: Sequence[str],
    *,
    node_env: Mapping[str, str] | None = None,
    client_env: Mapping[str, str] | None = None,
    timeout: float = 30,
) -> PairResult:
    """Run one node/client pair and guarantee cleanup on every exit path."""
    node: subprocess.Popen[bytes] | None = None
    client: subprocess.Popen[bytes] | None = None
    threads: list[threading.Thread] = []
    client_err: list[bytes] = []
    node_err: list[bytes] = []
    try:
        node = subprocess.Popen(
            list(node_command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=node_env,
        )
        client = subprocess.Popen(
            list(client_command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=client_env,
        )
        assert node.stdin is not None and node.stdout is not None and node.stderr is not None
        assert client.stdin is not None and client.stdout is not None and client.stderr is not None

        threads = [
            threading.Thread(target=_relay, args=(client.stdout, node.stdin), daemon=True),
            threading.Thread(target=_relay, args=(node.stdout, client.stdin), daemon=True),
            threading.Thread(target=_drain, args=(client.stderr, client_err), daemon=True),
            threading.Thread(target=_drain, args=(node.stderr, node_err), daemon=True),
        ]
        for thread in threads:
            thread.start()

        client.wait(timeout=timeout)
        node.wait(timeout=timeout)
        for thread in threads:
            thread.join(timeout=timeout)
        if any(thread.is_alive() for thread in threads):
            raise subprocess.TimeoutExpired("matrix pipe drain", timeout)

        assert client.returncode is not None and node.returncode is not None
        return PairResult(
            client_rc=client.returncode,
            node_rc=node.returncode,
            transcript=(client_err[0] if client_err else b"").decode("utf-8", "replace"),
            node_err=(node_err[0] if node_err else b"").decode("utf-8", "replace"),
        )
    finally:
        _terminate_started(client, timeout)
        _terminate_started(node, timeout)
        for thread in threads:
            thread.join(timeout=min(timeout, 1))
