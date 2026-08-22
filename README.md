# taut-shape

The **contract repo** for Taut delivery shapes (`log`, `value`, `atom`, `stream`,
`swmr`, `crdt`, and the `snapshot_delta` / `text_crdt` profiles).
This repo owns the
*shared, language-neutral* artifacts that every `taut-shape-<lang>`
implementation conforms to; it holds **no shipped engine code of its own**
(the reference engines embedded in the `atom`/`stream`/`swmr`/`value` corpus
generators are gen-tooling only, not a shipped runtime — review F5-09). The
rule the repo enforces: *the reference code is optional; the oracle is
mandatory.*

The canonical catalogue and engine/profile boundaries are decided in
[`../dev-docs/TautShapeCatalogDecision.md`](../dev-docs/TautShapeCatalogDecision.md).
This repo implements behavioral contracts from that catalogue; catalogue
membership alone is not a runtime capability claim.

What lives here:

1. **Design docs** — the normative contract (`dev-docs/`).
2. **The `shape_log` schema** — the taut-declared, payload-agnostic message
   vocabulary and its exported language-neutral IR (`ir/`).
3. **The behavioral oracle corpus** — golden `(input msgs) → (output msgs)`
   vectors every engine must reproduce (`corpus/`).
4. **The interop matrix** — a driver that runs `node(X) ⊗ client(Y)` across
   languages over the real wire framing (`matrix/`).

## dev-docs (read these first — they are the contract)

- [`dev-docs/TautClientImplPlan.md`](dev-docs/TautClientImplPlan.md) — the shared,
  language-neutral plan: §2 engine model (the pure mailbox `LogNode`), §3 message
  vocabulary + §3.4 read-resolution rules, §4 pinned decisions **D1–D17**. Every
  `taut-shape-<lang>/dev-docs/InitialPlan.md` references this and resolves its
  `«SPECIALIZE: …»` markers.
- [`dev-docs/TautShapeArchitecture.md`](dev-docs/TautShapeArchitecture.md) — the
  design: the store-core / session-table split, backing, mailbox engine + shells.
- [`dev-docs/TautShapeOracle.md`](dev-docs/TautShapeOracle.md) — the conformance
  contract: corpus format, the log-v0 vector catalog, generation, the lockstep
  gate, and the interop matrix.

The reference Rust rendering (the oracle generator) is a sibling repo:
[`../taut-shape-rs/dev-docs/InitialPlan.md`](../taut-shape-rs/dev-docs/InitialPlan.md).

## ir/ — the shape schemas

- [`ir/shape_log.taut.py`](ir/shape_log.taut.py) — the authored schema: the
  `log` delivery-shape wire vocabulary (messages + codecs, no `service`, D17).
  `LogRecord.payload = BYTES` carries the method's append-slot message already
  taut-encoded (the glade `Op.payload` pattern), so the engine stays
  payload-agnostic.
- [`ir/shape_value.taut.py`](ir/shape_value.taut.py) — the `value` (lww register)
  wire vocabulary: a *set* of attributed whole-value writes (`ValueSet.payload =
  BYTES`) folds to a single winner (glade's `fold_value`, extracted here per
  `TautShapeGladeConsolidation.md` P1). Payload-agnostic; MV surfacing deferred.
- [`ir/shape_atom.taut.py`](ir/shape_atom.taut.py) — the `atom` (latest-only
  state) wire vocabulary: replace-only delivery over a single slot, a
  `version` change counter (not a `seq`), no window/floor/expiry
  (`TautShapeRoadmap.md` §1 — a strict simplification of `log`). Payload-agnostic.
- [`ir/shape_stream.taut.py`](ir/shape_stream.taut.py) — the disposable ordered
  `stream` vocabulary: a bounded ring, node-owned reader positions, live-only
  late join, and explicit slow-reader drop. Policy is frozen in
  [`dev-docs/TautShapeStreamDecision.md`](dev-docs/TautShapeStreamDecision.md).
- [`ir/shape_swmr.taut.py`](ir/shape_swmr.taut.py) — the `swmr` (multi-slot
  reconstructible state) wire vocabulary: a snapshot + contiguous delta window,
  typed resets, writer-checked single-writer producer inputs
  (`TautShapeRoadmap.md` §3). Payload-agnostic; every decision the roadmap
  sketch left open is recorded in
  [`dev-docs/AtomSwmrNotes.md`](dev-docs/AtomSwmrNotes.md).
- `snapshot_delta` deliberately has no second IR: it is the fixed expiry profile
  over `shape_swmr`, specified in
  [`dev-docs/TautShapeSnapshotDeltaDecision.md`](dev-docs/TautShapeSnapshotDeltaDecision.md).
- [`ir/shape_crdt.taut.py`](ir/shape_crdt.taut.py) — causal replicated-operation
  delivery with vector resume and opaque bootstrap. `text_crdt` deliberately has
  no second IR; its operation payload and projection reuse this core as specified
  in [`dev-docs/TautShapeCrdtDecision.md`](dev-docs/TautShapeCrdtDecision.md).
- `ir/shape_<name>.ir.json` — the exported, language-neutral IR. **Generated** —
  do not hand-edit. Each `taut-shape-<lang>` vendors its generated message types
  from these schemas (`tautc gen -l <lang>`).

### Regenerate / gate the IR

Each exported IR must always be a faithful export of its schema. Regenerate all,
or check that the committed copies are in lockstep, with:

```sh
python3 ir/regen.py            # rewrite ir/shape_log.ir.json from the schema
python3 ir/regen.py --check    # exit nonzero if the committed IR is stale (CI gate)
```

`regen.py` bootstraps the taut builder from the sibling `../taut/src`, exactly as
`shape_log.taut.py` does, and writes the same
`json.dumps(schema_json(SCHEMA), indent=2) + "\n"` form as `taut.ir.export`.

## corpus/ and matrix/

- [`corpus/`](corpus/README.md) — the committed behavioral oracles
  (`log.v0.json`, `value.v0.json`, `atom.v1.json`, `stream.v1.json`,
  `swmr.v1.json`, `snapshot_delta.profile.v1.json`, `crdt.v1.json`,
  `crdt.convergence.v1.json`, and `text_crdt.profile.v1.json`) plus the
  authored input scripts they are generated from (`scripts/`, `scripts_value/`,
  `scripts_atom/`, `scripts_stream/`, `scripts_swmr/`,
  `scripts_snapshot_delta/`).
- [`matrix/`](matrix/README.md) — the Python `node(X) ⊗ client(Y)` interop
  driver plus its deterministic `scenarios/`.

See `dev-docs/TautShapeOracle.md` for both in full.

## Release and drift gate

`release/compatibility.v1.json` is the machine-readable contract/package/
consumer table. Run `python3 release/check_compatibility.py` for development
lockstep; tag CI runs the stricter `--release` mode, which rejects development
versions, non-semver consumer pins, and dirty participating repositories. See
`dev-docs/TautShapeReleaseCompatibility.md` for the human-facing table and
release transition.
