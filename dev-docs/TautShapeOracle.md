# The Taut Shape Behavioral Oracle

Status: design (draft, aligned with `TautClientImplPlan.md` v2 / D1–D16).
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

## 5. Generation

`taut-shape-rs` is the reference implementation: its tool's `gen` mode replays
authored scripts through the reference engine and emits the corpus JSON. The
authored *inputs* (scripts + construction knobs) live in this repo; `gen` fills
in the expected outputs; a human reviews the diff before committing (every
expected output is hand-reviewed once, the `glade_folds` discipline).

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

- **Data channel** (the wire under test): `u32-LE length + CBOR` frames of the
  taut companion messages (`LogReadRequest`/`LogEndStream` toward the node,
  `LogReadResponse` back) — client's stdout → node's stdin and vice versa,
  crossed pipes, drained concurrently by the driver.
- **Control/result channel**: OOB JSONL on stderr — each tool emits its observed
  transcript (and the node consumes a `--scenario` file scripting the producer:
  push/seal/close interleaved against read counts, so runs are deterministic).
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
│  ├─ log.v0.json       # committed oracle (generated by taut-shape-rs `gen`)
│  └─ scripts/          # authored input scripts + node knobs (the gen inputs)
├─ matrix/
│  ├─ driver.py         # the interop matrix runner (pytest)
│  └─ scenarios/        # deterministic node/client interop scenarios
└─ README.md
```
