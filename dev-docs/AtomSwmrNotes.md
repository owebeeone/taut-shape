# Atom / SWMR Notes — decisions and divergences from the roadmap sketch

Status: Phase 1 contract decisions. Scope: every place `TautShapeRoadmap.md` §1
(`atom`) and §3 (`swmr`) left a decision open, and every deliberate divergence
from the sketch, recorded here with the reasoning — for Gianni/taut review
before these schemas/corpora are treated as load-bearing across languages.

Companion artifacts: `ir/shape_atom.taut.py`, `ir/shape_swmr.taut.py`,
`corpus/atom.v1.json` (+ `corpus/scripts_atom/`, `corpus/atom_gen.py`),
`corpus/swmr.v1.json` (+ `corpus/scripts_swmr/`, `corpus/swmr_gen.py`).

Both schemas are modeled precisely on `shape_log.taut.py`'s idiom (D1–D23 in
`TautClientImplPlan.md`), reusing its message layering (core types / node
inputs producer / node inputs stream / node inputs environment / node
outputs), its enum-based type-tag registry, its opaque-`BYTES`-payload
pattern, and its comment style. Where a shape's semantics force a departure,
it is called out explicitly below rather than silently copied or silently
invented.

---

## `atom`

### 1. `atom_id` added to `AtomReadRequest`/`AtomReadResponse`

The roadmap's §1.2 vocabulary sketch table writes `AtomReadRequest{stream_id,
version?, timeout_ms?}` with no `atom_id`. This schema adds `atom_id` to both
`AtomReadRequest` and `AtomReadResponse` for identity-model parity with
`log_id`/`value_id` (D3: the opaque handle is service-level routing,
orthogonal to `stream_id`). The sketch's omission reads as an informal
shorthand, not a deliberate design choice to drop routing — `griplab`'s
`presence.get`/`presence.subscribe` (the atom exemplar) both need to name
*which* atom. Divergence: additive, low-risk.

### 2. `AtomReplace` after seal/close: dropped + diagnostic

The roadmap sketch table only says timers/`ProducerStop`/lifecycle "carry
over as-is" without spelling out whether a `replace` after seal/close mirrors
`log`'s `push_after_terminal` (D18/D19). Decision: yes, exactly mirrored —
`AtomReplace` is dropped (version unchanged) and emits
`AtomDiagnostic{warn, replace_after_terminal}`. Reasoning: the roadmap's own
§1.3 verdict is "atom is a strict simplification of log," and a late in-flight
replace racing a close is exactly the same expected race `log` already names;
inventing silent/fatal behavior instead would be a gratuitous divergence.

### 3. `version > current` is clamped, not a new state

The roadmap explicitly deletes `expired` for atom (no floor to fall below)
but does not say what happens if a client's `version` parameter somehow
exceeds the engine's current version (a client bug — the engine is the sole
source of truth on `version`, so this cannot happen legitimately). Decision:
treat it identically to "caught up" (`version == current`) rather than
inventing a new state. Reasoning: `log`'s `expired` rule 3's "beyond-head"
half has no atom analogue *because there is no floor/head distinction to
misuse* (roadmap §1.2) — clamping is the minimal-invention response, not a
new wire-visible behavior.

### 4. "Generation change" maps to an ordinary `AtomReplace`; no generation concept in taut-shape

`datascad/dev-docs/DatascadPhase0Spec.md` §3.4 requires "an incompatible atom
generation terminates the old typed subscription and the generated binding
establishes a new one." This is a **consumer-level** concept. Decision:
taut-shape's `atom` shape has **no** generation field or generation-awareness
at all — a generation bump is just another `AtomReplace` with a new opaque
payload. The consumer decodes the payload, decides compatibility, and if
incompatible, issues an ordinary `AtomEndStream` followed by a fresh
`AtomReadRequest` — both existing, generic mechanisms, not a new one. This is
the load-bearing generic/specific split the task explicitly calls out; see
`corpus/scripts_atom/04_generation_change_replace.json`'s comment for the
vector demonstrating it.

### 5. No `AtomEvict` (dropped, not "cannot arise")

The roadmap says `expired` "cannot arise" for atom but doesn't explicitly say
whether `LogEvict`'s message itself carries over as a no-op or is dropped
from the schema entirely. Decision: dropped entirely (no `AtomEvict` message)
rather than kept as an always-no-op input. Reasoning: an input with no
possible effect and no possible response is pure schema noise; `log`'s own
`§8 Non-goals` precedent values additive-only schemas, and a future language
implementation should not have to special-case an eviction message that can
never do anything.

---

## `swmr`

### 6. One mechanism for "first snapshot" and "compaction" (`SwmrSnapshotPush` always re-bases)

The roadmap (§3.2/§3.3) treats the *first* snapshot establishment and
*periodic compaction* (folding deltas into a new base, advancing
`snapshot_base_seq`) as related but not explicitly unified. Decision: **one
message, one rule** — `SwmrSnapshotPush` always sets `snapshot := (head,
payload)` and clears the delta window, whether this is the very first
snapshot (`head` was 0) or a later re-basing. Reasoning: a generic engine
cannot fold opaque delta payloads into a snapshot itself (it doesn't
understand the payload); only the producer can, and it does so by simply
pushing a fresh snapshot. Unifying avoids a second message type
(`SwmrCompact`) with near-identical semantics. This is the schema's single
biggest simplification relative to the sketch's "two coupled structures"
framing (§3.3) — see `dev-docs/TautShapeRoadmap.md` §3.3 for the store-core
discussion this simplifies.

**Formerly-known cost, resolved 2026-07-19 (PH0-D20/D24, PH0 review
remediation):** this entry originally set the new snapshot's resume position
at `head+1` — i.e. establishing/re-basing a snapshot consumed a
delivery-sequence slot, exactly like an ordinary delta. That had a genuine
cost: a reader exactly caught up at `head` when a routine `SnapshotPush`
arrived (even one whose content was materially unchanged, a pure
re-assertion) would have its next delivery flagged `state=reset,
reason=retention_exceeded` even though nothing was actually lost, because the
reader's stored cursor (`head`) was now one below the new snapshot's `seq`
(`head+1`). PH0-D20 fixes this by making a snapshot consume NO
delivery-sequence slot: `SwmrSnapshotPush` resumes at the PRE-push `head`
(the `base`), not `head+1` — deltas still run `base+1`. A reader's stored
cursor at the pre-push head is therefore still exactly equal to the new
snapshot's `seq`, so the very next resolve sees them as caught up, not stale
(PH0-D24). This removes the tension entirely for the common case (a producer
re-asserting unchanged or additively-changed state); it does NOT change the
genuine-compaction case, where a producer intentionally trims retained
history a caught-up reader could still reach — that reader is unaffected
either way (their cursor was already at/above the new base), and a reader
who was genuinely behind (cursor below the new base) still correctly gets
`reset, reason=retention_exceeded`. Pinned by
`corpus/scripts_swmr/26_caught_up_survives_compaction_push.json`.

### 7. Absent `cursor` is NOT equivalent to `{epoch: 0, seq: 0}` (divergence from `log`'s D8)

`log`'s D8 treats an absent cursor as exactly `{seq: 0}` (`START`), and reading
from `seq: 0` is *always* a legitimate, always-retained position (log retains
from the beginning by default; only `Evict` raises the floor). `swmr` has no
such position: because `SwmrSnapshotPush` always retires everything below the
new base (decision 6), there is no "read from the very beginning" position
that survives a compaction. Decision: `SwmrReadRequest.cursor` **absent**
means "no prior state, give me whatever exists now" and this is the *only*
way to express a request that can never resolve to `reset` — a literal
`{epoch: 0, seq: 0}` is instead treated as a claimed prior position like any
other cursor, and resolves to `reset` if epoch 0 is stale or, within the
current epoch, once a snapshot exists at `seq >= 1`. This is a deliberate,
documented divergence from D8's "absent ⇒ `{seq:0}`" equivalence, forced by
swmr's genuinely different
positional model (a position is only valid once a snapshot has established
it; `log`'s positions are valid from the very beginning by construction).

### 8. `next_cursor` is OPTIONAL (divergence from `log`'s "next_cursor ALWAYS present", D8)

Because there is no valid position before the current epoch has a snapshot
(see #7), `SwmrReadResponse.next_cursor` is optional and absent exactly when
the current epoch has no snapshot. Once a snapshot exists in that epoch, it
is present and carries both the current `epoch` and `head` sequence. This is a
second, related, documented divergence from `log`'s D8 guarantee.

**Clarified 2026-07-19 (PH0-D19, PH0 review remediation, fixes review
F5-02/F5-03):** two loose ends in #7/#8's original phrasing turned out to be
under-specified once a producer `SwmrReset` was exercised against a held
read:

- `SwmrReset`'s field comment used to say it "answers **every** currently
  held read with `state=reset`" — this is now scoped to reads whose ORIGINAL
  request named a positioned (non-absent) `cursor`. An absent-cursor hold
  never had a position to be reset FROM (#7's whole point), so a reset must
  not force-answer it `reset` either; the engine instead re-resolves it
  against the fresh (post-reset, snapshot-less) state via the ordinary
  resolver, which simply leaves it holding until a real snapshot arrives.
- A reset response produced immediately by `SwmrReset` has no `next_cursor`
  (never a hardcoded `{seq: 0}`, which the original implementation emitted)
  — consistent with #8's "present iff a snapshot currently exists" rule: a
  `SwmrReset` discards the snapshot, so no snapshot exists immediately after
  one. A later read carrying an old epoch receives `reset` with the current
  epoch's fresh snapshot/deltas and `next_cursor` if a new snapshot now exists.
  `{seq: 0}` was doubly wrong: it manufactured an incomplete position, and a
  same-epoch zero position is a "claimed stale position" (#7) that resolves to
  `reset(retention_exceeded)` the moment the next snapshot lands — handing a
  just-reset reader a guaranteed second reset.

Every response path — including the ones answering `SwmrTimerExpired` and
`SwmrReset` — now computes `next_cursor` through the one canonical resolver;
none of them echo a caller-supplied position or hardcode one. Pinned by
`corpus/scripts_swmr/25_absent_cursor_hold_across_reset.json`,
`.../32_timed_reset_cancels_timer.json`, and the updated
`05_generation_change_reset.json`.

### 9. `writer_id` and single-writer enforcement — a new mechanism, not in the sketch

The roadmap sketch's swmr vocabulary table has no writer-identity concept at
all (unlike `crdt`'s `origin`); producer inputs are "node-local" exactly like
`log`'s in v0. But the registry (`shapes.py`) declares `writers="single"` for
`swmr`, and the task's required corpus coverage explicitly asks for a
"writer-uniqueness violation as an error vector" plus "single-writer
discipline." A purely node-local, unaddressed producer input (mirroring
`log` verbatim) gives the wire vocabulary **no way to detect** a second
writer, since there is nothing to compare. Decision (new mechanism, not
sketched): add a `writer_id: STR` field to the three content-changing
producer inputs (`SwmrSnapshotPush`, `SwmrDeltaPush`, `SwmrReset` — NOT
`SwmrSeal`/`SwmrClose`, which stay writer-agnostic teardown, mirroring `log`
exactly). The engine binds `writer_id` on the first producer-content input
seen; any later producer-content input from a *different* `writer_id` is
rejected (dropped, `SwmrDiagnostic{error, writer_conflict}`) rather than
applied — the same shape of guard as `value`'s equivocation rejection (reject
and surface, never silently corrupt state). This is the single largest
structural addition beyond the roadmap sketch in this schema; flagging for
explicit review since it changes swmr's message shapes more than any other
decision here.

### 10. `max_deltas` retention/backpressure bound — a new mechanism, not in the sketch

Datascad requires "bounded retention/queues" and a "backpressure/
retention-bound behavior" vector; the roadmap's §3.3 discussion of
compaction/retention is architectural narrative, not a wire mechanism.
Decision: add a construction knob `max_deltas: int | None` (mirrors D6's
`stop_when` knob pattern). When `SwmrDeltaPush` would push the retained delta
count past `max_deltas`, it is rejected (dropped, `SwmrDiagnostic{error,
retention_bound_exceeded}`) rather than silently evicting the oldest delta —
because evicting the oldest delta without a corresponding snapshot payload
would leave the engine unable to answer a stale reader at all (it has no way
to materialize the folded state itself; only the producer can, via
`SnapshotPush`). This makes the bound a **hard backpressure signal to the
producer** ("you must `SnapshotPush` before you can push more deltas"),
rather than an automatic, silent trim — consistent with the task's framing of
the requirement as *backpressure*, not silent data loss. Datascad's separate
"bounded subscriber queues" requirement is judged to be already covered by
this same mechanism plus the pull/cursor-based read model (swmr reads, like
`log`'s, are cursor-in/cursor-out, not a push queue — there is no per-reader
queue to bound beyond the shared retained-delta window); no second queue-depth
mechanism was added. Flagged for review alongside #9 as the two mechanisms
this schema introduces beyond the sketch.

### 11. `SwmrResetReason.invalid_resume_seq` — a defensive case the sketch didn't name

The roadmap's swmr discussion only names the below-floor case
(`retention_exceeded`) as triggering `reset`; it does not discuss a cursor
*ahead* of `head` (a position that never existed — always a client bug,
since the engine is authoritative on `seq`). Decision: treat it the same way
as a stale cursor — `state=reset` with a fresh snapshot+deltas attached, but
tagged with its own reason (`invalid_resume_seq`) rather than conflating it
with genuine retention pressure. Reasoning: `log`'s D9 already treats both
"below floor" and "beyond head" as the single `expired` state (just with
different `next_cursor` values); swmr's typed-reason model gives an
opportunity to distinguish them precisely, which is strictly more informative
and costs nothing. Pinned (this reason previously had schema/code but no
vector, review F5-06) by
`corpus/scripts_swmr/24_invalid_resume_seq_after_snapshot.json`.

**Clarified 2026-07-19 (review F5-13):** `SwmrReset.reason` reuses the full
`SwmrResetReason` enum, so a producer's `SwmrReset` input is wire-legal even
if it names an engine-only reason (`retention_exceeded`/`invalid_resume_seq`
— both assigned above by the engine's own read resolution, never
legitimately by a producer). Rather than splitting the enum (a v0-incompatible
change), the engine normalizes: any producer-supplied `reason` other than
`producer_requested` is replaced with `producer_requested` before it is
echoed to readers. A producer-declared reset is, by definition, always
`producer_requested`.

### 12. `SwmrDelta.base_seq` is redundant with `seq - 1` but kept explicit

Every `SwmrDelta` in this engine has `base_seq == seq - 1` (deltas are always
contiguous, one at a time) — the field is redundant with the reference
engine's own invariant. Decision: keep it anyway, unreduced, because (a) it
mirrors `griplab`'s `FileDelta{base_seq, seq, ...}` precedent the roadmap
cites verbatim (§3.1), and (b) a future producer-side batching extension
(one `SwmrDeltaPush` covering a wider `[base_seq, seq]` span in one message)
is a natural additive extension this field already anticipates, matching
`log`'s own "named type so it can grow" reasoning for `LogCursor` (D8/D11).
Not built now — v0 always has `base_seq = seq - 1` — but the field is not
dead weight.

### 13. Reference-engine generation strategy: a hand-written Python mailbox, not an external tool or a pure fold

`gen.py` (log) shells to the external Rust `taut-shape-tool`; `value_gen.py`
imports a small pure function (`fold_value`) already living in the taut
runtime. Neither precedent fits atom/swmr: there is no per-language engine
for either shape yet (both are new), and neither is a pure fold — both have
state that outlives one message (held reads, timer tokens, sealed/closed
flags), so a bare fold-import approach (à la `value_gen.py`) cannot express
them. Decision: `atom_gen.py`/`swmr_gen.py` each embed a small, hand-written
reference mailbox engine (`AtomNode`/`SwmrNode`) directly in the generator,
mirroring `log`'s `LogNode` mailbox model in miniature. This is corpus-
generation tooling only — taut-shape still ships no engine of its own for any
shape (the repo's stated rule: "the reference code is optional; the oracle is
mandatory") — but it is a third distinct generation strategy alongside the
other two, worth flagging explicitly since a reviewer comparing `gen.py`/
`value_gen.py`/`atom_gen.py`/`swmr_gen.py` side by side will otherwise wonder
why they don't all look alike.

### 14. Vector catalog additions beyond the task's stated minimum

The task's minimum for swmr was: initial snapshot, delta batches, resume
success, resume-expired reset, generation-change reset, two readers, writer-
uniqueness violation, backpressure/retention. This corpus additionally
carries the full `log`/`atom`-parity lifecycle set (held-read/timer/
supersede/seal/close/idempotent-teardown/end_stream/producer_stop/
push-after-terminal/delta-before-snapshot/terminal-still-readable) so that
swmr's basic mailbox-lifecycle behavior is pinned exactly as rigorously as
`log`'s and `atom`'s, not just its shape-specific new behavior. Same for
atom's fuller lifecycle set beyond the task's four named vectors.

### 15. Roadmap D25 (swmr stream disposability) resolved trivially: window steering dropped for v0

Added 2026-07-19 (review F5-04): this document's opening claim — it records
"every place §1/§3 left a decision open" — was incomplete without an explicit
entry for `TautShapeRoadmap.md`'s **D25 [HIGH]**: "is D3 (streams are
disposable, position lives in the client cursor) `log`-only, once a
`window.update`-style reader-steering concept exists?" The delivered `swmr`
schema has no `window` concept at all — no window field, no `window.update`
message, no reader-steering state in the session table. Decision: (a) — D3
stays universal. `swmr` streams remain fully disposable exactly like `log`'s
and `atom`'s: the entire position a stream needs to resume is the client-held
`cursor`, nothing server-side survives an `end_stream`. D25's question is
resolved trivially for v0 because its premise (a reader-steering mechanism)
was never built — not because the harder case (D3 vs. a stateful session)
was adjudicated. If a future `window.update`-shaped mechanism is added to
`swmr` or a later shape, D25's (a)/(b) choice becomes live again and must be
revisited on its own merits; this note only certifies that v0 does not
trigger it.

### 16. Roadmap D28 resolved: one core selected by a fixed recovery profile

The catalog decision resolves D28: `swmr` and `snapshot_delta` are two fixed
public recovery profiles of one SWMR core, never two stores or engines. The
core is selected at construction through a closed recovery policy:
`repair` for `shape="swmr"` and `expire` for `shape="snapshot_delta"`.
`repair` owns the v1 behavior pinned here: unreconstructible or stale-epoch
cursors receive typed, in-band reset/repair with fresh state when available.
`expire` will expose an out-of-band refresh outcome and will not expose a
producer reset as a profile application event.

Both fixed profiles are now implemented. `snapshot_delta.profile/v1` has four
profile-specific vectors and thin wrappers in Rust, TypeScript, and Python.
Each wrapper instantiates the same `SwmrNode` store/session/lifecycle core with
`expire`, then projects a core reset to `refresh_required`; it rejects the
repair profile's application outcome without copying or forking `SwmrNode`.
The exact profile surface and evidence are recorded in
`TautShapeSnapshotDeltaDecision.md`.

## Phase 1 pre-freeze decisions

### 17. Atom v1 single-writer enforcement is an adapter obligation

Atom is normatively single-writer, but its producer messages remain node-local
and deliberately carry no `writer_id`. Adding writer identity would make the
strict `log` simplification heavier without improving the mailbox's state
semantics. Decision: the shell/adapter MUST bind exactly one producer to an
Atom node and reject a second producer binding before either producer can send
`AtomReplace`, `AtomSeal`, or `AtomClose`. Once inputs reach `AtomNode`, their
single-writer provenance is trusted.

This cannot be demonstrated by the Atom mailbox corpus because the corpus
starts after adapter binding and the messages contain no writer identity. Each
portable adapter MUST therefore carry a conformance test that attempts two
bindings, observes rejection of the second before state mutation, and proves
the first producer remains authoritative. An adapter that has no such check
must not advertise Atom v1 support.

### 18. Durable SWMR reset epoch, detail propagation, and node restart

`SwmrCursor` is `(epoch, seq)`, not a sequence alone. A new node incarnation
starts at epoch 0; successful `SwmrReset` increments the node-owned epoch and
retains the normalized reset reason plus opaque `detail` for that epoch.
Snapshot re-basing/compaction never changes epoch. A cursor from an older epoch
always receives `state=reset`, even if its sequence equals a valid sequence in
the new epoch; the response carries the retained producer detail and, when the
new epoch has a snapshot, its fresh snapshot/deltas and current cursor. A
future epoch is `invalid_resume_seq`. An absent cursor still means fresh
subscribe and never receives historical reset.

`swmr_id` identifies one node incarnation. A shell MUST NOT reuse an id for a
recreated node at epoch 0 while old cursors for that id can survive. It may
reuse the id only if it durably restores an epoch greater than every epoch the
prior incarnation issued; otherwise it must allocate a new `swmr_id`. This
keeps restart behavior unambiguous without requiring this pure mailbox engine
to perform persistence. Corpus vector
`33_reset_between_polls_epoch_overlap.json` pins the missed-between-polls and
overlapping-sequence regression; vector 5 and vector 33 pin `reset_detail`.
