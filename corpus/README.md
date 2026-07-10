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

## The fold oracle (glade's M-LIMP folds, re-homed — P2.S1)

Glade's frozen fold oracle (`taut/corpus/glade_folds.json`, generated from
`taut.crdt.glade_fold`) re-homed into taut-shape so taut-shape owns the canonical
fold semantics. This is the pure `(op-set) → folded state` layer *beneath* the
message-level shape corpora: raw attributed ops in, folded state out — no
sessions, streams, reads, timers, or lifecycle.

- `fold.v0.json` — the committed fold oracle (`version "fold.oracle/v0"`), 12
  vectors across three folds: `value` (lww; 6), `log` (causal-order append; 4),
  and `equiv` (forked-chain detection; 2). Raw-op granularity: ops carry
  `origin/seq/lamport/prev/payload` with **hex** payloads (glade's convention —
  the fold works on the raw op envelope, not schema messages, so there is no
  jsoncodec round-trip and no base64, unlike `value.v0.json`).
- `scripts_fold/` — the authored inputs (`{name, fold, ops}`; `gen` fills `expect`).
- `fold_gen.py` — generator + gate. `--check` is BOTH a lockstep gate (committed
  vs fresh gen) AND a **conflict guard** against glade's frozen oracle: it reads
  `taut/corpus/glade_folds.json` (read-only) and fails loud if any glade vector's
  `(ops, expect)` diverges from ours (a semantic conflict is a design event).

  ```sh
  python3 corpus/fold_gen.py            # rewrite corpus/fold.v0.json
  python3 corpus/fold_gen.py --check    # CI gate: stale OR conflicts with glade
  ```

**Dedup — `value`/`equiv` fold rows are already covered by `value.v0.json`.** The
fold oracle and the message-level `value` corpus derive from the *same*
`fold_value` reference at two granularities (raw fold vs full `set`/`read`/
response round-trip). The fold rows are re-homed (not dropped) so deleting
glade's private oracle loses nothing, but they add no new `value` *behavior*
beyond what P1 already gates. Mapping:

| `fold.v0.json` row          | covered by `value.v0.json` vector | note |
|-----------------------------|-----------------------------------|------|
| `value/single`              | `set_then_read`                   | payload `4131` = `b"A1"` (base64 `QTE=`) |
| `value/concurrent-lamport`  | `concurrent_lamport`              | higher lamport wins |
| `value/tiebreak-origin`     | `tiebreak_origin`                 | lamport tie → origin `b`>`a` |
| `value/out-of-order`        | `out_of_order`                    | arrival-order independent |
| `value/duplicate`           | `duplicate_idempotent`            | exact re-sends dropped |
| `value/empty`               | `read_empty`                      | empty set → `empty` |
| `equiv/forked`              | `equivocation_rejected`           | forked-by-payload → `ValueDiagnostic{error,equivocation}` |
| `equiv/clean`               | `duplicate_idempotent`            | clean dup is *not* equivocation |

`value.v0.json` additionally covers `overwrite_same_origin`, `read_reflects_latest`,
`equivocation_prev_mismatch`, and `two_reads_two_streams` — value coverage
*beyond* glade's fold oracle (P1 supersets it).

**New coverage — the `log` fold.** The 4 `log/*` rows are the causal-interleave
fold (`fold_log`, order by `(lamport, origin, seq)`, dedup by `(origin, seq)`).
This is *not* otherwise gated in taut-shape: `log.v0.json` is the `shape_log`
*behavioral* corpus (streaming reads/holds/timers/lifecycle, Rust-generated),
which never exercises the pure fold. P1 built only `value`; these rows bring
glade's log fold in.
