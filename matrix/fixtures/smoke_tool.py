#!/usr/bin/env python3
"""Tiny non-log CLI used only to contract-test the generic matrix harness."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("node", "client"))
    parser.add_argument("--shape", required=True)
    parser.add_argument("--script")
    parser.add_argument("--pid-file")
    parser.add_argument("--fail", action="store_true")
    parser.add_argument("--hang-on-eof", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.shape != "smoke":
        return 2
    if args.pid_file:
        Path(args.pid_file).write_text(str(os.getpid()))
    if args.fail:
        return 3

    if args.mode == "client":
        sys.stdout.buffer.write(b"ping\n")
        sys.stdout.buffer.flush()
        reply = sys.stdin.buffer.readline()
        if not reply:
            return 3
        event = {"kind": "reply", "value": reply.decode().strip()}
        sys.stderr.write(json.dumps(event, sort_keys=True) + "\n")
        return 0

    response = "pong"
    if args.script:
        response = str(json.loads(Path(args.script).read_text())["response"])
    for request in sys.stdin.buffer:
        if request == b"ping\n":
            sys.stdout.buffer.write(response.encode() + b"\n")
            sys.stdout.buffer.flush()
    if args.hang_on_eof:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
