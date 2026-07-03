# Taut Shape Runtimes — Architecture & the `log` Delivery Contract

Status: design (draft). Scope: design only, no phasing.

Audience: **any Taut client that needs to implement protocol delivery shapes**
(`log`, `stream`, …). This document defines the generic, reusable delivery
contract for Taut's shapes — where it lives, how it is implemented per language,
and how cross-language behavior is kept honest. It is not written for any one
client.

Why now: a shape runtime is something you generalize from a *second* consumer,
not the first — so this work was always planned but deliberately deferred until
one existed. **glade** is the first/existing implementation (the source we
extract from); **gwz** (gwz-cli/gwz-py) is now the second, which is what lets us
pull the mechanism out of glade and prove it against two independent clients.
gwz and glade are therefore the two concrete *validators* of this design — not
its drivers. Any client-specific need (e.g. gwz's `diff.output` binary patch
stream, or its cache-backed production) appears below only as an illustration of
the generic contract, never as a design constraint.

---

## 1. Problem: Taut specifies data, not delivery

Taut today gives a complete, corpus-proven story for **data parity**:

- **IR** — message/enum/method defs in `*.taut.py`; `shape` is the sole delivery
  discriminator (`unary/atom/log/stream/swmr/snapshot_delta/crdt`), validated
  against the `SHAPES` registry, with `out` binding the shape's slots.
- **Runtime** — per-language CBOR codec source (`gen/runtime/cbor.rs`,
  `cbor.ts`, …), vendored into consumers via `--with-runtime`.
- **Oracle** — the golden corpus (byte-parity, reproduced by every language).

But `shape` drives **no** codegen. The only thing generated from it is the
`is_streaming(shape)` bit (unary call vs. stream subscribe). A `shape="log"`
method emits only its message types and a stub; the *log-read mechanics* —
cursor, EOF, close/cancel, retention, backpressure, framing — are **left
unspecified and hand-rolled per consumer**. Today there are three divergent
hand-rolled log readers:

| | gwz-py bridge | glade node | taut reference |
|---|---|---|---|
| transport | in-process PyO3 | `[FrameType tag][CBOR body]` over WS/iroh | JSON envelope, base64(CBOR) |
| read model | pull/long-poll `wait_events(op,after_seq,timeout)` | push `Subscribe{from}` → `Ops[]` | `transport.subscribe()` |
| cursor | client `after_sequence`, filtered client-side | `Head{origin,seq}` resume vector | none explicit |
| close | none | `Unsubscribe` + `ChannelClose` (once) | none |
| retention | unbounded `Vec`, never freed | append-only forever (GC future) | n/a |

Each is a private re-invention of the same mechanism; any new client implementing
a `log` shape would write a fourth. This effort gives every client one shared
contract instead — gwz's `diff.output` simply happens to be the next consumer
that would otherwise have hand-rolled its own.

## 2. Thesis: delivery parity as a third layer

Add the parallel three layers for **delivery** that Taut already has for data.
The top layer (`SHAPES`) exists but is otherwise inert; the runtime and oracle
layers are the missing two-thirds.

| Layer | Data (exists) | Delivery (this effort) |
|---|---|---|
| IR | message defs | `SHAPES` + per-shape companion messages (cursor/read/state) |
| Runtime | per-language CBOR codec | per-language **sans-io shape state machines** |
| Oracle | golden corpus (byte-parity) | **behavioral oracle** (state-transition parity) |

## 3. Repo topology

| Repo | Owns | Code |
|---|---|---|
| `taut` | the DSL/compiler + per-language codec runtimes; consumer schemas declare `shape="log"` methods | tooling |
| `taut-shape` | design docs, the **`shape_log` message schema** (compiled by `tautc`, D17), **+ the behavioral oracle corpus** (the cross-language contract) | schema + corpus |
| `taut-shape-rs` | reference sans-io runtime + async adapter; first impl (extracted from glade); initial oracle generator | yes (first) |
| `taut-shape-py` | pure-Python impl + asyncio adapter; conforms to the oracle | later |
| `taut-shape-ts` | TS impl + Promise/async-iterator adapter; conforms to the oracle | later |

Rationale for per-language repos (`taut-shape-<lang>`) over a polyglot mono-repo:
the *sans-io core is small, but the async adapter is substantial and irreducibly
per-language* (see §6) — there is little to co-locate. Lockstep is instead held
by the oracle (§7), not by co-location.

Distinctions:
- **taut owns codec byte-parity**; **taut-shape owns behavioral parity** — a
  different conformance dimension taut does not generate today.
- The companion *message types* are schema, so they live in `taut`. The
  *behavior* of reading them lives in `taut-shape*`.

## 4. The `log` delivery contract

Normative detail (message vocabulary, resolution rules, pinned decisions
D1–D16) lives in [`TautClientImplPlan.md`](TautClientImplPlan.md) §2–§4. This
section is the design summary.

Identity / scope / lifecycle:
- **`log_id`** is an opaque handle minted by the producing call (e.g. `diff`
  returns `DiffOutputLogRef{log_id}`). Holding the ref is the authority to read.
- **`stream_id`** names one *stream instance*: one logical read loop with its
  own position. Many streams per client, at different positions, over one log
  (backed-up readers). Clients/connections are an adapter concern the engine
  never sees; streams are disposable (position lives in the client-held cursor).
- Operation-scoped, finite lifetime: created by the producing call, released on
  close / EOF-drain / TTL / last-stream-end / disconnect.
- Single-origin (no replication): the cursor is a scalar, not a vector.

Engine shape: a **pure mailbox endpoint** (`LogNode`, one per log) —
`handle(input) -> [outputs]`, no I/O, no clock, no callbacks. Internally split
into a **store core** (records window, head, floor, sealed/closed/failed) and a
**session table** of per-stream response handlers (held long-poll, timer token,
watermark). Held tail-reads are engine state, answered when a later input
releases them; timers are `SetTimer`/`TimerExpired` messages.

Companion messages — declared in a self-contained, **payload-agnostic** taut
schema (`taut-shape/ir/shape_log.taut.py`) and **generated** into every language
(D17); messages + codecs, no `service`, exactly glade's wire-schema pattern
("carries opaque app payloads (already taut-encoded)"). The wire vocabulary is
the service-level form of the engine's messages; nothing here is hand-written
per language except the In/Out unions:

```python
LogState = Enum(data=0, would_block=1, eof=2, closed=3, failed=4, expired=5)

LogErrorCode = Enum(unknown_log=0, producer_error=1, internal=2)

LogCursor = Msg(
    seq=F(1, INT))                              # records strictly after this are unseen
                                                # byte_offset reserved for future partial-record delivery

LogReadRequest = Msg(
    log_id=F(1, STR),
    stream_id=F(2, STR),                        # the stream instance (correlation)
    cursor=F(3, Ref.LogCursor, optional=True),  # absent = from start (seq 0)
    max_records=F(4, INT, optional=True),       # generic backpressure knob
    max_bytes=F(5, INT, optional=True),         # generic backpressure knob
    timeout_ms=F(6, INT, optional=True))        # absent = hold; 0 = probe; >0 = hold + timer

LogEndStream = Msg(
    log_id=F(1, STR),
    stream_id=F(2, STR))                        # adapters inject on transport death

LogRecord = Msg(
    seq=F(1, INT),
    payload=F(2, BYTES))                        # the method's append-type message, taut-encoded

LogReadResponse = Msg(
    log_id=F(1, STR),
    stream_id=F(2, STR),
    records=F(3, List(Ref.LogRecord)),
    next_cursor=F(4, Ref.LogCursor),            # ALWAYS present, even when empty
    state=F(5, Ref.LogState),
    error=F(6, Ref.LogError, optional=True))    # attached when state = failed
```

Semantics (summary; oracle-pinned via D-numbers in the impl plan):
- **Cursor** — `next_cursor` on every response. Resume = `seq > cursor.seq` scan
  ⇒ no dup / no skip. First record `seq=1`; `START={seq:0}` (D8).
- **Records** — `LogRecord{seq, payload}` (D11): `payload` is the method's
  `append`-slot message, already taut-encoded (e.g. a `DiffOutputRecord` whose
  `data` field carries the patch bytes) — the glade `Op.payload` pattern, which
  keeps the log vocabulary generic without generics; the method's `out=` binding
  declares what the payload decodes to. NUL-safe end to end (CBOR major-type-2,
  proven across Rust/Py/TS).
- **States** — `data`, `would_block` (probe/timeout while live), `eof`
  (sealed and drained), `closed` (deliberate teardown), `failed` (producer
  error, with `error` attached — D12), `expired` (invalid cursor; response
  carries the earliest resumable `next_cursor` — D9). Expiry is a state, never
  an error.
- **Retention** — bounded window inside the engine; consumer-driven `Evict` in
  v0, with the engine tracking per-stream watermarks so the safe (min-reader)
  floor is computable (D7). This is the profile *between* glade's
  "durable-forever log" and its "ephemeral nothing channel."
- **Backpressure** — `max_records`/`max_bytes` bound a batch (payload bytes
  only, with a forward-progress guarantee — D10); per-stream addressing lets an
  adapter apply per-client transport backpressure without penalizing fast
  readers.
- **Producer-stop** — an output message (`ProducerStop`), emitted on `Close` and
  on the last-stream-ended transition per the `stop_when` knob (D6). The shell
  routes it to the producer (pager-quit / broken-pipe / disconnect ⇒ the render
  halts and releases state).
- **Diagnostics** — an output message (`LogDiagnostic{severity, code}`): a
  sans-io engine cannot log, so warnings ride this output and the shell routes
  them to the host's logging facility. Code-only, no free text (D18); v0's one
  case is a `Push` after `Seal`/`Close`, dropped and warned (D19).

## 5. Production backing

v0: record bytes live in the engine's **bounded internal window** (D2); the
producer `Push`es into it and the consumer drives retention via `Evict`. The
consumer's larger store — a keyed cache, a durable append store — sits *outside*
the engine as the thing that seeds or re-creates logs. For byte stores that
should not pass through the window (disk/network-backed), the designed
**additive extension** is the `ScanRequest`/`ScanResult` message pair (impl plan
§9): the shell answers scans as asynchronously as it likes, with zero change to
the v0 vocabulary and no async coloring of the engine.

The one cross-cutting requirement any producer must honor: a lazy/cold render
must react to `ProducerStop`, so a disconnect during first production stops work
and releases its state.

*Illustration (gwz):* `diff` plans to render into a fingerprint-keyed cache and
replay it into per-operation logs (free re-reads); its cache-key design is a gwz
concern specified elsewhere. This is one backing choice, not part of the contract.

## 6. The mailbox engine and its shells

The runtime is a **pure message-queue engine** (D1): fully synchronous, and the
async question dissolves rather than being answered. A tail read that cannot be
answered is *held inside the engine* and released by a later input — there is no
readiness callback, no notify hook, no per-language await loop re-implementing
the long-poll. Everything that would have been a callback or I/O is a message:
timers (`SetTimer`/`TimerExpired`), producer-stop (`ProducerStop` out),
cancellation (`EndStream` in), store interaction (v0 internal; §5 extension).

This is what makes the engine droppable into **either** environment:
- a network adapter deserializes frames → `handle` → serializes addressed
  outputs to connections;
- an in-memory consumer (gwz) constructs the same messages in-process — the
  message-based API discipline holds without a network, so gwz's later
  detachment is a transport swap, not an API migration;
- asynchronous *producers* (disk reads, libgit2-over-network) need nothing
  special: they `Push` when bytes arrive; held reads wait until then.

The **shell** is per-language and part of each `taut-shape-<lang>`: a pump that
serializes `handle` (the engine is unsynchronized by design — D15), dispatches
addressed outputs, runs real timers, plus idiomatic streaming sugar (Rust
`Stream`, TS `AsyncIterable`, Python async generator) whose cancellation maps to
`EndStream` (Rust drop, `AbortSignal`, `CancelledError`).

**Design rule — taut-shape stays PyO3-agnostic.** The genuinely hard parts —
cross-runtime wakeup (a Rust producer thread waking an asyncio loop via
`call_soon_threadsafe`), cancel propagation across PyO3, backpressure crossing
back — do **not** live in `taut-shape`. They live at the gwz-core(Rust) ↔
gwz-py(Python) producer↔reader seam, isolated in gwz's bridge. The engine is
drivable purely synchronously, embeddable in Rust, and carries zero assumptions
about cross-language async. Where the engine sits relative to the gwz boundary
is a gwz integration decision, not a taut-shape one.

**Python stays pure.** No Rust-backed binding in the lower layers; performance is
not the driver here. This is consistent with taut's existing pure-Python wire
codec, and it removes the worst of the PyO3 story (no Rust-async ↔ asyncio
bridge). Revisit only if profiling shows it is needed.

## 7. The behavioral oracle (the cross-repo contract)

A versioned, language-neutral corpus of vectors — pure message I/O, matching the
engine shape:
```
input message sequence (Push / Read / Seal / Close / EndStream / TimerExpired / Evict)
  →  expected output message sequence (Response / SetTimer / CancelTimer / ProducerStop)
```
Initially **generated by `taut-shape-rs`** (the reference impl), committed to
`taut-shape`, then reproduced by every other `taut-shape-<lang>` in CI. Mirrors
glade's fold oracle (`glade_folds.json`) generated-by-Rust / reproduced-by-TS.
A "corpus bump" is the single coordination point across the language repos.

The contract: *take the reference code or leave it, but you must pass the
oracle.* That is what stops the drift the three existing hand-rolled readers
already exhibit.

Illustrative vectors to define first: append+read; resume from cursor (no
dup/skip); probe → `would_block`; held read released by `Push`; seal → `eof`;
close mid-hold (`closed` / `failed`+error); read below the floor → `expired` +
resumable cursor; `max_bytes`/`max_records` boundary + forward progress; and the
multi-stream cases — two held streams woken by one `Push` (creation-order
emission), `EndStream` mid-hold, last-stream-end → `ProducerStop`,
retry-supersede.

## 8. Extraction plan: glade → taut-shape-rs

Reuse (distill, do not lift-and-shift):
- `store.rs` — append-only store, `scan`/`heads`/`missing_for` resume,
  truncated-tail handling.
- `session.rs` — `Heads`/`missing_for`.

Note the mapping is structural, not just line-level: glade's `store.rs` vs
`session.rs`/`client_heads` split is exactly the engine's **store core** vs
**session table** (per-stream response handlers) — glade already embodies the
backing-store / response-handler separation this design makes normative.

Transform:
- Strip the replication/CRDT layer: `origin`/`seq`/`lamport`/`prev`-hash/`refs`/
  fold collapse to **single-origin**; the resume vector becomes a scalar cursor.

Add (the finite-log lifecycle glade lacks):
- `EOF` (glade logs are unbounded), `close`/cancel, `WouldBlock`, bounded
  reader-coupled retention with GC, producer-stop-on-close.

Then: taut-shape-rs generates the oracle; `events.subscribe` and `diff.output`
become consumers of the same runtime, retiring gwz-py's bespoke `wait_events`.

## 9. Scope & non-goals

- **`log` first** (the live demand: gwz `diff.output`, `events.subscribe`).
- **The full shape registry is committed roadmap, not speculation**: **gryth**
  (the glade-based node + browser-client stack) will need *all* of them —
  `atom`, `stream`, `swmr`/`snapshot_delta`, and `crdt` (at which point glade's
  fold/op machinery is extracted here and glade/gryth become consumers).
  Sequencing stays demand-ordered — each shape lands as a sibling schema
  (`shape_<name>.taut.py`), corpus (`<name>.v0.json`), and per-language engine
  module riding the same generic machinery (mailbox pattern, store-core/
  session-table split, oracle harness, tool framing, bump procedure).
- Consequence for the generic layer: it must be validated against the hardest
  shapes *before* it hardens further — `crdt` makes clients writers
  (stream-addressed op inputs, fan-out outputs) and `swmr`/`snapshot_delta` are
  multi-slot (`snapshot`/`delta`/`reset`) — see `TautShapeRoadmap.md`.
- Pure Python; per-language packages published per ecosystem
  (`taut-shape` crate / wheel / npm, or explicit `taut-shape-<lang>`). Local-only
  repos until publication is decided.
- Out of scope here: glade's distributed superstructure (zones, leases, folds,
  CRDT, P2P); the diff cache-key fingerprint design; gwz's bridge integration.

## 10. Open decisions

Resolved since v1 (now pinned as D1–D16 in `TautClientImplPlan.md` §4): engine
shape (pure mailbox endpoint), bytes-in-window v0, stream-instance identity,
supersede rule, producer-stop policy knob, retention watermark, seq origin,
expired-as-state, `max_bytes` accounting + forward progress, `Record.seq`,
`closed`/`failed` split, canonical state strings, timeout semantics, shell-owned
serialization, determinism rules. Repo topology: per-language repos
`taut-shape-<lang>`; the oracle lives in `taut-shape`.

Still open:
- Whether `taut` *generates* oracle scaffolding for the companion messages, or
  taut-shape-rs remains the sole generator.
- Framing for the remote path (align with glade's `[FrameType tag][CBOR body]`
  vs. defer; in-process v0 needs no framing — the CLI tool's length-prefixed
  framing is test-only).
- Published package names per registry (crate/wheel/npm).
