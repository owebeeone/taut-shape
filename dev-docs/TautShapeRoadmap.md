# Taut Shape Roadmap — the generic machinery, stress-tested against every shape

Status: design (draft). Scope: **design only** — no phasing, no implementation.
This memo is a *pre-hardening review*, not a plan.

Catalogue note (2026-08-22):
[`../../dev-docs/TautShapeCatalogDecision.md`](../../dev-docs/TautShapeCatalogDecision.md)
is now authoritative for names and boundaries. In particular, `value` is a
distinct engine, `snapshot_delta` is an SWMR profile, and `message`, `exchange`,
and `window` are not Taut delivery engines. The sections below remain useful as
per-engine stress tests; their older raw-registry descriptions are historical.

Audience: the `taut-shape-<lang>` maintainers and anyone about to build shape #2.
It presumes [`TautShapeArchitecture.md`](TautShapeArchitecture.md) (the three-layer
thesis, the mailbox engine, the store-core/session-table split) and
[`TautClientImplPlan.md`](TautClientImplPlan.md) (D1–D20, the `log` vocabulary),
and reads the validated canonical registry as the executable catalogue
([`taut/src/taut/ir/shapes.py`](../../taut/src/taut/ir/shapes.py)).

Why now, and why adversarial: only `log` exists (schema + rs/ts/py engines +
oracle, all green). But the committed consumer is **gryth** — the glade node +
browser-client stack — and gryth needs *all* the shapes:
`atom`, `stream`, `swmr`/`snapshot_delta`, `crdt`. The architecture doc asserts
(§9) that the generic machinery "must be validated against the hardest shapes
*before* it hardens further." This memo is that validation. The mailbox engine
(D1) and the store-core/session-table split (D2/D3) were designed *from* `log`;
the honest question is whether they were designed *to* `log`. Two shapes are the
real tests and this memo refuses to assume they pass: **`crdt`** (clients become
writers — bidirectional) and **`swmr`/`snapshot_delta`** (the store is
multi-slot, not an append window). Where the pattern strains, this memo says so
in those words.

The through-line: every shape lands as a sibling `shape_<name>.taut.py` schema, a
`<name>.v0.json` corpus, and a per-language engine module riding the same
mailbox pattern — *if* the pattern holds. The `log` module namespacing already
anticipates this: rs keeps the generated vocabulary under `generated::` and the
core types own the short names precisely so a second shape can't collide
([`taut-shape-rs/.../lib.rs:40`](../../taut-shape-rs/crates/taut-shape/src/lib.rs));
py already nests the whole engine under `taut_shape/log/`
([`taut-shape-py/src/taut_shape/log/`](../../taut-shape-py/src/taut_shape/log/)).
So the physical room for shape #2 exists; this memo asks whether the *semantic*
room does.

---

## 1. `atom` — latest-only state

### 1.1 Semantics (registry + prior art)

`atom`: `payload="whole-state"`, `history="latest"`, `initiation="pull|push"`,
`writers="single"`, `events={"replace"}`, `delivery="stream"`
([`shapes.py:32`](../../taut/src/taut/ir/shapes.py)). One slot, `replace`. The
GripLab surface binds it twice — `presence.subscribe` (push/stream) and
`presence.get` (pull/unary) over the same `PeerPresence`
([`griplab.taut.py:87`](../../taut/ir/griplab.taut.py)) — which is the whole
character of `atom`: **the subscribe and the get return the same thing**, a
current value, differing only in whether they tail.

The load-bearing difference from `log` is `history="latest"` vs
`"append-only"`: an atom keeps exactly one record (the current state), and a new
`replace` **overwrites** rather than appends. There is no back-history to resume
into; a late reader gets the latest state and then tails changes.

### 1.2 Vocabulary sketch — `shape_atom.taut.py` δ from `shape_log`

Atom is `log` with a window of size 1 and no seq-scan resume. Concretely:

| `shape_log` message | in `shape_atom` | note |
|---|---|---|
| `LogPush{payload}` | → `AtomReplace{payload}` (renamed) | overwrites the single slot; `history="latest"` (D8-analogue: monotonic `version`, not `seq`) |
| `LogReadRequest{cursor?, max_records?, max_bytes?, timeout_ms?}` | → `AtomReadRequest{stream_id, version?, timeout_ms?}` | **no `max_records`/`max_bytes`** (a single record; backpressure is meaningless) |
| `LogRecord{seq, payload}` | → `AtomValue{version, payload}` | `version` replaces `seq` — a change counter, not a position |
| `LogReadResponse{records[], next_cursor, state}` | → `AtomReadResponse{value?, next_version, state}` | **one optional value, not a list**; `next_version` is the cursor |
| `LogState{data, would_block, eof, closed, failed, expired}` | → drop `expired` | latest-only ⇒ nothing to evict-past ⇒ **`expired` cannot arise** |
| `LogCursor{seq}` | → `AtomVersion{version}` | scalar, same role |
| `LogSeal` / `LogClose` / `LogEvict` / `LogEndStream` / timers | carry over **as-is** | lifecycle is shape-invariant |

Carries over as-is: `stream_id` identity (D3), held-read-as-state, timers,
`ProducerStop`, `Diagnostic`, close/seal/failed lifecycle. New: the
version-vs-seq distinction (a `replace` bumps `version`; a read with
`version == current` holds/probes). Dropped: `max_records`/`max_bytes`,
`expired`, the record *list*, and the whole eviction/floor apparatus.

The read resolution collapses to two arms: `version < current` → `data` with the
one value; `version == current` → hold/probe/`eof`/`closed`. Rule 3
(invalid/expired cursor, [`TautClientImplPlan.md` §3.4](TautClientImplPlan.md))
**vanishes** — there is no floor and no beyond-head, only "you have the latest or
you don't."

### 1.3 Engine δ

The store core shrinks: `Window` (append vector + head + floor) becomes a
single `Option<(version, payload)>`. `Evict` becomes a no-op (or is removed).
Watermarks and the min-reader floor (D7) are **not needed** — there is nothing
to retain. The session table is **unchanged**: per-stream held read, timer token,
`stream_id` addressing — an atom is exactly one held-read parked on
"version advanced past mine." One-`Replace`-wakes-two-streams is the direct
analogue of D16's one-push-wakes-two, same creation-order emission.

**Verdict: the mailbox pattern holds for `atom`, cleanly.** Atom is a *strict
simplification* of `log` — a degenerate log with window=1. If anything it is the
proof that the store-core/session-table split has slack: the session table
carries over verbatim while the store core degenerates. This is the easy shape
and confirms the split's lower bound.

---

## 2. `stream` — ephemeral events, no history

### 2.1 Semantics (registry + prior art)

`stream`: `payload="whole-or-delta"`, `history="none"`, `initiation="push"`,
`writers="source"`, `events={"event"}`, `delivery="stream"`
([`shapes.py:40`](../../taut/src/taut/ir/shapes.py)). GripLab's
`session.output.subscribe` (terminal PTY bytes,
[`griplab.taut.py:104`](../../taut/ir/griplab.taut.py)) is the exemplar:
live-only output, subscribe-from-now, no replay of what you missed. Glade models
this as the `Channel*` frames — "ephemeral, never replicated"
([`glade.taut.py:143`](../../taut/ir/glade.taut.py)).

`history="none"` is the defining constraint: **no backfill, no resume, no
cursor**. You subscribe and receive events from the moment you subscribe; a
disconnect loses the gap unrecoverably (that is the contract, not a bug).

### 2.2 Vocabulary sketch — `shape_stream.taut.py` δ from `shape_log`

Stream is `log` with the *entire history/resume subsystem deleted*:

| `shape_log` | in `shape_stream` | note |
|---|---|---|
| `LogPush{payload}` | → `StreamEmit{payload}` | fan out to all live subscribers; **not stored** |
| `LogReadRequest{cursor, max_records, max_bytes, timeout_ms}` | → `StreamSubscribe{stream_id, timeout_ms?}` | **no cursor** (no resume), **no `max_*`** unless you keep a bounded live buffer |
| `LogRecord{seq, payload}` | → `StreamEvent{payload}` | **no `seq`** — "history none" means no position to name (registry rules it out) |
| `LogState` | → `{data, would_block, closed, failed}` | **no `eof`** (a stream has no defined end — it's live until closed), **no `expired`** (no floor) |
| `next_cursor` | **removed** | nothing to resume from |
| `LogEvict` | **removed** | nothing retained |

Carries over as-is: `stream_id` identity, held-read-as-state (a subscriber with
no pending event is exactly a held read), timers, `ProducerStop`, `Close`/`failed`,
`Diagnostic`. This is the "no cursor / no window / no eof" shape the brief flags.

**Open tension — the delivery model inverts.** `log` is *pull*
(`initiation="pull|push"`, cursor-in/cursor-out; the client asks, the engine
answers or holds). `stream` is *push-only* (`initiation="push"`). In a pure
mailbox that inversion is cosmetic — a "subscribe" is just a permanently-held
read that is *never* superseded by a new read (there is no next read carrying a
cursor; the subscriber holds one slot forever and the engine pushes into it).
But it forces a **buffering decision the log engine never faced**: when
`StreamEmit` arrives and a subscriber's held slot is *already filled* (it hasn't
drained the prior event), does the engine (a) drop, (b) coalesce (`whole-or-delta`
— the registry explicitly allows a delta/whole choice here, glade's `pri`
conflation, [`glade.taut.py:49`](../../taut/ir/glade.taut.py)), or (c) buffer a
bounded queue? `log` sidesteps this because every record has a `seq` and lives in
the window — the client always catches up by cursor. `stream` with
`history="none"` has **no window to catch up from**, so slow-consumer policy
becomes a *first-class engine concern* rather than an adapter one.

**Verdict: the mailbox pattern holds, but `stream` surfaces the slow-consumer
question the window hid.** Not a break — the engine can carry a per-session
bounded event buffer (which is a session-table concern, exactly where D3 says
per-stream richness lives) — but it is the first place where "the store core is
shared, the session table grows" (§2.2 of the impl plan) becomes load-bearing
rather than aspirational. Decision needed (see D24 below): is the drop/coalesce/
buffer policy a construction knob (like `stop_when`) or fixed?

---

## 3. `swmr` + `snapshot_delta` — multi-slot reconstructible state

Taken together, per the brief, because `snapshot_delta` is `swmr` minus the
`reset` slot.

### 3.1 Semantics (registry + prior art)

`swmr`: `payload="delta"`, `history="reconstructible"`, `initiation="push"`,
`writers="single"`, `events={"snapshot", "delta", "reset"}`
([`shapes.py:44`](../../taut/src/taut/ir/shapes.py)).
`snapshot_delta`: identical but `events={"snapshot", "delta"}` — no `reset`
([`shapes.py:48`](../../taut/src/taut/ir/shapes.py)).

The prior art is `griplab.taut.py`'s file subscription — the single richest hint
in the tree:

- `FileSnapshot{resource_id, resume_seq, content, window_start, window_end}`
  ([`griplab.taut.py:39`](../../taut/ir/griplab.taut.py)) — **`resume_seq` is
  called out as "the load-bearing resume offset."** A snapshot is a *base state
  at a sequence*.
- `FileDelta{resource_id, base_seq, seq, ops, result_size}`
  ([`griplab.taut.py:46`](../../taut/ir/griplab.taut.py)) — an incremental change
  from `base_seq` to `seq`, carrying `ByteOp[]`.
- `file.subscribe` binds `out={"snapshot": FileSnapshot, "delta": FileDelta}`
  ([`griplab.taut.py:97`](../../taut/ir/griplab.taut.py)) — the multi-slot `out`
  the registry's `sole_slot` guard forbids collapsing
  ([`shapes.py:67`](../../taut/src/taut/ir/shapes.py)).
- `file.window.update{start, end}` (role `ctl`,
  [`griplab.taut.py:99`](../../taut/ir/griplab.taut.py)) — a **client input on a
  read shape**: the reader steers *which window* of the file it wants
  snapshots/deltas for. This is a second, subtler bidirectionality (below).

The delivery model: a subscriber first receives a `snapshot` (base state at
`resume_seq`), then a tail of `delta`s. `reset` (swmr only) tells the subscriber
to discard and re-snapshot (the base moved out from under it — a truncation, a
window jump). This is `griplab`'s SWMR and glade's log-backfill `Chunk`
snapshot pattern ([`glade.taut.py:157`](../../taut/ir/glade.taut.py)) unified.

### 3.2 Vocabulary sketch — `shape_swmr.taut.py` δ from `shape_log`

This is the first shape where the δ is **structural, not a subset**:

| concept | `shape_log` | `shape_swmr` |
|---|---|---|
| producer input | `Push{payload}` (one kind) | **three kinds**: `SnapshotPush{base_seq, content}`, `DeltaPush{base_seq, seq, ops}`, `Reset{}` |
| store core | append window of records | **snapshot slot + delta window above it** (two coupled structures) |
| resume | `cursor{seq}` scan | `SnapshotRef{resume_seq}` → snapshot-or-delta stream |
| read response | `records[]` | **`snapshot` first, then `delta[]`** — a *tagged* response stream |
| state | flat | + a `needs_snapshot` / `reset` state (your `base_seq` fell below the retained snapshot) |

The read resolution gains a genuinely new arm the log engine has no analogue for:
**"your `base_seq` is below the current snapshot base."** In `log` that maps to
`expired` (below floor). In `swmr` it maps to **`reset` → re-deliver snapshot**,
which is *recoverable in-band* — the engine ships a fresh `snapshot` and the tail
of `delta`s above it. So `log`'s `expired` (client-decides-lossy) becomes swmr's
`reset` (engine-repairs-automatically). That is not a rename; it is a different
recovery contract.

New relative to everything in `log`:
- **Multi-slot output** (`snapshot` vs `delta` vs `reset`) — the response is no
  longer a homogeneous `records[]`; it is a tagged union stream. The oracle's
  whole-output equality still works, but the vector `out` arrays now carry a
  slot discriminator.
- **`window.update` as a reader→engine input** — the reader narrows/moves its
  window; the engine responds with a fresh snapshot for the new window. This is
  a **`Read` that carries steering, not just a cursor** — the first crack in
  "reads are cursor-in/cursor-out, streams are disposable" (D3). A swmr stream is
  **not** disposable: its *window state* lives in the session entry, not in a
  client-held cursor. Lose the stream and you lose the window selection, not just
  a held poll.

### 3.3 Engine δ — **the store-core/session-table split is genuinely tested here**

This is one of the two adversarial cases, so no assuming.

**Store core.** The append window (D2) does **not** generalize as-is. swmr's
store core is *two coupled structures*: a current snapshot (base state at
`snapshot_base_seq`) and a delta log above it, with an invariant
`snapshot_base_seq ≤ min(delta.base_seq)` and periodic compaction (fold deltas
into the snapshot, advance the base — the swmr analogue of `Evict`). The log
engine's `floor`/`head` scalars become `{snapshot_base, delta_head}` and the
retention story is *compaction*, not eviction. **This is real new store-core
code, not a parameterization.** The claim "the store core stays shared"
([impl plan §2.2](TautClientImplPlan.md)) is *refuted for swmr as literally
written* — but survives in spirit: it is still *one* store core, still owning
records/head/floor/lifecycle, just with a richer internal representation. The
architectural boundary holds; the append-window *implementation* does not
transfer.

**Session table.** Here the split earns its keep — and strains. The impl plan
predicted "for `crdt`/`swmr` the session entry grows richer (per-stream sync
state)" ([§2.2](TautClientImplPlan.md)); swmr confirms it precisely. The session
entry gains: the subscriber's **window selection** (`window_start/window_end`),
its **base_seq** (has it seen the current snapshot?), and a **"needs snapshot"**
flag. A `Read` (or `window.update`) now consults *both* the shared store core
*and* per-session window state to decide snapshot-vs-delta-vs-reset. The
addressing (`stream_id`) and held-read machinery carry over unchanged, so the
session table's *frame* holds; its *payload* is genuinely shape-specific.

**Where it strains, honestly:** `window.update` breaks the D3 disposability
invariant. In `log`, a stream is disposable because its whole position is the
client-held cursor; reconnect with a fresh `stream_id` + the old cursor and
nothing is lost. In `swmr`, the *window selection* is engine-side session state
that the client would have to re-assert on reconnect. Either (a) `window.update`
state must be echoed back to the client so it can re-assert (keeping streams
disposable — the D3 spirit), or (b) swmr streams are *stateful* and D3's
disposability is a `log`-only property. This is a **decision, not a detail** (see
D25). The mailbox pattern itself holds — `window.update` is just another
addressed input, held reads are still parked in the session table — but the
*disposability guarantee* does not generalize untouched.

**snapshot_delta** is swmr minus `reset`: drop the `Reset` input and the
`needs_snapshot`/`reset` state; the below-base case becomes `expired`-like
(client-decides) again rather than engine-repairs. So snapshot_delta is *closer*
to `log` than swmr is — it is the intermediate rung. Recommended: **build swmr
and derive snapshot_delta as the reset-less profile of the same engine** (a
construction knob `reset_policy ∈ {in_band, expire}`), rather than two engines.

**Verdict: the split holds *architecturally* but not *by code reuse*.** swmr
needs a new store-core implementation (snapshot+delta+compaction) and a richer
session entry (window+base). The mailbox message discipline survives intact. The
honest correction to the impl plan: "store core stays shared" should read "store
core stays *singular and same-role*," not "same code."

---

## 4. `crdt` — clients become writers (the bidirectional shape)

The hardest shape, and the one glade already implements — so this is extraction,
not invention. Maximum adversarial scrutiny.

### 4.1 Semantics (registry + prior art)

`crdt`: `payload="ops"`, `history="reconstructible"`, `initiation="push-bidi"`,
`writers="multi-merge"`, `events={"op", "sync"}`, `delivery="stream"`
([`shapes.py:52`](../../taut/src/taut/ir/shapes.py)). Three registry axes flip
from every prior shape at once: `writers="multi-merge"` (not single/source),
`initiation="push-bidi"` (the **only** bidi shape), `events={op, sync}` (two
slots, one of which — `sync` — is *anti-entropy metadata*, not app data).

The prior art is the richest in the tree and already oracle-backed:

- The op envelope: `Op{share, glade_id, key, origin, seq, prev, lamport, refs,
  shape, payload}` ([`glade.taut.py:82`](../../taut/ir/glade.taut.py)) — per-origin
  monotonic `seq`, `prev`-hash chain, `lamport` clock, causal `refs`. This *is*
  the crdt op input.
- The heads/resume unit: `StreamHeads{share, glade_id, key, heads:[Head]}` where
  `Head{origin, seq, hash}` ([`glade.taut.py:61`](../../taut/ir/glade.taut.py)) —
  a **per-origin resume vector**, not a scalar cursor.
- The bidirectional sync: `Subscribe{from:[Head]}` / `Heads{streams}` / `Ops{ops}`
  both directions ([`glade.taut.py:110`](../../taut/ir/glade.taut.py)) — the
  heads-exchange-then-gap-ship protocol, coded carrier-independent in
  `session.rs::missing_for` ([`glade/node/src/session.rs:25`](../../glade/node/src/session.rs)).
- The fold: `fold_value` (lww by `(lamport, origin, seq)`) / `fold_log` (order by
  `(lamport, origin, seq)`), both **pure functions of the op-set**, deduped by
  `(origin, seq)`, equivocation-detecting
  ([`glade_fold.py:50`](../../taut/src/taut/crdt/glade_fold.py);
  [`fold.ts:41`](../../glade/client-ts/src/fold.ts)) — already a cross-language
  oracle (`glade_folds.json`).
- The op-hash chain: `op_hash = sha256(canonical_cbor(op))`
  ([`glade_chain.py:31`](../../taut/src/taut/crdt/glade_chain.py)), oracle-backed
  by `glade_hashes.json`.
- The GripLab surface: `board.local_apply` (in), `board.merge` (ctl),
  `board.sync` (out, `shape="crdt"`, `out={"op": CrdtOp}`)
  ([`griplab.taut.py:143`](../../taut/ir/griplab.taut.py)) — the local-apply /
  merge-remote / sync triad.

### 4.2 Vocabulary sketch — `shape_crdt.taut.py` δ from `shape_log`

Everything the brief names is present in prior art — this is the sketch:

| concept | `shape_log` | `shape_crdt` |
|---|---|---|
| input (producer) | `Push{payload}` node-local, unaddressed | **`OpInput{stream_id, op:Op}` — client-addressed, bidirectional** (clients write ops) |
| input (control) | — | `SyncRequest{stream_id, heads:[Head]}` — anti-entropy: "here's what I have, ship gaps" |
| output (data) | `LogRecord{seq, payload}` | **`OpFanout{op}` — fan out one origin's op to *all other* subscribers** |
| output (control) | `next_cursor{seq}` scalar | `SyncResponse{heads:[Head], ops:[Op]}` — the gap ship (`missing_for`) |
| cursor / resume | `Cursor{seq}` scalar | **`Heads{[Head{origin,seq}]}` — a resume *vector*, per-origin** |
| identity | `stream_id` (a read loop) | `stream_id` **+ `origin`** (a peer/writer identity, chain-owning) |
| record | opaque payload | `Op{origin,seq,prev,lamport,refs,payload}` — attributed, chained |
| new failure | `failed` (producer) | **`equivocation`** (forked `(origin,seq)` — a *client* fault, detected in-engine) |

This is where the architecture doc's own §8 extraction plan runs in **reverse**:
`log` was built by *stripping* replication/CRDT from glade
("`origin`/`seq`/`lamport`/`prev`-hash/`refs`/fold collapse to single-origin; the
resume vector becomes a scalar cursor" — [architecture §8](TautShapeArchitecture.md)).
`crdt` **puts every one of those back**. So `shape_crdt.taut.py` is essentially
`glade.taut.py`'s `Op`/`Head`/`StreamHeads` re-homed under the shape schema, with
the `Subscribe`/`Ops`/`Heads` frames renamed to the sync vocabulary. **Almost
nothing of `shape_log` carries over as-is** — the scalar cursor, the single
writer, the node-local producer, the append-only-no-merge store are all exactly
the things `crdt` reverses.

### 4.3 Engine δ — **does the mailbox pattern actually hold? (adversarial)**

Four specific stresses, each answered honestly:

**(1) Bidirectionality — clients are writers.** In `log`, producer inputs
(`Push`/`Seal`/`Close`) are *node-local and unaddressed* — "the producer lives
with the node" ([impl plan §3.5](TautClientImplPlan.md)). In `crdt`, the producer
inputs arrive *from clients, addressed by `stream_id`/`origin`*, and every op
must **fan out to all other subscribers**. Does the mailbox `handle(input) ->
[output]` shape survive? **Yes — and this is the pattern's strongest result.**
`OpInput` is one input; its outputs are N `OpFanout`s addressed to the N-1 other
sessions (creation-order emission, D16, generalizes directly). glade's `echo.rs`
(`handle(&Frame) -> Vec<Frame>`, cited in
[`TautShapeOracle.md` §2](TautShapeOracle.md) as the mailbox shape in miniature)
already *is* a fan-out mailbox. The "producer-side inputs are unaddressed" clause
is a **`log` specialization, not a mailbox property** — the engine shape is
input→outputs regardless of who authored the input. **Bidirectionality does not
break the mailbox; it breaks a `log`-only simplifying assumption in §3.5.**

**(2) The store core must *merge*, not append.** `log`'s store appends by scalar
`seq` and rejects gaps. `crdt`'s store is glade's `Store`
([`glade/node/src/store.rs`](../../glade/node/src/store.rs)): per-`(origin)`
chains, idempotent by `(origin,seq)`, **equivocation-detecting** (a different
payload/hash at an existing `(origin,seq)` is a forked chain, rejected —
[`store.rs:93`](../../glade/node/src/store.rs)), `prev`-hash-verified. Materialized
state is the *fold* over the op-set. **This is a categorically different store
core** — multi-writer, content-addressed, merge-semantic. The impl plan's "store
core stays shared" is **refuted for crdt** more sharply than for swmr: it is not
even the same *role* (a log store answers "records after seq N"; a crdt store
answers "ops you're missing given your heads" + "the fold"). What survives is
narrower: it is still *one store core per stream, no I/O, pure*. The
**store-core/session-table boundary** survives; the store-core *contract* does
not.

**(3) The cursor is a vector, not a scalar.** D8's `Cursor{seq}` and its whole
"records strictly after seq" resume is **single-origin by construction**
(architecture §8 says so explicitly). crdt resume is `StreamHeads` — a per-origin
vector, and `missing_for` ([`session.rs:25`](../../glade/node/src/session.rs)) is
the vector-diff gap-ship. The `LogCursor` "named type so it can grow"
([impl plan §3.1](TautClientImplPlan.md)) hedge does **not** stretch to a vector
cleanly — a vector cursor changes the read-resolution algebra (per-origin gap
computation vs a single `seq > cursor` scan). **The scalar-cursor decision (D8)
does not generalize; it is correctly a `log`/`atom` property.**

**(4) `sync` is a second slot that is *metadata*, not app payload.** The `sync`
out-slot (`events={op, sync}`) carries heads/version-vectors — engine protocol
state exposed on the wire, unlike `log` where all engine protocol state
(`next_cursor`) rides *inside* the response envelope. crdt makes anti-entropy a
*first-class app-visible exchange* (`board.sync`). The mailbox holds (it is just
another output message), but the oracle must now cover **convergence**, not just
per-node behavior (§below).

**Verdict: the mailbox message-passing shape HOLDS for crdt — bidirectionality,
fan-out, and sync-as-message all reduce to `handle(input)->[outputs]`. What does
NOT hold is that the `log` store core, the scalar cursor, and the "producer is
node-local" model generalize — they were `log`-specific all along, correctly.**
The store-core/session-table *split* survives as an architectural boundary at
maximum stress; the *append-window store core* is a `log`/`atom` artifact. This
is the memo's central finding: **the engine *frame* is shape-generic; the store
*core* is per-shape.** The impl plan overstates code sharing and understates
frame sharing.

### 4.4 What glade/gryth extraction looks like

Per architecture §9, at `crdt` "glade's fold/op machinery is extracted here and
glade/gryth become consumers." Concretely:

- **Move into `taut-shape`** (the crdt engine's guts): `store.rs`'s per-origin
  append/idempotence/equivocation/chain-verify
  ([`store.rs:86`](../../glade/node/src/store.rs)); `session.rs`'s
  `heads_map`/`missing_for` ([`session.rs:18`](../../glade/node/src/session.rs));
  the folds (`glade_fold.py`/`fold.ts`) and `op_hash`
  (`glade_chain.py`/`oracle.test.ts`). These are already pure, already
  oracle-backed — they are *the* extractable core.
- **Stays in glade/gryth** (consumer superstructure, architecture §9 non-goals):
  zones, leases, the single-socket QoS scheduler (`Priority`,
  [`glade.taut.py:49`](../../taut/ir/glade.taut.py)), `Chunk` reassembly,
  P2P/iroh transport, `Hello`/`Welcome` session auth
  ([`glade.taut.py:98`](../../taut/ir/glade.taut.py)), the `principal`/`capability`
  security seams.
- **The seam**: glade keeps `Op` as *its* wire type but its `payload`/`shape`/fold
  selection is delegated to `taut-shape`'s crdt engine. glade's `store.rs`/
  `session.rs` become thin adapters over the extracted engine — exactly the
  architecture-§8 "structural, not line-level" mapping, run for real.
- **Oracle reuse, not re-derivation**: `glade_folds.json` and `glade_hashes.json`
  become the `crdt.v0.json` fold/hash oracle *directly* (§below). This is the
  single biggest free lunch in the whole roadmap.

---

## 5. Oracle / tool δ (per shape)

Each shape gets `corpus/<name>.v0.json` and authored scripts under
`corpus/scripts/`, generated by `taut-shape-rs` `gen`, reproduced by all
languages (the `glade_folds` discipline, [`TautShapeOracle.md` §5](TautShapeOracle.md)).

- **atom** — a *subset* of the log catalog: replace+read, held-read-woken-by-
  replace, one-replace-wakes-two, seal/close/failed, probe→would_block. Drop
  every eviction/expiry/floor/max_bytes vector (§1.2). No new framing.
- **stream** — log catalog minus resume/eviction/eof, **plus** new slow-consumer
  vectors: emit-while-slot-full → drop|coalesce|buffer (the D24 policy, made a
  construction knob so one corpus covers all profiles). No new framing.
- **swmr/snapshot_delta** — genuinely new vectors: snapshot-then-delta stream;
  `window.update` → fresh snapshot; below-base → `reset` (swmr) vs `expired`
  (snapshot_delta, via the `reset_policy` knob); compaction advances base then a
  stale `base_seq` read → reset/expire. The oracle's whole-output equality
  extends unchanged (the `out` arrays just carry slot-tagged messages).
- **crdt** — **two oracle dimensions, one already exists:**
  1. *Fold/hash determinism* — **already `glade_folds.json` + `glade_hashes.json`**,
     Rust-generated/TS-reproduced ([`TautShapeOracle.md` §2](TautShapeOracle.md)
     names them as the precedent this whole design copies). These transplant into
     `crdt.v0.json` with near-zero work — the memo's strongest oracle result.
  2. *Convergence* (**new tool need**) — the existing corpus is single-engine
     (`input seq → output seq`). crdt needs **multi-node vectors**: N engines,
     interleaved op deliveries in different orders, assert all N materialize the
     *same* fold. This is a new corpus *shape* (a scenario is a DAG of
     op-deliveries across nodes, not a linear script) and a new tool mode —
     essentially the interop matrix ([`TautShapeOracle.md` §7](TautShapeOracle.md))
     generalized from `node(X)⊗client(Y)` to `N-replica convergence`. The
     `session.rs` "converges both directions" test
     ([`session.rs:103`](../../glade/node/src/session.rs)) is the template.

The framing (`u32-LE length + CBOR`, OOB JSONL control) carries over for all
shapes. The **new** tool need is crdt convergence scenarios; everything else is
new *vectors* in the existing tool shape.

---

## 6. DECISIONS to settle NOW (candidate D21+)

Ranked by how much a later shape *constrains* an earlier commitment — settle the
high-rank ones before shape #2 lands, because retrofitting them across three
languages after two shapes exist is the expensive path.

**D21 — One shared `Log*`/`Shape*` message registry vs per-shape registries.
[HIGHEST]** Today every generated type is `Log`-prefixed and namespaced under
`generated::` / `taut_shape/log/`
([`lib.rs:40`](../../taut-shape-rs/crates/taut-shape/src/lib.rs),
[`messages.py`](../../taut-shape-py/src/taut_shape/log/messages.py)). Decide
*now* whether `Cursor`/`Record`/`State`/`Error` are (a) per-shape duplicated
(`AtomVersion`, `StreamEvent`, …) or (b) a shared base vocabulary shapes
specialize. Recommendation: **per-shape schemas, no shared base** — the shapes
diverge more than they share (crdt's cursor is a vector, atom's has no floor);
a forced common base would be a false abstraction. But the *naming convention*
must be pinned now (D22). This constrains every subsequent schema file, so it is
first.

**D22 — Naming convention: `<Shape><Concept>` prefix, locked before shape #2.**
`log` chose `Log*` ([`_generated`](../../taut-shape-py/src/taut_shape/log/_generated.py)).
Pin `Atom*`/`Stream*`/`Swmr*`/`Crdt*` as the mandatory prefix so the flat-vs-
namespaced collision `log` already solved by keeping generated types under
`generated::` ([`lib.rs:40`](../../taut-shape-rs/crates/taut-shape/src/lib.rs))
holds for N shapes. Cheap now, painful to retrofit across rs/ts/py after two
shapes ship. Settle with D21.

**D23 — rs/ts/py module namespacing under `log/` *before* shape 2. [HIGH]** py
already nests `taut_shape/log/` ([tree](../../taut-shape-py/src/taut_shape/log/));
rs keeps `generated::` namespaced but the *engine* modules (`node`, `session`,
`window`) are crate-flat ([`lib.rs:55`](../../taut-shape-rs/crates/taut-shape/src/lib.rs))
and ts is `src/`-flat ([tree](../../taut-shape-ts/src/)). Decide the per-shape
module boundary (`taut_shape::log::{node,session,window}`,
`src/log/*.ts`) **now**, while `log` is the only occupant — moving `log`'s
modules after `atom` exists is a churn tax on all three repos. This is a pure
refactor with a closing window.

**D24 — `stream` slow-consumer policy: knob or fixed? [MEDIUM]** Emit-while-
held-slot-full → drop | coalesce (`whole-or-delta`) | bounded-buffer (§2.2).
Make it a construction knob (`overflow ∈ {drop, coalesce, buffer(n)}`) like
`stop_when` (D6) so one corpus covers the profiles. Settle before `stream` so
the corpus doesn't fork. Constrains only `stream`, hence medium.

**D25 — swmr stream disposability: is D3 `log`-only? [HIGH]** `window.update`
puts window-selection state in the session entry, breaking D3's "streams are
disposable, position lives in the client cursor" (§3.2). Decide: (a) echo window
state to the client so it re-asserts on reconnect (**keep D3 universal**), or
(b) swmr streams are stateful (**D3 is a `log`/`atom` property**). This
reinterprets a *pinned* decision, so settle it before swmr and record the
re-scope. Constrains swmr *and* the D3 wording.

**D26 — Does stream-instance identity generalize to crdt peers? [HIGH]** In
`log`, `stream_id` names a *read loop* (D3). In crdt, the writer identity is
`origin` — a chain-owning, equivocation-relevant peer identity
([`store.rs:93`](../../glade/node/src/store.rs)), orthogonal to "which read loop."
Decide the identity model now: is a crdt session `(stream_id, origin)` — a read
loop *plus* a writer identity — or does `origin` subsume `stream_id`? This
constrains the crdt session table and the fan-out addressing, and it is the
place D3 (identity) is most likely to need a documented generalization. Settle
before crdt.

**D27 — crdt convergence oracle: extend the corpus format or a new one?
[MEDIUM]** Convergence vectors are N-node DAGs, not linear `input→output`
scripts (§5). Decide whether `crdt.v0.json` extends the existing per-step format
or introduces a `convergence.v0.json` sibling with its own schema. Settle before
the crdt corpus is authored; the fold/hash half (`glade_folds`/`glade_hashes`)
transplants regardless.

**D28 — swmr = one engine with a `reset_policy` knob, or two engines? [LOW]**
Recommendation in §3.3: one engine, `snapshot_delta` = `reset_policy=expire`
profile. Cheap to decide, avoids a duplicate engine. Low because it is internal
to the swmr repo work.

---

## 7. Recommended shape order (with rationale)

1. **`atom` first.** It is a strict simplification of `log` (window=1, no floor,
   no expiry, no max_bytes — §1). Building it *proves the second-shape mechanics*
   (schema sibling, corpus sibling, module namespacing, bump procedure) against
   the *easiest* possible δ, flushing out D21–D23 (registry/naming/namespacing)
   with minimal semantic risk. It is the shape that tests the *tooling* seam
   without also testing the *engine* seam.
2. **`stream` second.** Removes rather than adds (no history/cursor/eof, §2), but
   surfaces the first genuinely-new engine concern (slow-consumer, D24) and the
   push-vs-pull inversion — a controlled first stress of the session table before
   the multi-slot/bidi shapes.
3. **`snapshot_delta`, then `swmr`.** snapshot_delta is the intermediate rung
   (multi-slot store core + below-base=expired, but no in-band reset — §3.3);
   swmr adds `reset` + `window.update` on top. Building snapshot_delta first
   lets the new **snapshot+delta store core** (the real work, §3.3) land and
   pass its oracle before the `reset`/`window.update` disposability question
   (D25) is piled on. Do them as *one engine, two profiles* (D28).
4. **`crdt` last.** It reverses every `log` simplification at once (§4.2), needs
   the merge store core, the vector cursor, bidi fan-out, and the convergence
   oracle — but it is the *only* shape whose core already exists, oracle-backed,
   in glade. Doing it last means the mailbox frame, the session-table-grows-
   richer pattern, and the corpus-bump discipline are all battle-tested by three
   prior shapes before the extraction from glade begins. Demand-order and
   difficulty-order agree here (architecture §9's demand-ordering is satisfied:
   gryth needs all four, and this is the safe learning curve).

Rationale in one line: **increasing engine-seam stress** — atom tests tooling,
stream tests the session table, swmr tests the store core, crdt tests
everything + convergence. Each shape's *new* risk is isolated from the last.

---

## 8. Explicit NON-changes (what `log` got right, untouched)

The generic machinery that generalizes *verbatim* to all four shapes — do not
touch these when adding shapes:

- **The mailbox engine shape (D1).** `handle(input) -> [outputs]`, pure, no
  clock/locks/callbacks, held reads as engine state — holds for *every* shape,
  including bidi crdt fan-out (§4.3(1)). This is the memo's strongest
  confirmation: the *frame* is fully shape-generic.
- **The store-core / session-table *boundary* (D2/D3).** The *split* survives at
  maximum stress (swmr, crdt); only the store-core *contents* are per-shape
  (§3.3, §4.3). Keep the boundary; expect to rewrite the core.
- **`stream_id` addressing + implicit-create + `EndStream` (D3/D4).** The
  addressing and lifecycle-on-transport-death carry over for all shapes;
  crdt *adds* `origin` beside it (D26) but does not remove it.
- **Held-read-as-state + timers-as-messages (D1/D14).** `SetTimer`/`CancelTimer`/
  `TimerExpired` and the "park the read, release on a later input" model are
  shape-invariant (a subscriber, a tailing atom reader, a swmr delta-waiter, a
  crdt op-waiter are all held reads).
- **`ProducerStop` + `stop_when` knob (D6), `Diagnostic{severity, code}`
  code-only (D18), determinism (D16: monotonic timer tokens, creation-order
  multi-emission).** All shape-invariant; the construction-knob pattern (D6)
  *extends* cleanly to per-shape knobs (D24 overflow, D28 reset_policy) — it is
  the right extension mechanism, reused.
- **The oracle discipline (whole-output equality, Rust-generated / N-language-
  reproduced, versioned corpus, the bump as the single coordination point,
  [`TautShapeOracle.md`](TautShapeOracle.md) §3/§6).** Carries verbatim; crdt
  *adds* a convergence dimension (D27) but the per-node oracle format and the
  bump procedure are untouched. The `glade_folds`/`glade_hashes` precedent the
  design already copied becomes crdt's oracle *directly*.
- **taut-generated vocabulary, hand-written only In/Out unions (D17).** The
  "messages+codecs, no service, In/Out unions by hand" discipline
  ([`messages.py`](../../taut-shape-py/src/taut_shape/log/messages.py),
  [`lib.rs:52`](../../taut-shape-rs/crates/taut-shape/src/lib.rs)) is the per-shape
  authoring pattern — every `shape_<name>.taut.py` follows it unchanged.
- **The `LogRecord.payload = BYTES` opaque-payload pattern (D11/D17).** The glade
  `Op.payload` trick — carry the app message taut-encoded, keep the shape
  vocabulary generic-free — is *the* mechanism every shape uses (atom's value,
  stream's event, swmr's snapshot/delta content, crdt's op payload are all opaque
  BYTES). This is the single most reused idea and needs no change.

---

## Appendix: strain summary (the honest ledger)

| shape | mailbox frame | store core | session table | cursor | new failure mode | verdict |
|---|---|---|---|---|---|---|
| atom | holds | degenerates (window=1) | unchanged | scalar, no floor | none | **holds, clean** |
| stream | holds | removed (no history) | +overflow policy | none | none | **holds; surfaces slow-consumer (D24)** |
| swmr | holds | **new (snapshot+delta+compaction)** | +window+base | `SnapshotRef` | reset/needs-snapshot | **boundary holds, core rewritten; D3 strains (D25)** |
| crdt | holds (fan-out) | **new (merge/fold/equivocation)** | +origin+heads | **vector** | **equivocation** | **frame holds, core+cursor are log-only; convergence oracle new (D27)** |

The one sentence: **the mailbox *frame* (D1) and the store-core/session-table
*boundary* (D2/D3) generalize to every shape; the *append-window store core* and
the *scalar cursor* (D8) do not — they are `log`/`atom` artifacts, correctly. The
impl plan overstates store-core code sharing and understates engine-frame
sharing.**
