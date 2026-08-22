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
  13 vectors: lww basics (single/concurrent-lamport/tiebreak-origin/out-of-order/
  overwrite), deterministic same-origin clock-reuse tiebreaks, idempotent
  duplicates, a live read-reflects-latest sequence,
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

## The `atom` shape (replace-only latest state)

- `atom.v1.json` — the committed `atom` oracle (`version "atom.oracle/v1"`),
  28 vectors: initial delivery, replacement (overwrite, no back-history),
  generation-change replace (a consumer-level concept — taut-shape sees an
  ordinary replace, see `dev-docs/AtomSwmrNotes.md` #4), subscriber-join-mid-
  stream (a fresh stream gets the LATEST value, never back-history), held
  reads/timers/supersede, seal/close/idempotent-teardown, terminal-still-
  readable (no floor, so this always holds), multi-stream addressing and
  one-replace-wakes-two, `ProducerStop` on last-reader-gone (plus a never-read
  no-stop variant and a post-close double-`ProducerStop` pin), replace-after-
  terminal diagnostics, a beyond-current version clamp (immediate probe and
  timed-expiry variants), and timed early-wake `CancelTimer`-ordering pins
  (replace/seal/close). `atom` is a strict simplification of `log` —
  window=1, no floor/expiry/max_records/max_bytes (`TautShapeRoadmap.md` §1).
  Bumped `v0`→`v1` (2026-07-19, PH0 review remediation): `AtomTimerExpired`
  now normalizes `next_version` through the canonical resolver instead of
  echoing the originally requested version (fixes review 56-F2), and a
  timer-backed held read released for any reason other than `TimerExpired`
  now cancels its timer first (fixes review 56-F4).
- `scripts_atom/` — the authored inputs.
- `atom_gen.py` — the generator + lockstep gate (`--check`). This driver embeds
  its own small, hand-written reference
  mailbox engine (`AtomNode`, held reads + timers + lifecycle included, since
  `atom` is not a pure fold). See `dev-docs/AtomSwmrNotes.md` #13.

  ```sh
  python3 corpus/atom_gen.py            # rewrite corpus/atom.v1.json
  python3 corpus/atom_gen.py --check    # CI gate: nonzero if committed is stale
  ```

## The `stream` shape (bounded disposable ordered delivery)

- `stream.v1.json` — 28 vectors for the policy frozen in
  `dev-docs/TautShapeStreamDecision.md`: live-only late join, bounded batches,
  byte-bound forward progress, slow-reader drop, independent fast/slow readers,
  reconnect-as-late-join, multi-reader held wake-up, timers/supersession,
  terminal drain, clean/failed close, teardown, and diagnostics.
- `scripts_stream/` — authored inputs and `capacity_records`/`stop_when` node
  knobs.
- `stream_gen.py` — the self-contained reference engine and lockstep gate.

  ```sh
  python3 corpus/stream_gen.py
  python3 corpus/stream_gen.py --check
  ```

## The `swmr` shape (snapshot + delta + typed reset)

- `swmr.v1.json` — the committed `swmr` oracle (`version "swmr.oracle/v1"`),
  33 vectors: initial snapshot, delta batches, resume from a retained seq
  (success, no dup/no skip), resume from an expired seq (typed
  `state=reset, reason=retention_exceeded`, engine-repaired in-band with a
  fresh snapshot — not client-decided like `log`'s `expired`), a producer-
  declared generation-change reset (`reason=producer_requested`), two readers
  at different cursors, a backpressure/retention-bound vector
  (`max_deltas` construction knob rejects a delta past the bound), a
  writer-uniqueness-violation vector (a second `writer_id` is rejected,
  `SwmrDiagnostic{error, writer_conflict}`), plus the full `log`/`atom`-parity
  lifecycle set (held reads/timers/supersede/seal/close/idempotent-teardown/
  end_stream/`ProducerStop`/push-after-terminal/delta-before-snapshot/
  terminal-still-readable), a never-read no-stop variant, a post-close
  double-`ProducerStop` pin, an `invalid_resume_seq` reset vector, a
  pre-snapshot timed request with a supplied (unusable) cursor, an
  absent-cursor hold surviving a producer reset untouched, a caught-up reader
  surviving a compaction/re-basing push with no spurious reset, timed
  early-wake `CancelTimer`-ordering pins (delta/seal/close/reset), and a
  durable-reset regression where an old `(epoch, seq)` cursor cannot miss a
  reset while between polls even when the new epoch reuses the same sequence.
  Reset responses also surface the producer's opaque `detail`. Every
  decision the `TautShapeRoadmap.md` §3 sketch left open (including the two
  new mechanisms — `writer_id` enforcement and the `max_deltas` bound — that
  go beyond the sketch) is recorded in `dev-docs/AtomSwmrNotes.md`. Bumped
  `v0`→`v1` (2026-07-19, PH0 review remediation): a `SwmrSnapshotPush` now
  resumes at the pre-push base rather than consuming a delivery-sequence slot
  (so a caught-up reader survives a compaction push, PH0-D20/D24); every
  response path (including `SwmrTimerExpired` and `SwmrReset`) now computes
  `next_cursor` through the canonical resolver — present iff a snapshot
  exists, never a caller-echoed or hardcoded position (fixes reviews 56-F2
  and F5-03); an absent-cursor held read is never force-answered `reset` by a
  producer reset (fixes review F5-02); `SwmrReset.reason` is normalized to
  `producer_requested` (fixes review F5-13); and a timer-backed held read
  released for any reason other than `TimerExpired` now cancels its timer
  first (fixes review 56-F4). The v1 draft now uses `(epoch, seq)` cursors;
  successful producer reset increments the epoch and retains reason/detail so
  stale cursors remain detectable after the immediate reset step.
- `scripts_swmr/` — the authored inputs.
- `swmr_gen.py` — the generator + lockstep gate (`--check`), same
  self-contained-reference-engine strategy as `atom_gen.py` (`SwmrNode`: a
  snapshot+delta store core, held reads, timers, writer-checked producer
  inputs).

  ```sh
  python3 corpus/swmr_gen.py            # rewrite corpus/swmr.v1.json
  python3 corpus/swmr_gen.py --check    # CI gate: nonzero if committed is stale
  ```

## CRDT delivery and text specialization

- `crdt.v1.json` contains 15 exact mailbox vectors for vector reads, causal
  buffering, deduplication, deterministic equivocation, bootstrap, resume, and
  lifecycle.
- `crdt.convergence.v1.json` contains five N-replica delivery-permutation
  scenarios. Every implementation must produce an identical clock, canonical
  op set, and diagnostic set for every replica order.
- `text_crdt.profile.v1.json` contains five text projections over the same core,
  including concurrent siblings, delete-before-insert, bootstrap, and stable
  text diagnostics.
- `crdt_gen.py` and `crdt_convergence_gen.py` regenerate/check these artifacts;
  authored inputs live in `scripts_crdt*` and `scripts_text_crdt`.

The normative boundary is `../dev-docs/TautShapeCrdtDecision.md`.

## The fold oracle (glade's M-LIMP folds, re-homed — P2.S1)

Glade's frozen fold oracle (`taut/corpus/glade_folds.json`, generated from
`taut.crdt.glade_fold`) re-homed into taut-shape so taut-shape owns the canonical
fold semantics. This is the pure `(op-set) → folded state` layer *beneath* the
message-level shape corpora: raw attributed ops in, folded state out — no
sessions, streams, reads, timers, or lifecycle.

- `fold.v0.json` — the committed fold oracle (`version "fold.oracle/v0"`), 13
  vectors across three folds: `value` (lww; 7), `log` (causal-order append; 4),
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
| `value/tiebreak-seq`        | `tiebreak_seq`                    | same origin/lamport → higher seq |
| `value/out-of-order`        | `out_of_order`                    | arrival-order independent |
| `value/duplicate`           | `duplicate_idempotent`            | exact re-sends dropped |
| `value/empty`               | `read_empty`                      | empty set → `empty` |
| `equiv/forked`              | `equivocation_rejected`           | forked-by-payload → `ValueDiagnostic{error,equivocation}` |
| `equiv/clean`               | `duplicate_idempotent`            | clean dup is *not* equivocation |

`value.v0.json` additionally covers `overwrite_same_origin`, `read_reflects_latest`,
`tiebreak_seq_out_of_order`, `equivocation_prev_mismatch`, and
`two_reads_two_streams` — value coverage
*beyond* glade's fold oracle (P1 supersets it).

**New coverage — the `log` fold.** The 4 `log/*` rows are the causal-interleave
fold (`fold_log`, order by `(lamport, origin, seq)`, dedup by `(origin, seq)`).
This is *not* otherwise gated in taut-shape: `log.v0.json` is the `shape_log`
*behavioral* corpus (streaming reads/holds/timers/lifecycle, Rust-generated),
which never exercises the pure fold. P1 built only `value`; these rows bring
glade's log fold in.
