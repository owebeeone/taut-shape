"""shape_swmr wire surface — the taut `swmr` delivery-shape vocabulary.

Authored against `taut-shape/dev-docs/TautShapeRoadmap.md` §3 (the swmr
sketch, the design of record) and `dev-docs/AtomSwmrNotes.md` (every decision
the sketch left open, and every deliberate divergence, with reasons). Like
`shape_log`/`shape_value`/`shape_atom` this is the *delivery substrate* for any
`shape="swmr"` method, not an app service: `SwmrSnapshot.payload` and
`SwmrDelta.payload` carry the method's whole-state / incremental-change
messages already taut-encoded (opaque, NUL-safe — the glade `Op.payload`
pattern), so the engine stays payload-agnostic. Modeled as messages + codecs,
NOT a `service`: taut generates the message types; the mailbox engine (the
snapshot+delta store core, held reads, timers) and the In/Out unions are
hand-written per `taut-shape-<lang>` (D1, D17, D21, D22).

IMPORTANT — generic vs specific split: this schema carries NO relational or
query semantics. `generation`/`source_revision`/row semantics named in
`datascad/dev-docs/DatascadPhase0Spec.md` §3.4 are the CONSUMER's concern and
ride inside the opaque `payload`/`detail` BYTES fields; taut-shape owns only
the generic sequence/snapshot/delta/reset/resume/retention lifecycle.

Read whole. Four layers:
  1. core types — SwmrCursor, SwmrSnapshot, SwmrDelta, SwmrError (+ enums)
  2. node inputs — SwmrSnapshotPush/SwmrDeltaPush/SwmrReset/SwmrSeal/SwmrClose
     (producer, writer-checked in v0), SwmrReadRequest/SwmrEndStream
     (stream-side, addressed by stream_id), SwmrTimerExpired (environment)
  3. node outputs — SwmrReadResponse (addressed, tagged by `state`),
     SwmrSetTimer/SwmrCancelTimer, SwmrProducerStop, SwmrDiagnostic

Identity (D3/D4, unchanged from `log`): `swmr_id` is the opaque swmr handle
(service-level routing); `stream_id` names one stream instance — one logical
read loop with ≤1 outstanding read (D5). `writer_id` (NEW relative to `log`;
see `AtomSwmrNotes.md`) names the single producer that has bound this swmr
instance: the first producer-content input (`SnapshotPush`/`DeltaPush`/
`Reset`) binds `writer_id`; any later one from a DIFFERENT `writer_id` is
REJECTED (dropped, `SwmrDiagnostic{error, writer_conflict}`) rather than
applied — this is the wire-level enforcement of `writers="single"`
(`shapes.py`) and the delivery contract's single-writer discipline.

Store model (roadmap §3.3, "two coupled structures", simplified to a single
generic mechanism — see `AtomSwmrNotes.md`): a node-owned reset `epoch`, a
`snapshot` (a full state at a `seq` within that epoch), plus a `deltas` window
strictly above it, contiguous up to `head`. Epoch starts at 0 and increments
only on `SwmrReset`; snapshot compaction/re-basing never changes it. A cursor
therefore names `(epoch, seq)`, which makes a reset durable across polls even
when the new epoch reuses the same sequence numbers.
`SwmrSnapshotPush` ALWAYS establishes a brand-new snapshot at `head` — its
`resume_seq` is the pre-push `base`, consuming NO delivery-sequence slot
(PH0-D20, 2026-07-19: fixes review F5-03's `next_cursor={seq:0}` reset
contradiction and the 56-F2 position-normalization defect) — and clears the
delta window; this is both the FIRST snapshot and every later periodic
re-basing/compaction (one mechanism, not two). Because a re-basing push does
not advance `head`, a reader already caught up at the pre-push head remains
caught up (not reset) across it: compaction never strands a caught-up reader
(PH0-D24, `AtomSwmrNotes.md` #6). `SwmrDeltaPush` requires a snapshot to
already exist and appends one delta at `base+1` (i.e. `head+1`).
`SwmrReset` increments `epoch`, discards all retained state unconditionally
(snapshot AND deltas), and is the producer-declared "start over" signal (the
roadmap's generation-change reset). It carries a machine-readable `reason`
plus an opaque `detail` for app-specific context (e.g. datascad's new query
generation number), never free text (D18's rationale). The engine retains the
normalized reason/detail for the current epoch: a reader that was between
polls during reset and later presents an older epoch still receives
`state=reset` plus that context. The engine normalizes any producer-supplied
engine-only reason (`retention_exceeded`/`invalid_resume_seq`) to
`producer_requested` before retaining/echoing it (review F5-13) — those two
reasons are assigned by the engine's own read resolution, never legitimately
declared by a producer.

The read resolution (see `AtomSwmrNotes.md` for the full case table): an
ABSENT `cursor` always means "no prior state, give me whatever exists now" and
NEVER produces `reset` (there is nothing to have been reset FROM) — this holds
even across a producer `SwmrReset` (PH0-D19, fixes review F5-02): an
absent-cursor held read is re-resolved against the fresh post-reset state via
the ordinary resolver rather than force-answered `reset`, so it simply keeps
holding until a real snapshot arrives. A PRESENT cursor from an older epoch
always answers `state=reset` with the retained producer reset reason/detail,
including when reset occurred between polls. Within the current epoch, a
cursor below the current snapshot's `seq`, or past `head`, cannot be resolved
by the retained delta window and answers `state=reset` with an engine-assigned
`reset_reason` alongside a fresh `snapshot`+`deltas` — the swmr analogue of
`log`'s `expired`, but *engine-repaired in-band* rather than *client-decided*
(roadmap §3.2's central point). `next_cursor` is OPTIONAL (a deliberate
divergence from `log`'s
"next_cursor ALWAYS present", D8): it is present if and only if a snapshot
currently exists in the current epoch (PH0-D19) — absent before its first
`SnapshotPush` and on an immediate `SwmrReset` response, but present on a
later stale-epoch reset after fresh state arrives; never a caller-echoed
position (fixes review F5-03). Every response path — including
the one answering a `SwmrTimerExpired` — computes `next_cursor` through the
same canonical resolver; none of them re-emit a caller-supplied cursor
verbatim (PH0-D19, fixes review 56-F2's timed-expiry normalization defect).

The engine consuming these messages is a pure mailbox (D1): no I/O, no clock —
timers ride SwmrSetTimer/SwmrTimerExpired (D14); teardown consequences ride
SwmrProducerStop (D6). The oracle corpus (`TautShapeOracle.md`) is expressed as
sequences of exactly these messages in taut jsoncodec form.

Regenerate (from taut-dev/taut-shape):
  PYTHONPATH=../taut/src python3 -m taut.cli gen ir/shape_swmr.taut.py \
      -o <out> -l python,typescript,rust --api-only
"""

import sys
from pathlib import Path

# Make the taut builder importable when this file is loaded by path
# (taut is a sibling member of the taut-dev workspace).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "taut" / "src"))

from taut.ir.dsl import BYTES, INT, STR, Enum, F, List, Msg, Ref, schema

SCHEMA = schema(
    # ---- enums -------------------------------------------------------------
    # SwmrMsgType is the mailbox type-tag registry (D21/D22), mirrors
    # LogMsgType/AtomMsgType.
    Enum("SwmrMsgType",
         snapshot_push=0, delta_push=1, reset=2, seal=3, close=4,
         read=5, end_stream=6,
         timer_expired=7,
         read_response=8, set_timer=9, cancel_timer=10,
         producer_stop=11, diagnostic=12),
    # Six read outcomes: `log`'s five (data/would_block/eof/closed/failed)
    # plus `reset` — the swmr-specific, engine-repaired recovery state that
    # replaces `log`'s client-decided `expired` (roadmap §3.2).
    Enum("SwmrState",
         data=0, would_block=1, eof=2, closed=3, failed=4, reset=5),
    # unknown_swmr is service-level (swmr_id routing), mirrors LogErrorCode.
    Enum("SwmrErrorCode",
         unknown_swmr=0, producer_error=1, internal=2),
    # Why the producer was told to stop (D6), mirrors LogStopReason exactly.
    Enum("SwmrStopReason",
         last_reader_gone=0, closed=1, failed=2),
    # Why a `state=reset` response was produced. `producer_requested` is an
    # explicit `SwmrReset` input (e.g. the consumer's generation changed —
    # opaque to taut-shape, carried in `detail`); `retention_exceeded` is a
    # reader's cursor falling below the current snapshot's `seq` (their
    # position was compacted away); `invalid_resume_seq` is a cursor past
    # `head` (a position that never existed — a defensive case the roadmap
    # sketch did not spell out, see `AtomSwmrNotes.md`).
    Enum("SwmrResetReason",
         producer_requested=0, retention_exceeded=1, invalid_resume_seq=2),
    # Severity of an engine diagnostic (D18), mirrors LogSeverity/AtomSeverity.
    Enum("SwmrSeverity", warn=0, error=1),
    # Machine-readable diagnostic codes (D18); open for growth, no free-text
    # companion. `push_after_terminal` mirrors `log`'s D19 (a producer input
    # after seal/close is dropped, warn). `delta_before_snapshot` rejects a
    # `SwmrDeltaPush` with no snapshot yet established (error — a producer
    # sequencing bug, not a benign race). `writer_conflict` rejects a
    # producer-content input from a `writer_id` other than the bound one
    # (error — the single-writer discipline). `retention_bound_exceeded`
    # rejects a `SwmrDeltaPush` once the constructed `max_deltas` bound would
    # be exceeded (error — the generic backpressure/retention-bound signal;
    # the producer must `SnapshotPush` to continue, see `AtomSwmrNotes.md`).
    Enum("SwmrDiagCode",
         push_after_terminal=0, delta_before_snapshot=1,
         writer_conflict=2, retention_bound_exceeded=3),

    # ---- core types ----------------------------------------------------------
    # A durable delivery position `(epoch, seq)` a reader resumes from. `epoch`
    # is node-owned, starts at 0, and increments on every producer reset; it is
    # deliberately independent of opaque consumer generation detail. `seq` is
    # the scalar position within the epoch. Compaction does not change epoch.
    # Unlike `LogCursor`, absence (on `SwmrReadRequest.cursor`) is NOT
    # equivalent to any concrete cursor — see the schema docstring and
    # `AtomSwmrNotes.md`.
    Msg("SwmrCursor",
        F("seq", 1, INT),
        F("epoch", 2, INT)),
    # The base full state at `seq`. `payload` is the method's whole-state
    # message, already taut-encoded — opaque, NUL-safe (D11/D17).
    Msg("SwmrSnapshot",
        F("seq", 1, INT),
        F("payload", 2, BYTES)),
    # One incremental change from `base_seq` to `seq` (griplab's `FileDelta`
    # precedent). `payload` is the method's delta message, opaque (D11/D17).
    Msg("SwmrDelta",
        F("base_seq", 1, INT),
        F("seq", 2, INT),
        F("payload", 3, BYTES)),
    # Attached to `failed` responses (D12) and carried by SwmrClose.
    Msg("SwmrError",
        F("code", 1, Ref("SwmrErrorCode")),
        F("message", 2, STR, optional=True)),

    # ---- node inputs: producer side (writer-checked, node-local in v0) -----
    # Establish a brand-new snapshot at `head` (its `resume_seq` is the
    # pre-push base — a snapshot consumes NO delivery-sequence slot, PH0-D20),
    # clearing the retained delta window (this is both the FIRST snapshot and
    # every later re-basing / compaction — one mechanism, see the schema
    # docstring). Because `head` does not advance, a reader already caught up
    # at the pre-push head stays caught up across it (PH0-D24 — compaction
    # never resets a caught-up reader). Binds `writer_id` if unbound; rejects
    # (drop, `writer_conflict`) if a different writer_id is already bound.
    # Dropped with `push_after_terminal` after seal/close.
    Msg("SwmrSnapshotPush",
        F("writer_id", 1, STR),
        F("payload", 2, BYTES)),
    # Append one delta at `head+1`. Requires a snapshot to already exist
    # (else dropped, `delta_before_snapshot`) and the constructed
    # `max_deltas` retention bound not yet exceeded (else dropped,
    # `retention_bound_exceeded` — the producer must `SnapshotPush` instead).
    # Same writer-check and terminal-drop as `SwmrSnapshotPush`.
    Msg("SwmrDeltaPush",
        F("writer_id", 1, STR),
        F("payload", 2, BYTES)),
    # Increment the node-owned reset epoch and explicitly discard ALL retained
    # state (snapshot and deltas) — the producer-declared "start over" signal
    # (e.g. an app-level generation change, opaque to taut-shape). The
    # normalized reason/detail are retained for the new epoch so a reader
    # between polls cannot miss the reset. Answers every currently held read WHOSE
    # ORIGINAL REQUEST NAMED A POSITIONED (non-absent) `cursor` with
    # `state=reset` immediately (not silence: a typed reset is itself the
    # event); an absent-cursor hold is unaffected — it re-resolves against
    # the fresh post-reset state instead, since it never had a position to be
    # reset FROM (PH0-D19, fixes review F5-02 — this field comment used to say
    # "every currently held read" without that scope). `reason` is
    # normalized to `producer_requested` even if the wire-legal input claimed
    # an engine-only reason (F5-13). `detail` is an optional opaque payload
    # for app-specific context (D11/D17's opaque-payload pattern; D18's "no
    # free text" applies to `reason` itself, not to this opaque companion) and
    # is surfaced as `SwmrReadResponse.reset_detail` on producer-reset
    # responses, including later stale-epoch reads.
    # Same writer-check and terminal-drop as the pushes.
    Msg("SwmrReset",
        F("writer_id", 1, STR),
        F("reason", 2, Ref("SwmrResetReason")),
        F("detail", 3, BYTES, optional=True)),
    # Mark the swmr's producer finished; drained (caught-up) readers then see
    # `eof`. Idempotent. No writer-check (mirrors `LogSeal`: teardown is
    # writer-agnostic). Does not itself emit SwmrProducerStop (only Close
    # does, mirroring `log` exactly).
    Msg("SwmrSeal"),
    # Teardown. error absent => readers see `closed`; present => `failed`
    # with the error attached (D12). Emits SwmrProducerStop. Idempotent (a
    # repeat Close on an already-closed swmr emits nothing, D6). No
    # writer-check (mirrors `LogClose`).
    Msg("SwmrClose",
        F("error", 1, Ref("SwmrError"), optional=True)),

    # ---- node inputs: stream side (addressed by stream_id) ------------------
    # One read on one stream instance. `cursor` ABSENT means "no prior
    # state" (never resolves to `reset` — see schema docstring); a PRESENT
    # cursor is a claimed prior `(epoch, seq)`, resolved against the retained
    # snapshot+delta window (data / would_block / eof / closed / failed /
    # reset). A stale epoch resets before its possibly-overlapping seq is
    # considered. First use of a stream_id implicitly creates the stream (D4); a
    # read on a stream with a held read supersedes it (D5). No
    # `max_records`/`max_bytes` (a read delivers the whole due snapshot+tail
    # in one response, like griplab's file subscription). timeout_ms: absent
    # = hold until data/seal/close/end_stream; 0 = immediate would_block
    # probe; >0 = hold + timer (D14).
    Msg("SwmrReadRequest",
        F("swmr_id", 1, STR),
        F("stream_id", 2, STR),
        F("cursor", 3, Ref("SwmrCursor"), optional=True),
        F("timeout_ms", 4, INT, optional=True)),
    # End one stream instance: drops its held read (no response), cancels its
    # timer; reader-count ≥1→0 may emit SwmrProducerStop (D4/D6). Adapters
    # inject this on transport death. Unknown stream_id = no-op.
    Msg("SwmrEndStream",
        F("swmr_id", 1, STR),
        F("stream_id", 2, STR)),

    # ---- node inputs: environment -------------------------------------------
    # The shell's clock answering SwmrSetTimer. Late/canceled tokens are
    # ignored (no-op).
    Msg("SwmrTimerExpired",
        F("token", 1, INT)),

    # ---- node outputs --------------------------------------------------------
    # The answer to one SwmrReadRequest (or its held release). `snapshot` is
    # present when the response bridges a reader onto (or past) the current
    # base; `deltas` carries the contiguous tail above whichever position the
    # reader now has (empty when only a snapshot is delivered with nothing
    # above it yet). `next_cursor` is OPTIONAL — present if and only if a
    # snapshot currently exists (a deliberate divergence from `log`'s
    # "next_cursor ALWAYS present", D8 — see schema docstring): absent before
    # the current epoch's first `SnapshotPush` and on an immediate producer
    # reset response (the reset discards the snapshot), but present on a later
    # stale-epoch reset after fresh state arrives (PH0-D19/D20 — fixes review
    # F5-03's `next_cursor={seq:0}` reset contradiction). Every response path,
    # including a `SwmrTimerExpired` release, computes this through the same
    # canonical resolver — never a caller-supplied echo (56-F2). When present,
    # it contains the current node epoch and head. `reset_reason` is present
    # exactly when state=reset. `reset_detail` is present only when that reset
    # is producer-declared (an immediate held-read release or a later stale-
    # epoch read); engine-assigned retention/invalid-position resets leave it
    # absent. When one input releases several held reads, responses are emitted
    # in stream-creation order (D16).
    Msg("SwmrReadResponse",
        F("swmr_id", 1, STR),
        F("stream_id", 2, STR),
        F("snapshot", 3, Ref("SwmrSnapshot"), optional=True),
        F("deltas", 4, List(Ref("SwmrDelta"))),
        F("next_cursor", 5, Ref("SwmrCursor"), optional=True),
        F("state", 6, Ref("SwmrState")),
        F("reset_reason", 7, Ref("SwmrResetReason"), optional=True),
        F("error", 8, Ref("SwmrError"), optional=True),
        F("reset_detail", 9, BYTES, optional=True)),
    # Timer requests to the shell (D14). Tokens allocated monotonically from 1
    # (D16) so runs are deterministic.
    Msg("SwmrSetTimer",
        F("token", 1, INT),
        F("ms", 2, INT)),
    Msg("SwmrCancelTimer",
        F("token", 1, INT)),
    # Routed by the shell to the producer so it halts and releases state
    # (D6). Idempotent by design; shells that initiated the close ignore it.
    Msg("SwmrProducerStop",
        F("reason", 1, Ref("SwmrStopReason"))),
    # Engine diagnostics, delegated to the caller (D18).
    Msg("SwmrDiagnostic",
        F("severity", 1, Ref("SwmrSeverity")),
        F("code", 2, Ref("SwmrDiagCode"))),
)
