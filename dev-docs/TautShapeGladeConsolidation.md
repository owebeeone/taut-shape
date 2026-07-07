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
