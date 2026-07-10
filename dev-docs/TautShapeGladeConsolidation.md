# TautShapeGladeConsolidation — one home for delivery shapes

Status: working draft — phased plan (approved direction, Gianni 2026-07-05)

Purpose: taut-shape was born from the glade code; consolidate so there is ONE
contract home for delivery shapes and ONE cross-language conformance corpus.
After this plan: **taut-shape owns shapes** (payload-agnostic engines + oracle
corpora + interop matrix), **glade keeps only what is genuinely glade** —
session/frame vocabulary (HELLO/SUBSCRIBE/OPS/HEADS/EXCHANGE/CHANNEL),
routing, destinations, authority, claims. Glade becomes a *consumer* of shape
contracts, as will glial's client runtime (assembly engines) and any future
consumer (razel comms included).

The rule the repo already enforces carries over: *the reference code is
optional; the oracle is mandatory.* Glade's node/client earn their keep by
staying lockstep with the corpus, not by being the corpus.

## Phases

**P1 — `shape_value` (extract glade's lww).**
- S1: author `ir/shape_value.taut.py` — value register vocabulary (whole-value
  set, MV surfacing deferred with the GQ-1 posture), payload-agnostic
  (`payload = BYTES`, the Op.payload pattern).
- S2: vector catalog + committed corpus (`value.v0.json`) generated from the
  reference engine; lockstep gate mirrors log-v0.
- S3: matrix rows: `node(X) ⊗ client(Y)` over value scenarios.
  Exit: value shape conformance runs in CI beside log-v0.

### P1 build notes (S1–S2 landed; S3 blocked)

Delivered: `ir/shape_value.taut.py` + exported `ir/shape_value.ir.json`
(`ir/regen.py` now gates both shapes), the authored input scripts
`corpus/scripts_value/*.json`, the committed oracle `corpus/value.v0.json`
(11 vectors), and its self-contained lockstep gate `corpus/value_gen.py`
(`--check`). Decisions taken (smallest reasonable calls):

- **Reference engine is Python, not Rust.** `shape_log`'s `gen.py` shells to the
  external `taut-shape-tool` (Rust). The `value` fold is small and its canonical
  reference already exists in the taut runtime — `taut.crdt.glade_fold.fold_value`
  (winner = `max (lamport, origin)`; dedup by `(origin, seq)`; forked chain =
  equivocation). `value_gen.py` imports it, so value corpus gen/gate is
  self-contained in the workspace (no per-language build). taut-shape still holds
  no engine of its own — `fold_value` is the authority; the register-shell glue
  is driver code and asserts its winner equals `fold_value(ops)`.
- **Wire vocabulary (v0):** `ValueSet` (a whole-value write — the fold-relevant
  subset of the glade `Op` envelope: origin/seq/lamport/prev?/payload; glade owns
  share/glade_id/key routing), `ValueReadRequest{value_id, stream_id}` →
  `ValueReadResponse{value_id, stream_id, value?, winner?, state}`, and
  `ValueDiagnostic{severity, code}`. `ValueStamp{origin, seq, lamport}` is the
  winner provenance.
- **Reads are immediate probes** — no held reads, no timers, no lifecycle
  (seal/close/evict). Those are `shape_log` / later shapes; whole-value v0 does
  not need them. `end_stream` is omitted for the same reason (a probe leaves no
  per-stream state to clean up) — a v-next addition if the matrix needs it.
- **MV deferred (GQ-1 sidestep, GladeSubstrateV1 §11):** single-winner only;
  `ValueReadResponse.winner` is one stamp. MV grows additively (a repeated field)
  and forecloses nothing.
- **Equivocation** is a `ValueDiagnostic{error, equivocation}` on the offending
  write (rejected, register unchanged) — not a read outcome. `error` (not log's
  `warn`) because a forked chain is a rejected op, not a benign late-write race.
- **Format delta from log-v0:** value vectors carry no `node` construction knob
  (value has no `stop_when`); otherwise `corpus/value.v0.json` matches Oracle §3.

**S3 (interop matrix) — BLOCKED, not started.** The matrix needs a `value`
`node`/`client` CLI in each `taut-shape-<lang>`; none of `taut-shape-rs|ts|py`
are cloned in this workspace (and `matrix/driver.py` is log-specific — it
hardcodes the log tools and canonicalises log transcripts). Value matrix rows
land when those sibling repos gain a value engine. The corpus + Python-reference
gate already give cross-language conformance-against-spec; the matrix adds
live A-vs-B, which requires the language tools to exist.

**P2 — glade rebases onto the contracts.**
- S1: glade's fold-conformance vectors (lww + log byte-parity oracles from
  M-LIMP) MERGE into the taut-shape corpora — one corpus per shape, glade's
  Rust/TS engines become matrix participants rather than oracle owners.
- S2: `glade.taut.py` sheds shape vocabulary; imports/aligns with
  `shape_log`/`shape_value` IR; keeps op envelope (GQ-9) + frame vocabulary.
- S3: glade node/client swap internal fold implementations to the taut-shape
  engine seam (or prove byte-parity against it and keep their own — engine
  identity is free, conformance is not).
  Exit: deleting glade's private oracle dir loses nothing; matrix covers
  glade engines.

### P2.S1 build notes (fold oracle merged 2026-07-10)

Delivered the merge (S1). glade's frozen M-LIMP fold oracle
(`taut/corpus/glade_folds.json`, 12 vectors, generated from
`taut.crdt.glade_fold`) is re-homed into taut-shape as `corpus/fold.v0.json`
(`version "fold.oracle/v0"`) following the established scripts/gen/`--check`
pattern: `corpus/scripts_fold/*.json` (authored raw-op inputs) → `corpus/fold_gen.py`
(imports the taut fold reference, fills `expect`, self-contained — no per-language
build, mirroring `value_gen.py`). Smallest reasonable calls taken:

- **Re-homed whole, not shredded per shape.** glade's oracle is inherently one
  artifact spanning three folds (`value`/`log`/`equiv`); it lands as one
  taut-shape corpus (`fold.v0.json`), *not* split into `value.v0`/`log.v0`. This
  keeps byte-parity with glade's frozen file trivial (so the conflict guard is a
  simple by-name `(ops, expect)` compare) and preserves the "the fold is one
  contract" framing. A minor deviation from the plan's "one corpus per shape" —
  recorded here. The message-level per-shape corpora (`value.v0`, `log.v0`) stay
  the per-shape homes; `fold.v0` is the shared fold-primitive layer beneath them.
- **Raw-op / hex granularity, no jsoncodec.** The fold operates on the raw op
  envelope (`origin/seq/lamport/prev/payload`), not schema messages, so — unlike
  `value_gen.py` — there is no jsoncodec/CBOR round-trip and payloads ride **hex**
  (glade's convention), matching `glade_folds.json` exactly.
- **`value` + `equiv` rows deduped against P1's `value.v0.json`** (`corpus/README.md`
  mapping table): the fold rows and the message-level `value` corpus derive from
  the *same* `fold_value` reference at two granularities, so the fold rows add no
  new `value` *behavior* — they are re-homed (so deleting glade's oracle loses
  nothing) with the overlap documented. `value.v0.json` already supersets glade's
  value+equiv coverage (`overwrite_same_origin`, `read_reflects_latest`,
  `equivocation_prev_mismatch`, `two_reads_two_streams` are beyond the fold oracle).
- **The 4 `log/*` rows are genuinely new coverage.** taut-shape's `log.v0.json`
  is the `shape_log` *behavioral* corpus (streaming/holds/timers/lifecycle,
  Rust-generated) and never exercises the pure causal-interleave fold `fold_log`.
  P1 built only `value`; the log fold enters taut-shape here.
- **Conflict guard is the "gate" half of the brief.** `fold_gen.py --check`
  doubles as a design-event tripwire: it reads glade's frozen `glade_folds.json`
  (read-only) and fails loud if any glade vector's `(ops, expect)` diverges from
  ours. Result on this merge: **no conflict** — every glade fold row agrees.

**No IR / `regen.py` change.** The fold consumes raw ops, not a taut schema
message, so there is no new `shape_*.taut.py` / `.ir.json` and no `regen.py` row.

**P2.S2/S3 (glade rebases its schema + swaps engines onto the seam) — not done
here; out of scope** (this task is the taut-shape-side merge only; those edit
`glade/`, which was read-only). Exit condition (delete glade's private oracle,
lose nothing) is now *reachable*: glade's `client-ts/test/oracle.test.ts` can
repoint from `taut/corpus/glade_folds.json` to `taut-shape/corpus/fold.v0.json`
(the same 12 vectors, now taut-shape-owned + conflict-gated), a one-line glade
change left for glade's P2.S3.

### Value interop-matrix (P1.S3) — assessment 2026-07-10 (repos now present, still deferred)

P1.S3 was BLOCKED on the sibling repos being absent. They are now workspace
members — so the blocker is *partly* lifted — but a value×(rs,ts) matrix is still
not a ~500 LOC build; it stays deferred, with the shape estimated here.

**What exists.** Both `taut-shape-rs` and `taut-shape-ts` are strictly
**single-shape (`log` only)**:
- `taut-shape-rs`: `generated.rs` is `shape_log` codegen only (`LogMsgType`,
  `Log*` structs — no `Value*` types); the engine is `LogNode`
  (`crates/taut-shape/src/log/*`); the CLI (`main.rs` mode dispatch, `node.rs`,
  `client.rs`, `framing.rs`) is log-typed throughout.
- `taut-shape-ts`: `src/taut/gen/` holds only `shape_log.ir.json` + `shape_log.ts`
  (`LogMsgType` only); engine `LogNode` (`src/log/*`); `cli.ts` hardwires
  `node`→`LogNode` / `client`→the log cursor loop.
- `matrix/driver.py` is log-specific: `LogReadRequest`/`Response`, `--stream-id`/
  `--from`, *held* reads released by a producer `--script` after the k-th frame,
  and a 3-dialect **log** transcript canonicaliser + log scenarios/goldens.

**What's missing (per language), to run value×(rs,ts) live:**
1. Codegen the value vocabulary: `tautc gen ir/shape_value.ir.json` → `Value*`
   types + CBOR (rs `generated_value.rs`; ts `shape_value.ts`), wired into each
   crate/package (both are currently single-shape, so this is new module + tag-map
   plumbing, not a drop-in).
2. A value engine mirroring `value_gen.py`'s `Register` (accumulate `ValueSet`,
   answer `ValueReadRequest` by folding — winner = max `(lamport, origin)`, dedup
   `(origin, seq)`, equivocation → `ValueDiagnostic`): rs `value/node.rs` ~120,
   ts `value/node.ts` ~110.
3. A value CLI mode (`node`/`client` for value) + value framing tag-map: ~80–120
   LOC each (the current `node`/`client` modes are log-hardwired).
4. A value matrix driver + scenarios/goldens. Value reads are **immediate probes**
   (no held reads, no timers, no lifecycle), so the driver's release-after-k
   coordination model does *not* transfer — a value scenario is "client sets N
   writes, then probes"; needs a new/generalized driver (~150) + scenarios.

**Estimate & verdict.** ~250–350 LOC (rs) + ~230–330 (ts) + ~180–250 (driver +
scenarios) ≈ **700–900 LOC across three repos**, plus codegen wiring into two
engines that are architecturally single-shape today. That exceeds the ~500 LOC
step budget and is invasive (each CLI/framing assumes one shape). **Verdict: not
a minimal S3 — deferred.** The `fold.v0.json` + `value.v0.json` Python-reference
gates already give cross-language conformance-*against-spec*; the matrix's extra
value (live A-vs-B) waits on the value engines above. Natural first move when
picked up: generalize `main.rs`/`cli.ts` mode dispatch + `framing` over a shape
parameter, then add the value engine behind it — smaller if the two engine repos
are de-log-hardwired first (a shared step across all future shapes).

**P3 — `shape_window`.**
- Window semantics from the s-window trace: windowed projection over a log,
  interactive-priority first paint, backfill separately; window params are
  canonical key material. Contract + corpus + matrix before any glade/glial
  code consumes it.

**P4 — `shape_text_crdt`.**
- The editor shape: ops with **stable position identity** (cursor anchors to
  element ids — the requirement that makes multi-line fields survive remote
  edits without rewrites). Contract-first, corpus of concurrent-edit vectors,
  merge determinism gate. Feeds the GlialClientRuntime editor binding.

**P5 — the glial event envelope as a shape artifact.**
- The rich change-event schema (`refresh`/`delta`/`baseSeq` — see
  `GlialClientRuntime.md`) is versioned WITH the shapes that produce it
  (GC-1): each shape's contract states what its delta form is; the corpus
  gains event-emission vectors so glial assembly is conformance-tested too.

## Ordering constraints

P1 and P2.S1 can run in parallel; P2.S2/S3 need P1. P3/P4 are independent of
each other, both after P2 (they extend the corpus pattern, not glade). P5
trails the first shape that emits deltas (log suffices to start).

## Non-goals

No razel changes (razel already consumes taut wire directly); no glade wire
redesign (frames stay); no engine rewrites forced — parity gates decide what
survives.
