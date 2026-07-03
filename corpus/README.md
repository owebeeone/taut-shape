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
