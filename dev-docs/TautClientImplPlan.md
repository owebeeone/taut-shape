# Taut Client Implementation Plan (shared)

Status: plan (v2 — mailbox engine model). Scope: phased plan, language-neutral.
Audience: every `taut-shape-<lang>` implementation.

Relationship: each `taut-shape-<lang>/dev-docs/InitialPlan.md` **references this
document** and resolves every `«SPECIALIZE: …»` marker with a concrete,
language-specific commitment. This document defines *what* every client must
implement and the conformance it must pass; it holds no language detail.

See also: [`TautShapeArchitecture.md`](TautShapeArchitecture.md) (design),
[`TautShapeOracle.md`](TautShapeOracle.md) (the behavioral contract), and each
`taut-shape-<lang>/dev-docs/InitialPlan.md`.

Guiding constraint: **getting the API right beats speed.** §2–§4 are the
load-bearing decisions; they are pinned as D-numbers (§4) so the language repos
can cite them.

v2 note: this revision replaces the v1 "sync core + callback store seam +
readiness hook" model with a **pure message-queue engine** (see D1). The v1
per-language drafts predate this; they are reconciled against v2.

---

## 1. Goal

A reusable, per-language implementation of Taut delivery shapes (`log` first).
Each `taut-shape-<lang>` is an independent, idiomatic, publishable library
implementing **one shared contract**, kept honest by the behavioral oracle
(golden message vectors) and the interop matrix (live, over pipes). No client is
forced to use the reference code — but any client that reimplements must still
pass the oracle.

The engine is a **pure protocol endpoint**: droppable behind a network protocol
adapter (frames in/out) or called directly in-process (gwz today). An in-memory
consumer exercises the *same message API* a remote client would — detaching to a
network deployment is a transport swap, not an API migration.

## 2. The engine model (normative)

### 2.1 Shape: a mailbox endpoint (D1)

One **`LogNode`** engine instance per log. Canonical semantic form:

```
handle(input: InMsg) -> [OutMsg]     # or an equivalent send()/poll() pair
```

- **Pure**: no I/O, no clock, no executor, no internal locks. Outputs are a
  deterministic function of the input history (D16).
- The engine **manages the whole protocol state**, including held long-polls:
  a tail `Read` that cannot be answered yet is parked inside the engine and
  answered when a later input (`Push`/`Seal`/`Close`/`TimerExpired`/`EndStream`)
  releases it. There is **no readiness/notify callback seam** — readiness
  dissolved into message ordering.
- Timers are messages (D14): the engine emits `SetTimer`/`CancelTimer` and the
  shell feeds back `TimerExpired`. The engine never reads a clock.
- Single-threaded by construction; the **shell owns serialization** (D15) — a
  lock (or single loop) around `handle`.
- Read-only accessors (`head`, `floor`, `min_watermark`, `stream_count`) are
  permitted conveniences for in-process shells: never mutating, never part of
  the wire contract. «SPECIALIZE: engine type + concrete handle signature»

### 2.2 Internal split: store core + session table (D2, D3)

```
┌────────────────────────── LogNode (one per log) ──────────────────────────┐
│  Store core (one)                Session table (one entry per stream)     │
│  records window, head, floor,    held Read, timer token, watermark        │
│  sealed/closed/failed            (the per-stream "response handler")      │
│  — no stream concepts            — no byte/retention concepts             │
└───────────────────────────────────────────────────────────────────────────┘
```

Many stream instances read one backing at different positions (backed-up
readers). The split is the shape-generic architecture — but precisely: what
generalizes is the **boundary** (a store core with no stream concepts; a
session table with no byte/retention concepts), not shared core code. For
`crdt`/`swmr` the session entry grows richer (per-peer sync state) **and the
store core is a different machine per shape** (append-window here;
snapshot+delta+compaction for swmr; merge/fold for crdt) — same role, per-shape
implementation. See `TautShapeRoadmap.md` (the multi-shape stress test).

v0 keeps the record window **inside** the engine (D2); the external-store
extension is §9.

### 2.3 Identity model (D3, D4, D5)

| Concept | What | Owner |
|---|---|---|
| client / connection | a process, tab, socket | **adapter only** — routing; the engine never sees it |
| **stream instance** (`stream_id`) | one logical read loop, own position | the engine's session unit; many per client |
| request | one `Read` within a stream | ≤1 outstanding per stream ⇒ `stream_id` is the correlation |

Stream instances are **disposable**: position lives in the client-held cursor
(reads are cursor-in/cursor-out), so a lost stream loses only its held poll —
reconnect with a fresh `stream_id` and the old cursor.

## 3. The message vocabulary (`log`, v0) — normative

The vocabulary is **declared in taut and generated, not hand-written** (D17): a
self-contained, payload-agnostic schema (`taut-shape/ir/shape_log.taut.py`)
defines every message below — messages + codecs, no `service`, exactly the
glade wire-schema pattern. Each `taut-shape-<lang>` vendors its generated types
in Phase 0. Hand-written per language: only the In/Out unions, the engine, and
the shell.

### 3.1 Types

- `Cursor { seq }` — "records strictly after `seq` are unseen". Named type so it
  can grow (`byte_offset` reserved). `START = {seq: 0}` (D8).
- `Record { seq, payload: BYTES }` — payload opaque, NUL-safe (D11). The
  payload is the method's append-slot message, **already taut-encoded** (the
  glade `Op.payload` pattern) — the log vocabulary stays generic without
  generics (D17).
- `State ∈ { data, would_block, eof, closed, failed, expired }` (D12, D13).
- `Error { code ∈ {unknown_log, producer_error, internal}, message? }` —
  `unknown_log` is **service-level** (log_id routing, §3.5); the node engine
  itself only ever attaches `producer_error`/`internal` to `failed` responses.
  (There is no `canceled` error: client-initiated cancellation is `EndStream`,
  which needs no response.)

### 3.2 Inputs

Producer-side (node-local, unaddressed):
- `Push { payload }` — assign `seq := head+1` (first record `seq = 1`, D8),
  append to the window, answer any held reads. A `Push` arriving after
  `Seal`/`Close` is **dropped** (nothing appended, head unchanged) and emits
  `LogDiagnostic{warn, push_after_terminal}` (D18/D19): a late in-flight push
  is an expected race with `ProducerStop`, made visible, never silent or fatal.
- `Seal {}` — finite log complete; held reads answered `eof`. Idempotent.
- `Close { error? }` — teardown. Held reads answered `closed` (no error) or
  `failed` (error attached, D12); their timers canceled; `ProducerStop` emitted
  on the transition into the terminal state. Idempotent including outputs: a
  `Close` on an already-terminal log emits nothing (D6).

Stream-side (addressed):
- `Read { stream_id, cursor?, max_records?, max_bytes?, timeout_ms? }` —
  absent `cursor` ⇒ `START` (D8). First use of a `stream_id` implicitly creates
  the session entry (D4). A `Read` on a stream with a held read **supersedes**
  it: the old one is dropped without a response and its timer canceled (D5).
- `EndStream { stream_id }` — drop held read (no response), cancel its timer,
  remove watermark, decrement reader count (D4). Unknown `stream_id` = no-op.
  Adapters inject this on transport death — it *is* the disconnect cleanup.

Environment:
- `TimerExpired { token }` — if the token maps to a held read, answer it
  `would_block`; otherwise ignore (late/canceled timers are no-ops).
- `Evict { up_to_seq }` — drop records with `seq ≤ up_to_seq`, raising the
  floor (retention is consumer-driven in v0, D7). `up_to_seq` is clamped to
  `head`, so `floor ≤ head + 1` always holds (D20) — evicting past head cannot
  manufacture positions that never existed.

### 3.3 Outputs

- `Response { stream_id, records[], next_cursor, state, error? }` —
  `next_cursor` ALWAYS present.
- `SetTimer { token, ms }` / `CancelTimer { token }` — tokens allocated
  monotonically from 1 (D16).
- `Diagnostic { severity, code }` — engine warnings delegated to the caller: a
  sans-io engine cannot log, so the shell routes these to the host's logging
  facility. **Code only, no free text** — prose would freeze byte-identical
  strings into the cross-language oracle; shells localize (D18).
- `ProducerStop { reason ∈ {last_reader_gone, closed, failed} }` — emitted on
  `Close`, and on the reader-count **≥1 → 0 transition** when the node was
  constructed with `stop_when = last_reader` (D6). A log never read does not
  spuriously stop its producer. The shell routes this to the producer (gwz:
  across its bridge; glade: to the render task); shells that initiated the
  close ignore it (it is idempotent by design).

### 3.4 Read resolution (each rule oracle-pinned)

For `Read{stream_id, cursor C, limits, timeout_ms}`:

1. **Data available** (`C.seq < head`, records retained): return `data` with up
   to `max_records`/`max_bytes` records; `max_bytes` counts **raw payload bytes
   only**; **forward progress**: if any record is available, return at least
   one even if it alone exceeds `max_bytes` (D10). `next_cursor` = seq of the
   last returned record.
2. **Caught up** (`C.seq == head`): if sealed → `eof`; if closed/failed →
   `closed`/`failed` (+error); else it depends on `timeout_ms` (D14):
   `0` → immediate `would_block` (non-tail probe); absent → **hold
   indefinitely** (until data/seal/close/EndStream); `> 0` → hold + emit
   `SetTimer`; on expiry answer `would_block`. `next_cursor` = `C`.
3. **Invalid cursor** → `expired` with `next_cursor` = the earliest resumable
   position (D9): `C.seq + 1 < floor` → `next_cursor = {floor − 1}` (records
   were evicted); `C.seq > head` → `next_cursor = {head}` (position never
   existed). The client decides whether to continue lossy from there.
4. Terminal states (`eof`/`closed`/`failed`) remain re-readable: a later `Read`
   below head still returns `data` until the window is evicted — terminal
   describes the *log*, not the stream.

When one input releases several held reads (e.g. `Push` waking two streams),
responses are emitted **in stream-creation order** (D16).

### 3.5 The service layer (multi-log)

A thin, per-language `LogService` routes wire messages by `log_id` to `LogNode`
instances, mints `log_id`s, and answers unknown ids with `unknown_log`. The taut
companion messages (the wire schema in `taut`) are the *service-level*
vocabulary — node messages plus `log_id`. Producer-side inputs are node-local
in v0 (the producer lives with the node). «SPECIALIZE: service form»

## 4. Pinned decisions (cite by number)

| # | Decision |
|---|---|
| D1 | Engine = pure mailbox endpoint; holds long-polls as state; no callbacks; no clock; timers as messages |
| D2 | v0 bytes live in an engine-internal bounded window + `Evict` input; external store is the §9 extension |
| D3 | Identity = client (adapter-only) / stream instance (engine) / request; responses addressed by `stream_id` |
| D4 | Streams: implicit create on first `Read`; explicit `EndStream` (adapter injects on transport death) |
| D5 | ≤1 outstanding `Read` per stream; a new `Read` supersedes (held read dropped unanswered, timer canceled) |
| D6 | `ProducerStop`: construction knob `stop_when ∈ {last_reader, explicit_only}`; fires on the ≥1→0 reader transition and on the **transition into** a terminal state via `Close`. A repeated `Close` on an already-terminal log emits nothing — outputs-idempotent, symmetric with `Seal` |
| D7 | Retention consumer-driven in v0 (`Evict`); engine tracks per-stream watermarks, exposes min via accessor |
| D8 | First record `seq = 1`; `START = {seq: 0}`; absent cursor ⇒ START; empty log `head = 0` |
| D9 | `expired` is a **state**, never an error; response carries earliest-resumable `next_cursor`; beyond-head cursors are also `expired` |
| D10 | `max_bytes` counts raw payload bytes only; forward-progress guarantee (≥1 record when any available) |
| D11 | `Record` carries its `seq` |
| D12 | Terminal split: `Close{}` → `closed`; `Close{error}` → `failed` (+error on responses); `eof` = sealed-and-drained |
| D13 | Canonical state strings: `data, would_block, eof, closed, failed, expired` |
| D14 | `timeout_ms`: absent = hold indefinitely; `0` = probe (`would_block`); `>0` = hold + timer. No clock in the engine |
| D15 | Engine is unsynchronized; the shell owns serialization (lock/loop around `handle`) |
| D16 | Determinism: timer tokens monotonic from 1; multi-response emission in stream-creation order |
| D17 | Message types are **taut-generated** from a self-contained, payload-agnostic schema (`taut-shape/ir/shape_log.taut.py`; messages + codecs, no service). `LogRecord.payload = BYTES` carries the method's append-type message already taut-encoded (glade `Op.payload` pattern). Hand-written per language: only In/Out unions, engine, shell. Corpus JSON = taut jsoncodec form |
| D18 | Diagnostics are an output message — `LogDiagnostic{severity, code}`, routed by the shell to host logging (the engine cannot log). Code-only, no free text, so the behavioral oracle stays byte-stable across languages |
| D19 | `Push` after `Seal`/`Close` (any terminal state) is dropped — nothing appended, head unchanged — and emits `LogDiagnostic{warn, push_after_terminal}`. Never silent, never fatal |
| D20 | `Evict{up_to_seq}` clamps to `head`: `floor ≤ head + 1` invariant. Discovered as a clean-room divergence (an unpinned behavior); pinned so `expired` resume cursors can never point past real positions |
| D21 | Per-shape message registries: each shape is a self-contained sibling schema (`shape_<name>.taut.py`, own `<Shape>MsgType` registry). No shared/base message schema across shapes |
| D22 | Naming: `<Shape>*` message prefix per schema (`Log*`, `Atom*`, …); per-shape corpus file `<name>.v0.json`, version `<name>.oracle/v0` |
| D23 | Engines namespace per shape (a `log/` module) in every language **before shape 2 lands** — py already complies; rs/ts owe the move |

## 5. Conformance obligations (shared)

Every client MUST:
1. **Reproduce the behavioral oracle** — vectors are pure
   `(input message sequence) → (expected output message sequence)` pairs; the
   whole observed output is compared (golden), never per-field assertions.
   Format + catalog: `TautShapeOracle.md`.
2. **Ship the conformance/interop CLI tool** with modes:
   - `gen` — emit oracle vectors (reference implementation only),
   - `check` — replay the committed oracle through the engine, report pass/fail,
   - `node` — run a `LogNode`+service behind stdin/stdout framing,
   - `client` — run the reading side (the cursor loop) against a node.
   Data channel = **length-prefixed CBOR** taut companion messages (the real
   wire, under test); control/result channel = **OOB JSONL** (scenario in,
   observed transcript out). Follows taut's existing `test_kotlin.py`
   convention (a Python driver spawns the tool, asserts on structured output).
   The interop matrix runs `node(X) ⊗ client(Y)` for all language pairs.
3. **Golden/snapshot as the house style** — the oracle JSON is the primary
   golden; a snapshot tool covers derived surfaces (CLI transcripts, error
   rendering). «SPECIALIZE: golden framework»

## 6. Phases (milestones)

Foundational-first; steps parallel-friendly, budgeted to an aspirational
< 500 LOC. Each `InitialPlan.md` uses these **same phase names**.

**Phase 0 — Scaffold & contract intake**
- S0.1 Repo skeleton: manifest, `README.md`, `docs/api/`, `docs/examples/`,
  license. «SPECIALIZE: manifest»
- S0.2 Test runner + golden framework + CI. «SPECIALIZE: runner, golden»
- S0.3 Pin the oracle + tool protocol from `taut-shape`; generate/vendor the
  `shape_log` message types via `tautc gen` (D17) and the CBOR codec source.
  «SPECIALIZE: cbor source, generated-types vendoring»

**Phase 1 — The engine (foundational; the API to get right)**
- S1.1 Message + core types (§3.1–§3.3) rendered idiomatically. «SPECIALIZE»
- S1.2 Store core: the bounded window (`Push` append, scan, `head`/`floor`,
  `Evict`).
- S1.3 Session table + read resolution (§3.4): held reads, supersede,
  `EndStream`, watermarks, reader-count/`ProducerStop`.
- S1.4 Lifecycle + timers: `Seal`/`Close`(+error), `SetTimer`/`CancelTimer`/
  `TimerExpired`, determinism rules (D16).
  Source: «SPECIALIZE: mirror glade source / clean-room».

**Phase 2 — Golden conformance**
- S2.1 Oracle-vector loader.
- S2.2 Replay vectors through the engine; whole-output golden. «SPECIALIZE»
- S2.3 Lockstep gate (committed corpus vs pinned version).

**Phase 3 — Shell & idiomatic stream surface**
- S3.1 The pump: serialize `handle`, dispatch addressed outputs, run timers.
  «SPECIALIZE: loop/lock form»
- S3.2 Idiomatic streaming sugar over the pump (`Stream` / `AsyncIterable` /
  async generator): issue `Read` (no timeout) → await addressed `Response` →
  yield → repeat; cancellation ⇒ `EndStream`. «SPECIALIZE: async idiom»

**Phase 4 — Conformance / interop CLI tool**
- S4.1 Framing: length-prefixed CBOR data channel; OOB JSONL control channel.
- S4.2 Modes: `gen` / `check` / `node` / `client`. The tool is little more than
  the engine + framing — by design.

**Phase 5 — Interop matrix participation**
- S5.1 Pass `node(X) ⊗ client(Y)` pairings driven by `taut-shape`'s matrix.

**Phase 6 — `stream` shape (deferred)** — after `log` lands across languages.

## 7. Specialization checklist (every InitialPlan.md MUST resolve)

| Marker | What the language doc commits |
|---|---|
| Package manifest | build/packaging manifest |
| Build/test runner | the test command |
| Golden framework | snapshot/golden tool |
| Engine rendering | engine type, `handle` signature, message-type idiom (enums/unions/dataclasses) |
| Shell & async idiom | the pump (lock/loop) + streaming sugar + cancellation mapping |
| Service form | the `log_id`-routing layer |
| CBOR codec | which taut CBOR runtime is reused |
| Generated message types | how the `tautc gen` output of `shape_log.taut.py` is vendored/imported (D17) |
| Source to mirror | glade source to extract, or clean-room |
| Distribution | published package name + registry |
| docs/ layout | `docs/api/` specs + `docs/examples/` worked examples |

## 8. Repository structure (nominated; each language confirms)

- `README.md`, package manifest «SPECIALIZE», `LICENSE`
- `src/` — messages/types, store core, session/engine, shell + stream sugar,
  service, CLI tool + framing
- `docs/api/` + `docs/examples/`
- `tests/` — oracle golden + engine unit + tool e2e
- `dev-docs/InitialPlan.md`

## 9. Extension (designed, not v0): external store

For disk/cache-backed logs whose bytes should not sit in the engine window, the
engine gains a message pair — it emits `ScanRequest{from, limits}` and the shell
answers `ScanResult{records}` whenever its store (disk, network, cache) can.
Reads pend on scans exactly as they pend on data. Purely **additive** (new
messages, opt-in at construction); nothing in the v0 vocabulary changes. Not
built until a real consumer needs it.

## 10. Non-goals / out of scope

- Production transport/framing (the consumer's concern; gwz's bridge owns the
  PyO3 / cross-runtime work — the engine never sees it).
- `swmr` / `snapshot_delta` / `crdt` shapes (later; the store/session split is
  designed for them).
- Performance optimization — pure-language first; revisit only on evidence.
