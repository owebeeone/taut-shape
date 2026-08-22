#!/usr/bin/env python3
"""Generate (or --check) the committed fold oracle `corpus/fold.v0.json`.

This is glade's M-LIMP fold oracle (`taut/corpus/glade_folds.json`) re-homed into
taut-shape (consolidation plan P2.S1): the pure `(op-set) -> folded state` layer
that sits *beneath* the message-level shape corpora. Three folds, all pure
functions of the attributed op-set (so convergence is guaranteed when every
replica folds the same set):

  - `value` (lww register): winner = max by `(lamport, origin, seq)`.
  - `log`   (append):       payloads in `(lamport, origin, seq)` order.
  - `equiv`:                a forked `(origin, seq)` (same key, different
    payload/prev) is equivocation — detected, never folded.

All dedup by `(origin, seq)` (idempotent delivery). The canonical reference is
`taut.crdt.glade_fold` in the taut runtime (the same authority `value_gen.py`
uses for `fold_value`); this driver imports it, so fold-corpus gen/gate is
self-contained in the workspace with no per-language build.

The authored *inputs* live in `corpus/scripts_fold/*.json` (raw ops, hex
payloads — glade's convention; the fold operates on the raw op envelope, not on
schema messages, so there is no jsoncodec round-trip here, unlike value_gen).
This script replays each through the reference fold and fills in `expect`.

`--check` is BOTH a lockstep gate (committed vs a fresh gen) AND a conflict
guard against glade's frozen oracle: it reads `taut/corpus/glade_folds.json`
(read-only) and asserts every glade fold vector's `(ops, expect)` agrees with
the taut-shape vector of the same name. A divergence is a design event (a
semantic conflict between the two oracles), not a stale-file nit — it fails loud.

Usage (run from anywhere; paths resolve to this file):
    python3 corpus/fold_gen.py            # (re)write corpus/fold.v0.json
    python3 corpus/fold_gen.py --check    # exit nonzero if stale OR conflicting
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO = CORPUS_DIR.parent
SCRIPTS_DIR = CORPUS_DIR / "scripts_fold"
OUT_JSON = CORPUS_DIR / "fold.v0.json"

# glade's frozen fold oracle (read-only) — the conflict-guard reference.
GLADE_FOLDS = REPO.parent / "taut" / "corpus" / "glade_folds.json"

VERSION = "fold.oracle/v0"

# Bootstrap the taut runtime (the fold reference) from the sibling workspace
# member, mirroring ir/regen.py and value_gen.py.
sys.path.insert(0, str(REPO.parent / "taut" / "src"))


def _run(fold: str, ops: list[dict]):
    """Fold a raw-op set through the taut reference; return the JSON-safe result.

    `value` -> winning payload hex (or None); `log` -> [payload hex]; `equiv` ->
    bool. Payloads arrive as hex strings and are converted to bytes for the fold,
    then re-encoded to hex on the way out — matching glade_folds.json exactly."""
    from taut.crdt.glade_fold import fold_log, fold_value, is_equivocation

    byte_ops = [{**o, "payload": bytes.fromhex(o["payload"]),
                 "prev": bytes.fromhex(o["prev"]) if o["prev"] else None}
                for o in ops]
    if fold == "value":
        w = fold_value(byte_ops)
        return None if w is None else w.hex()
    if fold == "log":
        return [p.hex() for p in fold_log(byte_ops)]
    if fold == "equiv":
        return is_equivocation(byte_ops)
    raise ValueError(f"unknown fold {fold!r}")


def _vector(script: dict) -> dict:
    vec = {"name": script["name"], "fold": script["fold"],
           "ops": script["ops"], "expect": _run(script["fold"], script["ops"])}
    if "comment" in script:
        vec["comment"] = script["comment"]
    return vec


def _corpus_text() -> str:
    scripts = sorted(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        raise SystemExit(f"no scripts found under {SCRIPTS_DIR}")
    vectors = [_vector(json.loads(p.read_text())) for p in scripts]
    corpus = {"shape": "fold", "version": VERSION, "vectors": vectors}
    return json.dumps(corpus, sort_keys=True, indent=2) + "\n"


def _conflict_guard(fresh: str) -> int:
    """Assert taut-shape's fold vectors agree with glade's frozen oracle.

    Compares by vector name on `(ops, expect)`. Any glade row whose semantics
    differ from the taut-shape row of the same name is a genuine oracle conflict
    (a design event) and fails loud. glade rows absent here (or vice versa) are
    reported too — the two oracles are meant to be the same fold contract."""
    if not GLADE_FOLDS.exists():
        print(f"note: {GLADE_FOLDS} not found — skipping glade conflict guard.")
        return 0
    glade = {v["name"]: v for v in json.loads(GLADE_FOLDS.read_text())}
    ours = {v["name"]: v for v in json.loads(fresh)["vectors"]}
    rc = 0
    for name, gv in glade.items():
        ov = ours.get(name)
        if ov is None:
            print(f"CONFLICT: glade fold vector {name!r} has no taut-shape "
                  f"counterpart in fold.v0.json.", file=sys.stderr)
            rc = 1
            continue
        if gv["ops"] != ov["ops"] or gv["expect"] != ov["expect"]:
            print(f"CONFLICT: fold vector {name!r} disagrees with glade's frozen "
                  f"oracle.\n  glade: ops={gv['ops']} expect={gv['expect']!r}"
                  f"\n  ours : ops={ov['ops']} expect={ov['expect']!r}",
                  file=sys.stderr)
            rc = 1
    extra = set(ours) - set(glade)
    if extra:
        print(f"note: taut-shape fold vectors not in glade's oracle: "
              f"{sorted(extra)} (additive coverage — fine).")
    if rc == 0:
        print(f"fold.v0.json agrees with glade's frozen oracle "
              f"({GLADE_FOLDS.relative_to(REPO.parent)}).")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if committed fold.v0.json is stale OR conflicts with "
             "glade's frozen oracle",
    )
    args = parser.parse_args(argv)

    fresh = _corpus_text()

    if args.check:
        committed = OUT_JSON.read_text() if OUT_JSON.exists() else ""
        rc = 0
        if committed != fresh:
            print(
                f"{OUT_JSON.relative_to(REPO)} is stale — run "
                f"`python3 corpus/fold_gen.py` and commit the result.",
                file=sys.stderr,
            )
            rc = 1
        else:
            print(f"{OUT_JSON.relative_to(REPO)} is in lockstep with the scripts.")
        rc |= _conflict_guard(fresh)
        return rc

    OUT_JSON.write_text(fresh)
    n = len(json.loads(fresh)["vectors"])
    print(f"wrote {OUT_JSON.relative_to(REPO)} ({n} vectors, {len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
