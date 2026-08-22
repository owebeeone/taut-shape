# The Taut Shape Behavioral Oracle

Status: design (draft, aligned with `TautClientImplPlan.md` v2 / D1–D23).
Scope: the conformance contract — corpus format, vector catalog, generation,
lockstep, and the interop matrix. Home: this repo (`taut-shape`) owns the
committed corpus; every `taut-shape-<lang>` pins and gates on it.

The rule this document enforces: **the reference code is optional; the oracle is
mandatory.** A client may use a `taut-shape-<lang>` library or reimplement the
engine — either way it must reproduce these vectors. That is what stops the
drift already exhibited by the three pre-existing hand-rolled log readers
(gwz-py's `wait_events` poll loop, glade's subscribe/backfill, taut's reference
JSON envelope).

---

## 1. Two conformance dimensions

taut already owns **codec byte-parity**: the golden corpus proves every language
encodes each message to identical CBOR bytes (`gwz-core/protocol/corpus/`,
`taut/corpus/glade.golden.json`).

This oracle owns the second dimension, which taut does not generate today:
**behavioral parity** — given the same input *message sequence*, every engine
emits the same output *message sequence*. Because the engine is a pure mailbox
(D1), behavior is exactly this function; the oracle can therefore be total.

## 2. Prior art (what this generalizes)

The pattern is proven in-tree; we are extending a convention, not inventing one:

- **`taut/corpus/glade_folds.json`** — reference fold results generated from the
  Python reference (`taut.crdt.glade_fold`), reproduced by the Rust node and the
  pure-TS client. `test_glade_folds.py` states the intent verbatim: *"the
  reference folds are the cross-language oracle: the Rust node (P1) and TS
  client (P2) must reproduce these results."* Its
  `test_committed_oracle_in_lockstep_with_reference()` is the lockstep-gate
  pattern §6 copies.
- **`taut/corpus/glade_hashes.json`** — the op-hash oracle
  (`sha256(canonical_cbor(op))`), reproduced byte-for-byte by TS
  (`client-ts/test/oracle.test.ts`).
- **`taut/src/tests/test_kotlin.py`** (and the cpp/go/java/js siblings) — the
  subprocess convention §7 adopts: a Python driver builds and spawns a
  per-language tool and asserts on structured output
  (`corpus_mismatches=0`, `fuzz_mismatches=0`).
- **glade itself is the two-implementation precedent**: one contract (frozen
  `glade.taut.py` wire + corpus), implemented independently in Rust
  (`glade/node`) and pure TS (`glade/client-ts`), kept honest by the corpora —
  exactly the multi-repo shape `taut-shape-<lang>` scales to N languages. And
  glade's `echo.rs` (`handle(&Frame) -> Vec<Frame>`, pure, exactly-once close)
  is the mailbox-engine shape (D1) in miniature.

What none of the prior corpora cover — and this oracle adds — is *live interop*:
the existing tests prove each language agrees with the spec alone; the matrix
(§7) proves language A's running node actually serves language B's running
client over a real byte channel.

## 3. Corpus format

One JSON file per shape+version, committed under `taut-shape/corpus/`:
`corpus/log.v0.json`.

```jsonc
{
  "shape": "log",
  "version": "log.oracle/v0",          // the pin every taut-shape-<lang> asserts
  "vectors": [
    {
      "name": "push_then_read_data",
      "comment": "basic append then catch-up read",
      "node": { "stop_when": "last_reader" },   // engine construction knobs (D6)
      "steps": [
        { "in":  { "type": "push", "payload": "aGVsbG8=" },
          "out": [] },
        { "in":  { "type": "read", "stream_id": "s1", "cursor": { "seq": "0" },
                   "max_records": "10", "timeout_ms": "0" },
          "out": [ { "type": "response", "stream_id": "s1",
                     "records": [ { "seq": "1", "payload": "aGVsbG8=" } ],
                     "next_cursor": { "seq": "1" }, "state": "data" } ] }
      ]
    }
  ]
}
```

Conventions:
- **A step is one input message + the exact ordered list of outputs it causes.**
  Nothing is asynchronous, nothing is timed — the engine is pure, so the pairing
  is total and deterministic (D16: timer tokens allocated 1,2,3…; multi-response
  emission in stream-creation order).
- Messages are JSON objects: the **taut jsoncodec form** of the `shape_log`
  schema messages (D17) plus a `type` discriminator. Per proto3-JSON
  conventions that means bytes are **base64** and i64s are strings — produced
  and consumed by taut's existing jsoncodec in every language, so **no bespoke
  corpus serializer exists anywhere** (NUL bytes and binary stay exact through
  base64). The mild human-readability cost was accepted for that.
- `cursor`/`next_cursor` are `LogCursor` objects (`{"seq": "0"}`); the CBOR
  wire encoding of all these messages is covered by taut's byte-parity corpus,
  not this one.
- Optional fields: taut's canonical native form materializes absent optionals
  as `null`/`None` (verified against the real codec). Authored vectors MAY omit
  them; conformance compares **decoded values** (each side normalized through
  the jsoncodec), never raw JSON text — so absent == null by construction.
- The conformance comparison is **whole-output equality** on the observed step
  transcript — never per-field assertions (the house golden style).
- **Diagnostics are code-only** (`LogDiagnostic{severity, code}` — D18): the
  vectors carry the machine-readable `code`, never free text. This is what keeps
  the oracle byte-stable across languages — because comparison is whole-output
  equality, any prose companion would freeze byte-identical strings into the
  oracle and every shell would have to reproduce them verbatim. Shells localize
  the code to human text at their logging edge; the oracle pins only the code.

## 4. Vector catalog (log v0)

Each pinned rule (D-number) gets at least one vector. The initial set:

**Basics**
1. `push_then_read_data` — append, catch-up read (D8: first record seq=1).
2. `read_empty_probe` — `timeout_ms=0` on an empty log → `would_block`,
   `next_cursor=0` (D8, D14).
3. `resume_no_dup_no_skip` — read half with `max_records`, resume from
   `next_cursor`, records 1..N appear exactly once (D8, D11).
4. `batch_bounds` — `max_records` and `max_bytes` boundaries; `max_bytes`
   counts payload bytes only (D10).
5. `forward_progress` — single record larger than `max_bytes` is still
   returned alone (D10).

**Hold / tail (held reads are engine state — D1)**
6. `held_read_released_by_push` — `read` with no `timeout_ms` on a caught-up
   log emits nothing; a later `push` emits the response.
7. `held_read_timer` — `read` with `timeout_ms=50` emits `SetTimer{1,50}`;
   `timer_expired{1}` answers `would_block` (D14, D16).
8. `late_timer_ignored` — `timer_expired` for a canceled/answered token emits
   nothing.
9. `supersede` — second `read` on the same stream drops the held first
   (unanswered) and emits `CancelTimer` for its timer (D5).

**Lifecycle (D12)**
10. `seal_then_drain_eof` — records then `seal`; a drained reader gets `eof`;
    held reads are answered `eof` by `seal` itself.
11. `close_clean` — `close{}` answers held reads `closed` and emits
    `ProducerStop{closed}`.
12. `close_failed` — `close{error}` answers held reads `failed` with the error
    attached and emits `ProducerStop{failed}`.
13. `terminal_still_readable` — after `seal`, a fresh cursor below head still
    reads `data` before `eof` (terminal describes the log, not the stream).
14. `idempotent_seal_close` — repeated `seal`/`close` emit nothing new.

**Retention / expiry (D7, D9)**
15. `evict_then_expired` — `evict{up_to}`, then a read below the floor →
    `expired` with `next_cursor = floor−1`; continuing from there yields the
    retained tail.
16. `beyond_head_expired` — cursor past head → `expired` with
    `next_cursor = head`.
24. `evict_beyond_head_clamps` — `evict{up_to_seq}` far past head clamps to
    `head` (D20: `floor ≤ head + 1` invariant), so evicting past head cannot
    manufacture positions that never existed. After the clamp `floor = head + 1`,
    hence `floor − 1 == head`: a below-floor read → `expired` with
    `next_cursor = {floor − 1} = {head}`, and a read **at** head then
    holds/probes normally (`would_block` on a `timeout_ms=0` probe,
    `next_cursor = head`) — D20, D9, D14.

**Multi-stream (D3–D6 — the backing-store / response-handler split)**
17. `two_streams_two_positions` — s1 and s2 read the same log at different
    cursors; each gets its own addressed responses.
18. `one_push_wakes_two` — s1 and s2 both held; one `push` emits two responses
    in stream-creation order (D16).
19. `end_stream_mid_hold` — `end_stream{s1}` drops s1's held read (no
    response), cancels its timer; s2 is untouched.
20. `last_stream_producer_stop` — with `stop_when=last_reader`: s1 and s2 end →
    `ProducerStop{last_reader_gone}` exactly on the ≥1→0 transition; variant
    with a never-read log emits nothing (D6).
21. `stop_when_explicit_only` — same script, knob off → no `ProducerStop` until
    `close`.

**Diagnostics (D18/D19 — `push_after_terminal`)**
22. `push_after_seal_warns` — `seal`, then a `push`: the record is dropped
    (nothing appended, head unchanged), the step emits exactly one
    `LogDiagnostic{warn, push_after_terminal}`, and a subsequent read still sees
    only the pre-seal records (the late push left no trace). N late pushes emit N
    diagnostics, one per push (D18/D19).
23. `push_after_close_warns` — `close{}` (or `close{error}`), then a `push`:
    same shape as 22 — dropped, one `LogDiagnostic{warn, push_after_terminal}`
    per late push, head unchanged, subsequent reads unaffected (the terminal
    state and any error stay as `close` set them — D18/D19).

## 4b. The `value` shape (lww register) — vector catalog (value v0)

The `value` shape (`ir/shape_value.taut.py`) is glade's `value` fold extracted
to its own contract: a *set* of attributed whole-value writes (`ValueSet`) folds
to a single winner — `max` by `(lamport, origin, seq)`, dedup by `(origin, seq)`, a
forked `(origin, seq)` is equivocation (`taut.crdt.glade_fold.fold_value`).
Reads are immediate probes (`ValueReadRequest` → `ValueReadResponse{value?,
winner?, state}`); there are no held reads, timers, or lifecycle in v0 (those are
`shape_log` / later shapes). MV is deferred (GQ-1 sidestep): single winner only.
Corpus `corpus/value.v0.json`, `version "value.oracle/v0"`; same step format as
log-v0 minus the `node` knob (the register has no construction options).

1. `set_then_read` — one `set`, then read → `data` with the payload + winner
   stamp.
2. `read_empty` — read before any set folds the empty set → `empty` (no
   value/winner).
3. `concurrent_lamport` — two writers; higher lamport wins.
4. `tiebreak_origin` — lamport tie → origin breaks it (`"b" > "a"`).
5. `out_of_order` — arrival order irrelevant; same winner.
6. `overwrite_same_origin` — a later write by the same origin (higher lamport)
   supersedes its earlier one.
7. `duplicate_idempotent` — exact re-sends by `(origin, seq)` are dropped, no
   diagnostic; winner unchanged.
8. `read_reflects_latest` — the register is live: read, set, read shows the
   winner advancing.
9. `equivocation_rejected` — a forked `(origin, seq)` with a different payload →
   exactly one `ValueDiagnostic{error, equivocation}`, register unchanged.
10. `equivocation_prev_mismatch` — same `(origin, seq)` and payload but a
    different `prev` is still a forked chain → equivocation, register unchanged.
11. `two_reads_two_streams` — two reads on different stream ids each get their
    own addressed response.
12. `tiebreak_seq` — if one origin reuses a Lamport value, higher `seq` wins.
13. `tiebreak_seq_out_of_order` — that fallback is arrival-order independent.

## 4c. The fold oracle (glade's M-LIMP folds, re-homed) — vector catalog

`corpus/fold.v0.json` (`version "fold.oracle/v0"`) re-homes glade's frozen fold
oracle (`taut/corpus/glade_folds.json`, §2 prior art) so taut-shape owns the
canonical fold semantics (consolidation plan P2.S1). It is the pure
`(op-set) → folded state` layer *beneath* the message-level shape corpora: raw
attributed ops in (`origin/seq/lamport/prev/payload`, **hex** payloads — glade's
convention, no jsoncodec/base64 round-trip because the fold works on the raw op
envelope, not schema messages), folded state out. 13 vectors, three folds
(reference: `taut.crdt.glade_fold`):

- **`value`** (lww, winner = max by `(lamport, origin, seq)`): `value/single`,
  `value/concurrent-lamport`, `value/tiebreak-origin`, `value/out-of-order`,
  `value/tiebreak-seq`, `value/duplicate`, `value/empty`.
- **`log`** (append, order by `(lamport, origin, seq)`): `log/order`,
  `log/tiebreak-origin`, `log/out-of-order`, `log/duplicate`.
- **`equiv`** (forked `(origin, seq)` detection): `equiv/forked`, `equiv/clean`.

The `value`/`equiv` rows are the same semantics as §4b at raw-fold granularity
(re-homed, not new coverage — the `corpus/README.md` mapping ties each to its
`value.v0.json` vector). The `log` rows are new: `log.v0.json` (§4) is the
`shape_log` *behavioral* corpus and never exercises the pure causal-interleave
fold. Its generator (`corpus/fold_gen.py --check`) doubles as a **conflict guard**
against glade's frozen oracle (fails loud if any glade vector's `(ops, expect)`
diverges — a design event, not a stale-file nit).

## 4d. The `atom` shape (replace-only latest state) — vector catalog (atom v1)

The `atom` shape (`ir/shape_atom.taut.py`) is `log` degenerated to window=1
(`TautShapeRoadmap.md` §1): a single slot, `replace`-only, a `version` change
counter instead of a `seq` position, no floor/expiry/max_records/max_bytes.
Corpus `corpus/atom.v1.json`, `version "atom.oracle/v1"`; same step format as
log-v0 (a `node` knob for `stop_when`, D6). Every decision the roadmap sketch
left open (naming, the terminal-guard on `AtomReplace`, the clamp on
`version > current`) is recorded in `dev-docs/AtomSwmrNotes.md`. Bumped from
`v0` (2026-07-19, PH0 review remediation, see `dev-docs/AtomSwmrNotes.md`):
`AtomTimerExpired` normalizes `next_version` through the canonical resolver
instead of echoing the originally requested version (56-F2), and a
timer-backed held read released for any reason other than `TimerExpired`
cancels its timer first (56-F4).

1. `read_empty_probe` — `timeout_ms=0` on an atom with no value yet ->
   `would_block`, `next_version=0`.
2. `replace_then_read_data` — initial delivery: one replace then a catch-up
   read; first `version=1`.
3. `replacement_overwrites` — a second replace OVERWRITES the slot (no
   back-history); a read sees only the latest.
4. `generation_change_replace` — a consumer-level "generation change" is an
   ORDINARY replace at the taut-shape layer (no generation concept in this
   shape; `dev-docs/AtomSwmrNotes.md` #4).
5. `subscriber_join_mid_stream` — a fresh stream's first read gets the LATEST
   value, never the first one.
6. `held_read_released_by_replace` — a read with no timeout on a caught-up
   atom holds; a later replace releases it.
7. `held_read_timer` — `timeout_ms=50` emits `SetTimer`; `timer_expired`
   answers `would_block`.
8. `late_timer_ignored` — a token already answered (here, by a replace) is a
   no-op on a later `timer_expired`.
9. `supersede` — a second read on the same stream drops the held first and
   cancels its timer.
10. `seal_then_drain_eof` — a value then seal; a caught-up reader gets `eof`.
11. `close_clean` / 12. `close_failed` — teardown answers held reads
    `closed`/`failed` and emits `ProducerStop`.
13. `terminal_still_readable` — after seal, a read below current version
    still reads `data` (no floor to evict past).
14. `idempotent_seal_close` — repeated seal/close emit nothing new.
15. `two_streams_two_positions` / 16. `one_replace_wakes_two` — multi-stream
    addressing and creation-order multi-emission.
17. `end_stream_mid_hold` / 18. `last_stream_producer_stop` /
    19. `stop_when_explicit_only` — the D4/D6 reader-count lifecycle.
20. `replace_after_seal_warns` / 21. `replace_after_close_warns` — a late
    replace is dropped and warns exactly once (D18/D19 analogue).
22. `beyond_current_probe` — an immediate `timeout_ms=0` read naming a
    `version` beyond current clamps to current, never a new state (56-F2).
23. `beyond_current_timed_expiry` — the timed variant of #22: `timer_expired`
    answers with the clamped current version, never the originally requested
    one (the defect 56-F2 identified and this pins the fix for).
24. `never_read_no_stop` — the never-read variant of #18 (log 20b parity,
    review F5-06c): `end_stream` on an atom with no streams ever created
    never spuriously stops the producer.
25. `post_close_end_stream_double_stop` — a later `end_stream` on the last
    stream after `close` still transitions reader-count ≥1→0 and emits a
    second `ProducerStop` (idempotent by design, D6; review F5 §8.9).
26. `timed_early_wake_replace` / 27. `timed_seal_cancels_timer` /
    28. `timed_close_cancels_timer` — a timer-backed held read released early
    by `replace`/`seal`/`close` cancels its timer immediately before its
    response (56-F4).

## 4e. The `stream` shape (bounded disposable delivery) — vector catalog (stream v1)

`stream` is the bounded, lossy ordered engine frozen in
`TautShapeStreamDecision.md`. Readers have node-owned positions, first read
joins at the current head, and a reader behind the retained floor receives
`dropped` and is removed. Corpus `corpus/stream.v1.json`, version
`stream.oracle/v1`; node knobs are `capacity_records` and `stop_when`.

1. `read_empty_probe` and 2. `late_join_skips_backlog` pin empty/live-only join.
3. `held_read_released_by_push` and 4. `live_two_records` pin normal live flow.
5. `batch_records` and 6. `byte_bound_forward_progress` pin read bounds.
7. `slow_reader_dropped`, 8. `fast_reader_survives_slow_drop`, and
   9. `late_join_after_overflow` pin bounded-memory loss and reader isolation.
10. `one_push_wakes_two` pins creation-order multi-reader wake-up.
11. `held_read_timer`, 12. `timer_expiry`, 13. `late_timer_ignored`, and
    14. `supersede` pin deterministic Sans-I/O timers.
15. `seal_releases_held`, 16. `terminal_drain`, 17. `close_clean`,
    18. `close_failed`, 19. `terminal_still_readable`, and
    20. `idempotent_terminal` pin lifecycle and data-before-terminal behavior.
21. `end_stream_mid_hold`, 22. `last_reader_stop`, and 23. `explicit_only` pin
    teardown and producer-stop policy.
24. `push_after_seal`, 25. `push_after_close`, and 26. `never_read_close` pin
    terminal diagnostics and never-read close behavior.
27. `timed_push_cancels` pins cancel-before-wake ordering.
28. `dropped_reconnect_is_late_join` pins the intentional lack of resume,
    including reuse of a previously dropped stream id.

## 4f. The `swmr` shape (snapshot + delta + typed reset) — vector catalog (swmr v1)

The `swmr` shape (`ir/shape_swmr.taut.py`) is a snapshot + contiguous delta
window with typed, engine-repaired resets (`TautShapeRoadmap.md` §3). Corpus
`corpus/swmr.v1.json`, `version "swmr.oracle/v1"`; the `node` knob carries
`stop_when` (D6) plus an optional `max_deltas` retention bound (new, see
`dev-docs/AtomSwmrNotes.md` #10). A read response is one `SwmrReadResponse`
with optional `snapshot`, a `deltas` tail, and an optional `next_cursor`,
present if and only if a snapshot exists in the current epoch — absent before
one exists and on an immediate producer-reset response, but present on a later
stale-epoch reset once fresh state exists (a documented divergence from
`log`'s D8 "always present", `dev-docs/AtomSwmrNotes.md` #7/#8/#18). Cursors
are `(epoch, seq)`; sequence values are interpreted only within their epoch.
Bumped from `v0` (2026-07-19, PH0 review remediation, see
`dev-docs/AtomSwmrNotes.md`): `SwmrSnapshotPush` now resumes at the pre-push
base instead of consuming a delivery-sequence slot, so a caught-up reader
survives a compaction/re-basing push (PH0-D20/D24); every response path
computes `next_cursor` through the canonical resolver rather than an echoed
or hardcoded position (56-F2, F5-03); an absent-cursor held read is never
force-answered `reset` by a producer reset (F5-02); `SwmrReset.reason` is
normalized to `producer_requested` (F5-13); and a timer-backed held read
released for any reason other than `TimerExpired` cancels its timer first
(56-F4). Successful producer reset increments a durable node epoch and retains
the normalized reason plus opaque detail, so a reader between polls cannot
miss the reset even if the new epoch reuses the same sequence values.

1. `initial_snapshot` — one `snapshot_push` then a fresh read delivers the
   snapshot with an empty tail.
2. `delta_batches` — a snapshot then two deltas deliver as one contiguous
   tail in a fresh read.
3. `resume_retained_seq_success` — a caught-up reader is released by each new
   delta with ONLY the incremental tail (no dup, no skip, no re-sent
   snapshot).
4. `resume_expired_seq_reset` — a reader's cursor falls below a new snapshot's
   base (re-basing retired the old delta window) -> `state=reset,
   reason=retention_exceeded`, with a fresh snapshot+tail attached
   (engine-repaired in-band, the swmr analogue of `log`'s client-decided
   `expired`).
5. `generation_change_reset` — an explicit producer `SwmrReset` (e.g. the
   consumer's query generation changed, opaque to taut-shape, carried in
   `detail`) answers held reads immediately with `state=reset,
   reason=producer_requested`.
6. `two_readers_different_cursors` — independent addressed responses (an
   incremental resume vs. a fresh subscribe) over the same store.
7. `backpressure_retention_bound` — with `max_deltas=2`, a third `delta_push`
   is rejected (`SwmrDiagnostic{error, retention_bound_exceeded}`); the
   producer must `SnapshotPush` to continue.
8. `writer_uniqueness_violation` — a second `writer_id` on a producer input is
   rejected (`SwmrDiagnostic{error, writer_conflict}`), register unchanged —
   the wire-level enforcement of `writers="single"`.
9. `held_read_released_by_delta` / 10. `held_read_timer` /
   11. `late_timer_ignored` / 12. `supersede` — the D1/D5/D14/D16 held-read
    lifecycle, mirrored from `log`.
13. `seal_then_drain_eof` / 14. `close_clean` / 15. `close_failed` /
    16. `idempotent_seal_close` — teardown, mirrored from `log`'s D12/D6.
17. `end_stream_mid_hold` / 18. `last_stream_producer_stop` /
    19. `stop_when_explicit_only` — the D4/D6 reader-count lifecycle.
20. `push_after_seal_warns` — a late `snapshot_push`/`delta_push` is dropped
    and warns once each (D18/D19 analogue).
21. `terminal_still_readable` — after seal, a fresh subscribe still reads the
    retained snapshot+deltas as `data` before `eof`.
22. `delta_before_snapshot` — a `delta_push` before any snapshot exists is
    rejected (`SwmrDiagnostic{error, delta_before_snapshot}`).
23. `pre_snapshot_timed_cursor` — a timed read supplying a positioned cursor
    before any snapshot exists still holds (nothing to resolve against); the
    timed expiry answers with `next_cursor` ABSENT, never the supplied cursor
    echoed back (56-F2).
24. `invalid_resume_seq_after_snapshot` — a cursor past `head` after a
    snapshot exists → `state=reset, reason=invalid_resume_seq` (the enum
    branch existed but had no vector, review F5-06b).
25. `absent_cursor_hold_across_reset` — a held read whose original request
    had an absent cursor is NOT force-answered `reset` by a producer
    `SwmrReset` (there is nothing to have been reset FROM); it keeps holding
    and is later released normally by the next real snapshot (PH0-D19, fixes
    review F5-02).
26. `caught_up_survives_compaction_push` — a reader caught up at head does
    NOT get spuriously `reset` by a redundant/compacting `SnapshotPush`,
    because such a push no longer advances `head` (PH0-D20/D24, fixes the
    known cost `dev-docs/AtomSwmrNotes.md` #6 used to document).
27. `never_read_no_stop` — the never-read variant of #18 (log 20b parity,
    review F5-06c): `end_stream` on a swmr with no streams ever created
    never spuriously stops the producer.
28. `post_close_end_stream_double_stop` — a later `end_stream` on the last
    stream after `close` still transitions reader-count ≥1→0 and emits a
    second `ProducerStop` (idempotent by design, D6; review F5 §8.9).
29. `timed_early_wake_delta` / 30. `timed_seal_cancels_timer` /
    31. `timed_close_cancels_timer` / 32. `timed_reset_cancels_timer` — a
    timer-backed held read released early by `delta_push`/`seal`/`close`/
    `reset` cancels its timer immediately before its response (56-F4).
33. `reset_between_polls_epoch_overlap` — a reader at epoch 0/seq 1 is between
    polls while reset advances to epoch 1 and fresh state reuses seq 0..1; its
    next read must receive typed reset with the retained producer detail and
    fresh epoch-1 state/cursor, never `would_block` from sequence equality.

## 5. Generation

`taut-shape-rs` is the reference implementation for `shape_log`: its tool's
`gen` mode replays authored scripts through the reference engine and emits the
corpus JSON. For `shape_value` the reference is Python — `fold_value` in the taut
runtime — so `corpus/value_gen.py` replays `scripts_value/` through it directly
(self-contained, no per-language build); the register-shell glue asserts its
winner equals `fold_value(ops)`, keeping the fold the authority. The stateful
non-fold contracts use `corpus/atom_gen.py`, `corpus/stream_gen.py`, and
`corpus/swmr_gen.py`; each embeds a small hand-written reference mailbox engine
directly in the generator — a third
generation strategy, self-contained like `value_gen.py` but modeling a
stateful mailbox like `log`'s reference engine rather than importing a pure
function (`dev-docs/AtomSwmrNotes.md` #13). Either way the authored *inputs*
(scripts + construction knobs) live in this repo; `gen` fills in the expected
outputs; a human reviews the diff before committing (every expected output is
hand-reviewed once, the `glade_folds` discipline).

Open (carried from the architecture doc): whether `taut` later generates
script scaffolding from the shape IR. Not v0.

## 6. Lockstep (the corpus bump)

The corpus `version` string is the single cross-repo coordination point:
- Each `taut-shape-<lang>` pins the version it conforms to and asserts it in CI
  against the committed corpus (the `test_committed_oracle_in_lockstep_with_
  reference` pattern). Pin ≠ corpus → fail with "oracle out of date — bump pin."
- A semantic change ⇒ new version + regenerated corpus here, then per-language
  repos update their pin and conform. No co-location needed; the bump replaces it.

## 7. The interop matrix

The corpus proves each engine against the spec **alone**; the matrix proves them
against **each other**, live, over the real wire framing.

Every `taut-shape-<lang>` ships one CLI tool (shared plan §5) with modes
`gen | check | node | client`. The matrix driver (Python, in this repo) runs:

```
for X in {rs, ts, py}:            # the node side
  for Y in {rs, ts, py}:          # the client side (same-lang pairs are baselines)
    node(X)  <== pipes ==>  client(Y)
```

- **Data channel** (the wire under test): `u32-LE length + 1 tag byte + CBOR`
  frames of the taut companion messages (`LogReadRequest`/`LogEndStream` toward
  the node, `LogReadResponse` back) — client's stdout → node's stdin and vice
  versa, crossed pipes, drained concurrently by the driver. The `length` prefix
  counts the tag byte **plus** the CBOR body (min 1); the tag byte is the
  `LogMsgType` wire value (0..=11). This is the framing every `taut-shape-<lang>`
  tool implements (the `taut-shape-rs` node mode is the reference).
- **Control/result channel**: OOB JSONL on stderr — each tool emits its observed
  transcript (and the node consumes a `--script` file scripting the producer:
  push/seal/close interleaved against read counts, so runs are deterministic). The
  script is a JSON array of `{ "after_frames": k, "inputs": [<producer messages in
  taut jsoncodec form>] }` — after the *k*-th client frame is processed, `inputs`
  is injected in order and its outputs written too (`after_frames: 0` fires before
  any client frame). A `{ "steps": [ … ] }` object wrapper is also accepted so a
  script file can carry a `comment`. All three tools accept `--script` identically:
  in `node` mode the injected messages feed the local engine; in `client` mode they
  are written as frames toward the peer node (client-side producer injection).
- **Client transcript shape**: the `client` cursor loop logs one jsoncodec
  `read_response` object per received response, then a terminal
  `{ "type": "client_final", "state": <state> }` line on exit. It sends **held**
  `LogReadRequest`s (`timeout_ms` omitted) from `--from`, advancing to
  `next_cursor` on `data`/`would_block`/`expired` and terminating on
  `eof`/`closed`/`failed`. Because the node writes *every* engine output as a
  frame, the client tolerates control frames on the response channel: a
  `producer_stop` frame is terminal (`state: "producer_stop"`), while
  `set_timer`/`cancel_timer`/`diagnostic` frames are informational and skipped
  (no re-send). A clean EOF before any terminal answer is treated as `eof`, exit 0.
- The driver compares both transcripts against the scenario's expectation —
  whole-output golden, spawned subprocess-style per `test_kotlin.py`.

Timer caveat: interop scenarios avoid `timeout_ms > 0` (real clocks are
nondeterministic across processes); timer behavior is corpus-only, where
`TimerExpired` is a scripted input.

## 8. What the oracle does NOT cover

- Shell behavior (pump loops, streaming sugar, cancellation mapping) — each
  language tests its own shell; the engine underneath is what conformance pins.
- Real timers, real transports, real producers — adapters' concerns.
- Codec byte-parity — taut's existing corpus owns it.
- The service layer beyond `unknown_log` routing (thin by design).

## 9. Repo layout (this repo)

```
taut-shape/
├─ dev-docs/            # TautShapeArchitecture.md, TautClientImplPlan.md, this file
├─ corpus/
│  ├─ log.v0.json       # committed log oracle (generated by taut-shape-rs `gen`)
│  ├─ scripts/          # authored log input scripts + node knobs (gen inputs)
│  ├─ value.v0.json     # committed value oracle (value_gen.py, Python fold ref)
│  ├─ scripts_value/    # authored value input scripts
│  ├─ atom.v1.json      # committed atom oracle (atom_gen.py, reference AtomNode)
│  ├─ scripts_atom/     # authored atom input scripts
│  ├─ stream.v1.json    # committed stream oracle (stream_gen.py, reference StreamNode)
│  ├─ scripts_stream/   # authored stream input scripts
│  ├─ swmr.v1.json      # committed swmr oracle (swmr_gen.py, reference SwmrNode)
│  ├─ scripts_swmr/     # authored swmr input scripts
│  ├─ fold.v0.json      # re-homed fold oracle (fold_gen.py; glade's M-LIMP folds)
│  └─ scripts_fold/     # authored fold input scripts (raw ops, hex payloads)
├─ matrix/
│  ├─ driver.py         # the interop matrix runner (pytest)
│  └─ scenarios/        # deterministic node/client interop scenarios
└─ README.md
```
