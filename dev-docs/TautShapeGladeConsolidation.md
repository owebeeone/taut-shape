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
