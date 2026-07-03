#!/usr/bin/env python3
"""matrix/driver.py — the taut-shape interop matrix (pytest).

The corpus proves each engine against the spec *alone*; the matrix proves the
engines against *each other*, live, over the real wire framing. For every
language pair (X, Y) in {rs, ts, py}^2 it spawns ``node(X)`` (owning the engine
and a scenario's producer ``--script``) and ``client(Y)`` (the reading cursor
loop), crosses their stdio into the Oracle §7 topology ::

        client.stdout ──frames──▶ node.stdin      (LogReadRequest → node)
        node.stdout   ──frames──▶ client.stdin    (LogReadResponse → client)

drains both concurrently, collects the client's OOB JSONL transcript (stderr),
canonicalises it (see ``canonicalise`` — the three client tools emit three
different transcript *dialects*; only the wire framing between them is byte-for-
byte identical), and compares the whole canonical transcript to the scenario's
committed golden (``scenarios/<name>.expected.json``).

Interop scenarios avoid ``timeout_ms > 0`` (real clocks are nondeterministic
across processes): every reader uses a *held* read, and the producer ``--script``
releases it deterministically after the k-th client frame. Timer behaviour is
corpus-only.

Run:  ``pytest matrix/driver.py -v``   (or ``python3 matrix/driver.py`` for a
plain pass table without pytest).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# ── configuration (paths/commands — edit here to relocate tools) ─────────────

# Repo layout: this file lives at <taut-dev>/taut-shape/matrix/driver.py.
_MATRIX_DIR = Path(__file__).resolve().parent
_TAUT_DEV = _MATRIX_DIR.parents[1]  # <taut-dev>/

# Built rs binary (cargo build -p taut-shape-tool). Override with $TAUT_SHAPE_RS.
_RS_BIN = os.environ.get(
    "TAUT_SHAPE_RS",
    str(_TAUT_DEV / "taut-shape-rs" / "target" / "debug" / "taut-shape-tool"),
)
_TS_CLI = str(_TAUT_DEV / "taut-shape-ts" / "src" / "cli.ts")
_PY_SRC = str(_TAUT_DEV / "taut-shape-py" / "src")

# Per-language argv prefix (mode is appended). Everything is a list, so paths
# with spaces survive. The py tool runs via ``-m`` with PYTHONPATH set below.
_TOOLS: dict[str, list[str]] = {
    "rs": [_RS_BIN],
    "ts": ["node", "--experimental-strip-types", _TS_CLI],
    "py": [sys.executable, "-m", "taut_shape.tool"],
}

# Extra env per language (py needs its src on PYTHONPATH; rs/ts need nothing).
def _env_for(lang: str) -> dict[str, str]:
    env = dict(os.environ)
    if lang == "py":
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = _PY_SRC + (os.pathsep + prev if prev else "")
    return env


LANGS = ("rs", "ts", "py")
SCENARIOS = (
    "catchup_to_eof",
    "live_tail_to_eof",
    "close_mid_tail",
    "evict_expired_resume",
)

_TIMEOUT_S = 30  # per-pairing wall-clock cap (a stuck held read must not hang CI)


# ── command construction ─────────────────────────────────────────────────────

def _node_cmd(lang: str, script_path: str) -> list[str]:
    return [*_TOOLS[lang], "node", "--stop-when", "last_reader", "--script", script_path]


def _client_cmd(lang: str, stream_id: str, from_seq: int) -> list[str]:
    return [*_TOOLS[lang], "client", "--stream-id", stream_id, "--from", str(from_seq)]


# ── the crossed-pipe run ─────────────────────────────────────────────────────

def _relay(src, dst) -> None:
    """Copy bytes src→dst until EOF, then close dst (propagates the half-close so
    the peer sees stdin end). Broken-pipe on a peer that already exited is fine."""
    # read1() returns whatever a single underlying read yields (frames are tiny;
    # a fill-the-buffer read(4096) would deadlock waiting for bytes that only
    # arrive after the peer answers this frame).
    reader = src.read1 if hasattr(src, "read1") else src.read
    try:
        while True:
            chunk = reader(4096)
            if not chunk:
                break
            dst.write(chunk)
            dst.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass
    finally:
        try:
            dst.close()
        except OSError:
            pass


def run_pair(node_lang: str, client_lang: str, script_path: str,
             stream_id: str, from_seq: int) -> dict:
    """Spawn node(X) ⊗ client(Y) over crossed pipes, drain concurrently, and
    return ``{"client_rc", "node_rc", "transcript"(client stderr text),
    "node_err"}``. Raises on timeout (a scenario that fails to terminate)."""
    node = subprocess.Popen(
        _node_cmd(node_lang, script_path),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_env_for(node_lang),
    )
    client = subprocess.Popen(
        _client_cmd(client_lang, stream_id, from_seq),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_env_for(client_lang),
    )

    # Cross the data pipes: client→node (requests), node→client (responses).
    t_req = threading.Thread(target=_relay, args=(client.stdout, node.stdin), daemon=True)
    t_resp = threading.Thread(target=_relay, args=(node.stdout, client.stdin), daemon=True)
    t_req.start()
    t_resp.start()

    # Drain both stderrs from threads so a full pipe buffer can never block a tool.
    client_err: list[bytes] = []
    node_err: list[bytes] = []
    te_c = threading.Thread(target=lambda: client_err.append(client.stderr.read()), daemon=True)
    te_n = threading.Thread(target=lambda: node_err.append(node.stderr.read()), daemon=True)
    te_c.start()
    te_n.start()

    try:
        client.wait(timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        client.kill()
        node.kill()
        raise
    # Client done → its stdout closed → relay closes node.stdin → node drains & exits.
    try:
        node.wait(timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        node.kill()
        raise

    for t in (t_req, t_resp, te_c, te_n):
        t.join(timeout=_TIMEOUT_S)

    return {
        "client_rc": client.returncode,
        "node_rc": node.returncode,
        "transcript": (client_err[0] if client_err else b"").decode("utf-8", "replace"),
        "node_err": (node_err[0] if node_err else b"").decode("utf-8", "replace"),
    }


# ── canonicalisation (bridge the three client transcript dialects) ───────────

# The three clients emit semantically identical read answers but in different
# JSON dialects:
#   rs : alphabetical keys; final line {"state":S,"type":"client_final"}.
#   ts : insertion-order keys; final {"type":"client_final","stream_id",...,"state":S,"cursor"}.
#   py : json.dumps default (spaces); final {"final":S,"next_seq":N}; a channel-EOF
#        sentinel {"final":"eof_channel", ...} when the node hangs up early.
# We parse each line into ONE canonical record so a single golden covers all 9
# pairings. A ``read_response`` line → a response record; any client_final /
# {"final":...} line → the terminal marker.

def _canon_response(obj: dict) -> dict:
    """One received read_response → canonical response record."""
    recs = [
        {"seq": int(r["seq"]), "payload": r["payload"]}
        for r in obj.get("records", [])
    ]
    return {
        "state": obj["state"],
        "next_seq": int(obj["next_cursor"]["seq"]),
        "records": recs,
        "error": obj.get("error"),
    }


def canonicalise(transcript: str) -> dict:
    """Parse a client's raw JSONL stderr transcript into the canonical form
    ``{"responses":[...], "final": <state>}``. Dialect-agnostic."""
    responses: list[dict] = []
    final: str | None = None
    for line in transcript.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # A tool's non-transcript stderr noise (usage/error text). Skip it;
            # a genuine failure shows up as a missing/mismatched response.
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "read_response":
            responses.append(_canon_response(obj))
        elif obj.get("type") == "client_final":
            # rs / ts terminal line.
            final = obj.get("state")
        elif "final" in obj:
            # py terminal line: {"final": <state|eof_channel>, "next_seq": N}.
            fin = obj["final"]
            final = "eof" if fin == "eof_channel" else fin
        # else: an ignored control-frame mirror (producer_stop/diagnostic/etc.).
    return {"responses": responses, "final": final}


def load_expected(scenario: str) -> dict:
    exp = json.loads((_MATRIX_DIR / "scenarios" / f"{scenario}.expected.json").read_text())
    return {
        "responses": [
            {"state": r["state"], "next_seq": int(r["next_seq"]),
             "records": [{"seq": int(x["seq"]), "payload": x["payload"]} for x in r["records"]],
             "error": r.get("error")}
            for r in exp["responses"]
        ],
        "final": exp["final"],
        "read_args": exp["read_args"],
    }


# ── the pairing check (shared by pytest and the __main__ table) ──────────────

def check_pairing(node_lang: str, client_lang: str, scenario: str):
    """Run one (node, client, scenario) pairing. Returns (ok, detail) where
    detail is a diff string on mismatch, "" on pass."""
    exp = load_expected(scenario)
    script = str(_MATRIX_DIR / "scenarios" / f"{scenario}.script.json")
    ra = exp["read_args"]
    res = run_pair(node_lang, client_lang, script, ra["stream_id"], int(ra["from"]))
    got = canonicalise(res["transcript"])
    want = {"responses": exp["responses"], "final": exp["final"]}

    problems = []
    if res["client_rc"] != 0:
        problems.append(f"client exit {res['client_rc']}")
    if res["node_rc"] != 0:
        problems.append(f"node exit {res['node_rc']}")
    if got["responses"] != want["responses"]:
        problems.append(
            "responses differ:\n  want=" + json.dumps(want["responses"])
            + "\n  got =" + json.dumps(got["responses"])
        )
    if got["final"] != want["final"]:
        problems.append(f"final: want {want['final']!r} got {got['final']!r}")
    if problems:
        detail = "; ".join(problems)
        if res["node_err"].strip():
            detail += "\n  node stderr: " + res["node_err"].strip()
        return False, detail
    return True, ""


# ── pytest entry points ──────────────────────────────────────────────────────

try:
    import pytest

    @pytest.mark.parametrize("scenario", SCENARIOS)
    @pytest.mark.parametrize("client_lang", LANGS)
    @pytest.mark.parametrize("node_lang", LANGS)
    def test_matrix(node_lang, client_lang, scenario):
        ok, detail = check_pairing(node_lang, client_lang, scenario)
        assert ok, f"node={node_lang} client={client_lang} scenario={scenario}: {detail}"
except ImportError:  # pragma: no cover — pytest optional for the plain runner
    pass


# ── plain-runner pass table (no pytest) ──────────────────────────────────────

def _main() -> int:
    rc = 0
    for scenario in SCENARIOS:
        print(f"\n=== scenario: {scenario} ===")
        header = "node\\client  " + "  ".join(f"{c:>6}" for c in LANGS)
        print(header)
        for node_lang in LANGS:
            cells = []
            for client_lang in LANGS:
                try:
                    ok, detail = check_pairing(node_lang, client_lang, scenario)
                except subprocess.TimeoutExpired:
                    ok, detail = False, "TIMEOUT"
                cells.append("  PASS" if ok else "  FAIL")
                if not ok:
                    rc = 1
                    print(f"  ! {node_lang}->{client_lang}: {detail}", file=sys.stderr)
            print(f"  {node_lang:<9} " + "  ".join(cells))
    print("\nOK" if rc == 0 else "\nFAILURES (see stderr)")
    return rc


if __name__ == "__main__":
    sys.exit(_main())
