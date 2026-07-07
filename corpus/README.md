# corpus — the behavioral oracle

The committed golden vectors every `taut-shape-<lang>` engine must reproduce.
See [`../dev-docs/TautShapeOracle.md`](../dev-docs/TautShapeOracle.md) (§3 format,
§4 catalog, §5 generation, §6 lockstep) for the full contract.

- `log.v0.json` — one JSON file per shape+version. Each vector is a pure
  `(input message sequence) → (expected output message sequence)` pair; a step
  is one input message plus the exact ordered outputs it causes. Messages are
  the **taut jsoncodec form** of the `shape_log` schema (bytes base64, i64s as
  strings) plus a `type` discriminator. The `version` string
  (`"log.oracle/v0"`) is the single cross-repo pin. Conformance compares the
  whole observed output (golden), never per-field.
- `scripts/` — the authored *inputs* (producer/read scripts + node construction
  knobs, D6). `taut-shape-rs`'s `gen` mode replays these through the reference
  engine and fills in the expected outputs; a human reviews the diff before it
  is committed (the `glade_folds` discipline).

`log.v0.json` is generated, never hand-written; edit `scripts/` and re-run `gen`.

## The `value` shape (lww register)

- `value.v0.json` — the committed `value` oracle (`version "value.oracle/v0"`),
  11 vectors: lww basics (single/concurrent-lamport/tiebreak-origin/out-of-order/
  overwrite), idempotent duplicates, a live read-reflects-latest sequence,
  equivocation rejection (forked `(origin,seq)` by payload or by prev), and
  two-stream addressing. Same `(input → output)` step format as log-v0; value
  vectors carry no `node` knob (the register has no construction options).
- `scripts_value/` — the authored inputs.
- `value_gen.py` — the generator + lockstep gate (`--check`). Unlike log's
  `gen.py` (which shells to the external Rust `taut-shape-tool`), the `value`
  fold's reference is Python — `taut.crdt.glade_fold.fold_value`, glade's lww
  oracle — so value gen/gate is self-contained in the workspace with no
  per-language build:

  ```sh
  python3 corpus/value_gen.py            # rewrite corpus/value.v0.json
  python3 corpus/value_gen.py --check    # CI gate: nonzero if committed is stale
  ```
