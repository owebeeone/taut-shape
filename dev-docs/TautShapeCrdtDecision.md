# Taut CRDT Delivery and Text Specialization Decision

Status: accepted for `crdt.oracle/v1` and `text_crdt.profile/v1`  
Date: 2026-08-22  
Scope: Phase 7 of `TautShapeImplementationPlan.md`

## Decision

`crdt` is a payload-agnostic replicated-operation delivery engine. It owns
replica operation identity, causal readiness, deduplication, equivocation,
vector resume, anti-entropy reads, bootstrap, and terminal delivery state. It
does not interpret an operation payload or decide an application's merge.

`text_crdt` is a public specialization over that same engine. It defines a
canonical text-operation payload and deterministic text projection, but it does
not have a second wire envelope, operation store, cursor, deduplicator, or
bootstrap protocol.

## Identity and operation envelope

- `crdt_id` routes one replicated object. It is not part of convergence.
- `stream_id` addresses one anti-entropy read/connection. It is disposable and
  is not a replica identity.
- `origin` is the stable replica/writer identity.
- An operation identity is `(origin, seq)`, where `seq` is positive and starts
  at 1 for each origin.
- `deps` is a normalized version vector: unique origins, sorted by origin,
  non-negative sequence values. The predecessor `(origin, seq - 1)` is also an
  implicit dependency when `seq > 1`; producers should include their observed
  cross-origin dependencies explicitly.
- `payload` is opaque, NUL-safe bytes. The delivery engine never folds it.

An operation is causally ready when all explicit dependencies and its implicit
same-origin predecessor are covered by the engine clock. Valid operations may
arrive in any order. Unready operations are retained in a construction-bounded
pending map and reconsidered after every integration. Ready operations are
integrated in `(origin, seq)` order, so release of a pending batch is stable.

## Deduplication and equivocation

An exact repeat of the complete envelope is idempotent and emits nothing.
Different envelopes with one `(origin, seq)` are equivocation. The engine emits
one `equivocation` diagnostic for that identity and keeps the lexicographically
smallest canonical `(deps, payload)` variant. This deterministic winner rule is
deliberately independent of arrival order. It is not an endorsement of a
malicious writer: applications may quarantine an origin after the diagnostic.

An invalid operation is rejected without changing the accepted op set. Invalid
cases are: empty origin, non-positive sequence, duplicate/unsorted/negative
clock entries, a self-dependency at or beyond the operation sequence, or an
operation that cannot enter the configured pending bound. Diagnostics are
machine-readable; malformed wire data fails in the codec before the engine.

## Clock, reads, and reconnect

`CrdtClock` is a normalized version vector. Missing origins mean sequence zero.
The engine clock records the greatest contiguous integrated sequence per
origin, including a bootstrap floor.

`CrdtReadRequest.cursor` is the caller's current clock. An absent cursor means a
fresh replica. A valid read returns every integrated operation above the
caller's components, sorted by `(origin, seq)`, and the complete current clock.
Reads are immediate in v1:

- `data` when a bootstrap or operations are returned;
- `empty` when caught up and the engine is active;
- `eof` when caught up and sealed;
- `closed` or `failed` after close; and
- `invalid_cursor` if any caller component is ahead of the engine.

Because an operation may depend on another origin, a receiver applies the
returned batch through its own `CrdtNode`; it must not treat response order as a
substitute for causal validation. Reconnect sends the durable local clock and
therefore neither duplicates nor skips accepted operations.

## Bootstrap

`CrdtBootstrap` carries an opaque application snapshot plus the normalized
clock it covers. It may be installed only into an engine with no bootstrap,
accepted operations, or pending operations. Repeating the exact bootstrap is
idempotent; any other later bootstrap is `bootstrap_conflict` and is rejected.

The bootstrap clock is the retention floor. Historical operations at or below
that floor are already covered and are ignored. A read cursor below any floor
component receives `bootstrap_required` with the bootstrap and all retained
tail operations. A fresh absent cursor also receives the bootstrap. Bootstrap
state is not interpreted by the common engine.

V1 retains every post-bootstrap operation; compaction is deliberately deferred.
A future retention/compaction change requires a contract version change and new
vectors, not a hidden implementation policy.

## Lifecycle and errors

`seal` stops future applies/bootstrap installation and lets caught-up reads
return `eof`; retained data remains readable. `close` rejects future mutation
and makes reads return `closed`, or `failed` with the supplied typed error.
Applying after seal/close produces `apply_after_terminal`. Repeated terminal
inputs are idempotent.

The v1 engine has no held reads or timers. Anti-entropy shells choose when to
poll or exchange clocks. This keeps network scheduling outside the convergence
contract while preserving the same result for offline/reconnect delivery.

## Text specialization

Text payloads are canonical UTF-8 JSON objects:

```json
{"kind":"insert","atom_id":"a:1","after":null,"text":"A"}
{"kind":"delete","atom_id":"a:1"}
```

`atom_id` is a stable application-level text-item identity and is independent
of the envelope identity. An insert creates one non-empty text item after
another item (or at the root). Concurrent siblings are ordered by `atom_id`.
A delete is a tombstone and may arrive before its insert. A conflicting reuse
of an `atom_id` resolves to the lexicographically smallest
`(after, text, envelope identity)` insert and reports `atom_equivocation`.
Missing parents, cycles, malformed payloads, and invalid bootstrap state are
reported as sorted, deduplicated text diagnostics; they never alter common-core
delivery diagnostics.

Text bootstrap bytes encode canonical JSON
`{"atoms":[{"atom_id", "after", "text", "deleted"}, ...]}`. The projection
loads that materialized state, then applies the common engine's retained tail.
All implementations expose the same pure projection so every operation order
produces the same text and diagnostics.

## Compatibility boundary

Glade's existing `(origin, seq, lamport, prev, payload)` fold was evidence, not
the wire contract. This decision reuses `(origin, seq)` and equivocation
semantics, replaces the single `prev` chain with a version-vector dependency
boundary, and leaves Lamport ordering to payload CRDTs that need it. Existing
Glade value/log folds are unchanged.

The first consumer is Glial's collaborative-text adapter. It owns a local
`CrdtNode`, queues edits while offline, exchanges common-core operations and
clocks on reconnect, and projects through `text_crdt`. No Glial-only merge or
cursor rule is permitted.

## Acceptance evidence

- `crdt.oracle/v1`: mailbox behavior, invalid input, dedup, deterministic
  equivocation, reorder, bootstrap, resume, and lifecycle.
- `crdt.convergence/v1`: N-replica delivery permutations with identical clocks,
  op sets, and diagnostic sets.
- `text_crdt.profile/v1`: inserts, concurrent siblings, deletes-before-inserts,
  offline merge, bootstrap, and deterministic text diagnostics.
- Rust, TypeScript, and Python pass both corpora and a live 3x3 multi-replica
  matrix.
- The Glial collaborative-text integration passes offline edit and reconnect
  without private convergence behavior.
