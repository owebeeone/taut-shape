#!/usr/bin/env python3
"""Regenerate (or --check) the exported shape_log IR JSON from the schema.

The IR JSON `ir/shape_log.ir.json` is the language-neutral artifact every
`taut-shape-<lang>` consumes (D17) — it must always be a faithful export of the
authored schema `ir/shape_log.taut.py`. This script is the lockstep gate that
keeps the two in step:

  * default (write) mode  — re-export the schema over the committed JSON, so a
    schema edit is one command away from an updated artifact.
  * ``--check`` mode      — fail (nonzero exit) if the committed JSON differs
    from a fresh export. Wire this into CI so a schema change that forgets to
    re-run the export is caught, exactly like taut's own corpus lockstep gates.

Export form is byte-identical to `taut.ir.export`:
``json.dumps(schema_json(SCHEMA), indent=2) + "\n"``.

Run from anywhere; paths are resolved relative to this file. The taut builder is
bootstrapped onto PYTHONPATH from the sibling ``../taut/src`` (the taut-dev
workspace layout), matching the bootstrap in ``shape_log.taut.py`` itself.

  python3 ir/regen.py            # rewrite ir/shape_log.ir.json from the schema
  python3 ir/regen.py --check    # exit nonzero if committed JSON is stale
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

IR_DIR = Path(__file__).resolve().parent
REPO = IR_DIR.parent
SCHEMA_PY = IR_DIR / "shape_log.taut.py"
IR_JSON = IR_DIR / "shape_log.ir.json"

# Bootstrap the taut builder from the sibling workspace member, mirroring the
# sys.path insert in shape_log.taut.py (taut is ../taut relative to this repo).
sys.path.insert(0, str(REPO.parent / "taut" / "src"))


def _load_schema():
    """Import shape_log.taut.py by path and return its SCHEMA object."""
    spec = importlib.util.spec_from_file_location("shape_log_taut", SCHEMA_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCHEMA


def _export_text() -> str:
    from taut.ir.export import schema_json

    return json.dumps(schema_json(_load_schema()), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if the committed IR JSON differs from a fresh export",
    )
    args = parser.parse_args(argv)

    fresh = _export_text()

    if args.check:
        committed = IR_JSON.read_text() if IR_JSON.exists() else ""
        if committed != fresh:
            rel = IR_JSON.relative_to(REPO)
            print(
                f"{rel} is out of date with {SCHEMA_PY.name} — "
                f"run `python3 ir/regen.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{IR_JSON.relative_to(REPO)} is in lockstep with the schema.")
        return 0

    IR_JSON.write_text(fresh)
    print(f"wrote {IR_JSON.relative_to(REPO)} ({len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
