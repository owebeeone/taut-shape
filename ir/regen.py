#!/usr/bin/env python3
"""Regenerate (or --check) the exported shape IR JSON from each schema.

The IR JSON (`ir/shape_log.ir.json`, `ir/shape_value.ir.json`, …) is the
language-neutral artifact every `taut-shape-<lang>` consumes (D17) — each must
always be a faithful export of its authored schema (`ir/shape_<name>.taut.py`).
This script is the lockstep gate that keeps every (schema, IR) pair in step:

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

# Every authored shape schema and its exported IR artifact. Add a row per shape.
SHAPES = [
    (IR_DIR / "shape_log.taut.py", IR_DIR / "shape_log.ir.json"),
    (IR_DIR / "shape_value.taut.py", IR_DIR / "shape_value.ir.json"),
    (IR_DIR / "shape_atom.taut.py", IR_DIR / "shape_atom.ir.json"),
    (IR_DIR / "shape_stream.taut.py", IR_DIR / "shape_stream.ir.json"),
    (IR_DIR / "shape_swmr.taut.py", IR_DIR / "shape_swmr.ir.json"),
    (IR_DIR / "shape_crdt.taut.py", IR_DIR / "shape_crdt.ir.json"),
]

# Bootstrap the taut builder from the sibling workspace member, mirroring the
# sys.path insert in each shape_*.taut.py (taut is ../taut relative to this repo).
sys.path.insert(0, str(REPO.parent / "taut" / "src"))


def _load_schema(schema_py: Path):
    """Import a shape_*.taut.py by path and return its SCHEMA object."""
    spec = importlib.util.spec_from_file_location(schema_py.stem, schema_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCHEMA


def _export_text(schema_py: Path) -> str:
    from taut.ir.export import schema_json

    return json.dumps(schema_json(_load_schema(schema_py)), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if any committed IR JSON differs from a fresh export",
    )
    args = parser.parse_args(argv)

    rc = 0
    for schema_py, ir_json in SHAPES:
        fresh = _export_text(schema_py)
        if args.check:
            committed = ir_json.read_text() if ir_json.exists() else ""
            if committed != fresh:
                print(
                    f"{ir_json.relative_to(REPO)} is out of date with "
                    f"{schema_py.name} — run `python3 ir/regen.py` and commit "
                    f"the result.",
                    file=sys.stderr,
                )
                rc = 1
            else:
                print(f"{ir_json.relative_to(REPO)} is in lockstep with the schema.")
        else:
            ir_json.write_text(fresh)
            print(f"wrote {ir_json.relative_to(REPO)} ({len(fresh)} bytes)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
