"""shape_log wire surface — the taut `log` delivery-shape vocabulary (D17).

Authored against `taut-shape/dev-docs/TautClientImplPlan.md` (§2 engine model,
§3 message vocabulary, §4 pinned decisions D1–D17). This is the *delivery
substrate* for any `shape="log"` method, not an app service: it carries opaque
app payloads (already taut-encoded) so the log engine stays payload-agnostic —
`LogRecord.payload` is the method's append-slot message, CBOR-encoded (the
glade `Op.payload` pattern; D17). Therefore it is modeled as messages +
codecs, NOT a `service` — taut generates the message types; the mailbox engine
(held reads, timers, sessions) and the In/Out unions are hand-written per
`taut-shape-<lang>` (D1).

Read whole. Three layers:
  1. core types — LogCursor, LogRecord, LogError (+ enums)
  2. node inputs — LogPush/LogSeal/LogClose (producer, node-local in v0),
     LogReadRequest/LogEndStream (stream-side, addressed by stream_id),
     LogTimerExpired/LogEvict (environment)
  3. node outputs — LogReadResponse (addressed), LogSetTimer/LogCancelTimer,
     LogProducerStop

Identity (D3/D4): `log_id` is the opaque log handle (service-level routing);
`stream_id` names one stream instance — one logical read loop with ≤1
outstanding read (D5); clients/connections are an adapter concern and never
appear here. Position lives in the client-held cursor: reads are cursor-in /
cursor-out (D8: first record seq=1, START = seq 0), so streams are disposable.

The engine consuming these messages is a pure mailbox (D1): no I/O, no clock —
timers ride LogSetTimer/LogTimerExpired (D14); teardown consequences ride
LogProducerStop (D6). The oracle corpus (`TautShapeOracle.md`) is expressed as
sequences of exactly these messages in taut jsoncodec form.

Regenerate (from taut-dev/taut-shape):
  PYTHONPATH=../taut/src python3 -m taut.cli gen ir/shape_log.taut.py \
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
    # LogMsgType is the mailbox type-tag registry: framing (the conformance
    # tool's `[tag][CBOR]` data channel) and the hand-written In/Out unions
    # discriminate on it. Not a union message — the discriminator is a
    # transport/dispatch detail, the codecs are per-message (glade FrameType
    # precedent).
    Enum("LogMsgType",
         push=0, seal=1, close=2,
         read=3, end_stream=4,
         timer_expired=5, evict=6,
         read_response=7, set_timer=8, cancel_timer=9,
         producer_stop=10),
    # The six read outcomes (D12/D13). `expired` is a state, never an error
    # (D9). Terminal states describe the LOG, not the stream: a re-read below
    # head still returns data while retained.
    Enum("LogState",
         data=0, would_block=1, eof=2, closed=3, failed=4, expired=5),
    # unknown_log is service-level (log_id routing); the node engine itself
    # only attaches producer_error/internal to `failed` responses. There is no
    # `canceled`: client-initiated cancellation is LogEndStream, which needs
    # no response.
    Enum("LogErrorCode",
         unknown_log=0, producer_error=1, internal=2),
    # Why the producer was told to stop (D6): the last stream ended (under
    # stop_when=last_reader), or the log was torn down.
    Enum("LogStopReason",
         last_reader_gone=0, closed=1, failed=2),

    # ---- core types ----------------------------------------------------------
    # An ordered position in one single-origin log: records strictly after
    # `seq` are unseen. First record is seq=1; START = seq 0 (D8). A named
    # message (not a bare int) so it can grow byte_offset for partial-record
    # delivery without a breaking change.
    Msg("LogCursor",
        F("seq", 1, INT)),
    # One append. `payload` is the method's append-slot message, already
    # taut-encoded — opaque, NUL-safe at this layer (D11, D17). The consuming
    # method's `out=` binding declares what it decodes to.
    Msg("LogRecord",
        F("seq", 1, INT),
        F("payload", 2, BYTES)),
    # Attached to `failed` responses (D12) and carried by LogClose.
    Msg("LogError",
        F("code", 1, Ref("LogErrorCode")),
        F("message", 2, STR, optional=True)),

    # ---- node inputs: producer side (node-local in v0) ----------------------
    # Append one record: the engine assigns seq := head+1 and answers any held
    # reads (D1).
    Msg("LogPush",
        F("payload", 1, BYTES)),
    # Mark the finite log complete; drained readers then see `eof`. Idempotent.
    Msg("LogSeal"),
    # Teardown. error absent => readers see `closed`; present => `failed` with
    # the error attached (D12). Emits LogProducerStop. Idempotent.
    Msg("LogClose",
        F("error", 1, Ref("LogError"), optional=True)),

    # ---- node inputs: stream side (addressed by stream_id) ------------------
    # One read on one stream instance. cursor absent = START (D8). First use of
    # a stream_id implicitly creates the stream (D4); a read on a stream with a
    # held read supersedes it (D5). timeout_ms: absent = hold until data/seal/
    # close/end_stream; 0 = immediate would_block probe; >0 = hold + timer
    # (D14). max_bytes counts raw payload bytes only, with the ≥1-record
    # forward-progress guarantee (D10).
    Msg("LogReadRequest",
        F("log_id", 1, STR),
        F("stream_id", 2, STR),
        F("cursor", 3, Ref("LogCursor"), optional=True),
        F("max_records", 4, INT, optional=True),
        F("max_bytes", 5, INT, optional=True),
        F("timeout_ms", 6, INT, optional=True)),
    # End one stream instance: drops its held read (no response), cancels its
    # timer, removes its watermark; reader-count ≥1→0 may emit LogProducerStop
    # (D4/D6). Adapters inject this on transport death — it IS the disconnect
    # cleanup. Unknown stream_id = no-op.
    Msg("LogEndStream",
        F("log_id", 1, STR),
        F("stream_id", 2, STR)),

    # ---- node inputs: environment -------------------------------------------
    # The shell's clock answering LogSetTimer. Late/canceled tokens are
    # ignored (no-op).
    Msg("LogTimerExpired",
        F("token", 1, INT)),
    # Consumer-driven retention (D7): drop records with seq <= up_to_seq,
    # raising the floor. Reads below the floor then resolve `expired` (D9).
    Msg("LogEvict",
        F("up_to_seq", 1, INT)),

    # ---- node outputs --------------------------------------------------------
    # The answer to one LogReadRequest (or its held release). next_cursor is
    # ALWAYS present, even when records is empty; on `expired` it is the
    # earliest resumable position (D9). error is attached when state=failed.
    # When one input releases several held reads, responses are emitted in
    # stream-creation order (D16).
    Msg("LogReadResponse",
        F("log_id", 1, STR),
        F("stream_id", 2, STR),
        F("records", 3, List(Ref("LogRecord"))),
        F("next_cursor", 4, Ref("LogCursor")),
        F("state", 5, Ref("LogState")),
        F("error", 6, Ref("LogError"), optional=True)),
    # Timer requests to the shell (D14). Tokens are allocated monotonically
    # from 1 (D16) so runs are deterministic.
    Msg("LogSetTimer",
        F("token", 1, INT),
        F("ms", 2, INT)),
    Msg("LogCancelTimer",
        F("token", 1, INT)),
    # Routed by the shell to the producer so a lazy/cold render halts and
    # releases state (pager-quit / broken pipe / disconnect). Idempotent by
    # design; shells that initiated the close ignore it (D6).
    Msg("LogProducerStop",
        F("reason", 1, Ref("LogStopReason"))),
)
