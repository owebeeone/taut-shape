"""shape_atom wire surface — the taut `atom` delivery-shape vocabulary.

Authored against `taut-shape/dev-docs/TautShapeRoadmap.md` §1 (the atom
sketch, the design of record) and modeled precisely on `shape_log.taut.py`'s
idiom (D1-D20 in `TautClientImplPlan.md` carry over almost unchanged — see the
roadmap's §1.3 verdict: "atom is a strict simplification of `log` ... a
degenerate log with window=1"). Like `shape_log`/`shape_value` this is the
*delivery substrate* for any `shape="atom"` method, not an app service:
`AtomValue.payload` carries the method's whole-state message already
taut-encoded (opaque, NUL-safe — the glade `Op.payload` pattern), so the
engine stays payload-agnostic. Modeled as messages + codecs, NOT a `service`:
taut generates the message types; the mailbox engine (held reads, timers) and
the In/Out unions are hand-written per `taut-shape-<lang>` (D1, D17, D21, D22).

Read whole. Three layers:
  1. core types — AtomVersion, AtomValue, AtomError (+ enums)
  2. node inputs — AtomReplace/AtomSeal/AtomClose (producer, node-local in v0),
     AtomReadRequest/AtomEndStream (stream-side, addressed by stream_id),
     AtomTimerExpired (environment)
  3. node outputs — AtomReadResponse (addressed), AtomSetTimer/AtomCancelTimer,
     AtomProducerStop, AtomDiagnostic

Identity (D3/D4, unchanged from `log`): `atom_id` is the opaque atom handle
(service-level routing); `stream_id` names one stream instance — one logical
read loop with ≤1 outstanding read (D5). Position is a `version` (a change
counter), NOT a `seq` (a byte position, roadmap §1.2): a `replace` OVERWRITES
the single slot rather than appending, so there is no back-history to resume
into — a late reader gets the latest value and then tails changes. `version`
starts at 0 (no value yet, the atom analogue of log's `START = seq 0`, D8);
the first `replace` advances it to 1.

Dropped relative to `log` (roadmap §1.2, "a strict simplification"): there is
no window, so `max_records`/`max_bytes` are meaningless (a single record and
backpressure has nothing to bound), and `expired` cannot arise (there is no
floor to fall below — the one stored value is always retained, `Evict` does
not exist for this shape). Terminal states remain re-readable exactly as in
`log` (D12 rule 4 analogue): a read below the current version always answers
`data` regardless of sealed/closed/failed, because there is no eviction to
make the single retained value unavailable.

The engine consuming these messages is a pure mailbox (D1): no I/O, no clock —
timers ride AtomSetTimer/AtomTimerExpired (D14); teardown consequences ride
AtomProducerStop (D6). The oracle corpus (`TautShapeOracle.md`) is expressed as
sequences of exactly these messages in taut jsoncodec form.

Atom is normatively single-writer, but v1 keeps producer inputs node-local and
does not add a `writer_id` field. The shell/adapter that binds a producer to an
Atom node MUST enforce exactly one producer binding and reject a second binding
before either producer can send `AtomReplace`/`AtomSeal`/`AtomClose`. The mailbox
cannot detect that violation after binding because its producer messages carry
no identity. This is an adapter conformance obligation, not an implication left
unenforced; see `dev-docs/AtomSwmrNotes.md`.

See `dev-docs/AtomSwmrNotes.md` for every place this schema had to make a
decision the roadmap sketch left open (naming, the terminal-guard on
`AtomReplace`, the clamp on `version > current`), and for the deliberate
divergence recorded there: `atom_id` is added to `AtomReadRequest`/
`AtomReadResponse` for identity-model parity with `log`/`value`, even though
the roadmap's vocabulary sketch table did not list it explicitly.

Regenerate (from taut-dev/taut-shape):
  PYTHONPATH=../taut/src python3 -m taut.cli gen ir/shape_atom.taut.py \
      -o <out> -l python,typescript,rust --api-only
"""

import sys
from pathlib import Path

# Make the taut builder importable when this file is loaded by path
# (taut is a sibling member of the taut-dev workspace).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "taut" / "src"))

from taut.ir.dsl import BYTES, INT, STR, Enum, F, Msg, Ref, schema

SCHEMA = schema(
    # ---- enums -------------------------------------------------------------
    # AtomMsgType is the mailbox type-tag registry (D21/D22): framing and the
    # hand-written In/Out unions discriminate on it, mirroring LogMsgType.
    Enum("AtomMsgType",
         replace=0, seal=1, close=2,
         read=3, end_stream=4,
         timer_expired=5,
         read_response=6, set_timer=7, cancel_timer=8,
         producer_stop=9, diagnostic=10),
    # Five read outcomes: no `expired` relative to `LogState` (roadmap §1.2 —
    # there is no floor, so an invalid/beyond-head version cannot arise; a
    # version past current is clamped to current, see AtomReadRequest).
    Enum("AtomState",
         data=0, would_block=1, eof=2, closed=3, failed=4),
    # unknown_atom is service-level (atom_id routing), mirrors LogErrorCode.
    Enum("AtomErrorCode",
         unknown_atom=0, producer_error=1, internal=2),
    # Why the producer was told to stop (D6), mirrors LogStopReason exactly.
    Enum("AtomStopReason",
         last_reader_gone=0, closed=1, failed=2),
    # Severity of an engine diagnostic (D18), mirrors LogSeverity.
    Enum("AtomSeverity", warn=0, error=1),
    # Machine-readable diagnostic codes (D18); open for growth, no free-text
    # companion (the oracle compares whole outputs — D18's rationale carries
    # over verbatim). `replace_after_terminal` is the atom analogue of `log`'s
    # `push_after_terminal` (D19): a `replace` after seal/close is dropped.
    Enum("AtomDiagCode", replace_after_terminal=0),

    # ---- core types ----------------------------------------------------------
    # A change counter, NOT a byte position (roadmap §1.2: "version replaces
    # seq"). version=0 means "no value has ever been set" (the atom analogue
    # of log's START); the first `replace` advances it to 1. A named message
    # (not a bare int) for the same D8/D11 "can grow" reason as `LogCursor`.
    Msg("AtomVersion",
        F("version", 1, INT)),
    # The current whole state at `version`. `payload` is the method's
    # whole-state message, already taut-encoded — opaque, NUL-safe (D11/D17).
    Msg("AtomValue",
        F("version", 1, INT),
        F("payload", 2, BYTES)),
    # Attached to `failed` responses (D12) and carried by AtomClose.
    Msg("AtomError",
        F("code", 1, Ref("AtomErrorCode")),
        F("message", 2, STR, optional=True)),

    # ---- node inputs: producer side (node-local in v1) ----------------------
    # Atom is single-writer. These messages deliberately carry no writer_id:
    # the shell/adapter MUST bind exactly one producer and reject a second
    # binding before inputs reach this mailbox. See AtomSwmrNotes.md #17.
    # Overwrite the single slot: version := version+1, payload := this
    # payload. Answers any held reads (D1). A `replace` after seal/close is
    # dropped (nothing overwritten, version unchanged) and emits
    # AtomDiagnostic{warn, replace_after_terminal} (D18/D19 analogue).
    Msg("AtomReplace",
        F("payload", 1, BYTES)),
    # Mark the atom's producer finished; drained readers then see `eof`.
    # Idempotent. Sealing does not itself emit AtomProducerStop (mirrors
    # LogSeal exactly: only Close does).
    Msg("AtomSeal"),
    # Teardown. error absent => readers see `closed`; present => `failed` with
    # the error attached (D12). Emits AtomProducerStop. Idempotent (a repeat
    # Close on an already-closed atom emits nothing, D6).
    Msg("AtomClose",
        F("error", 1, Ref("AtomError"), optional=True)),

    # ---- node inputs: stream side (addressed by stream_id) ------------------
    # One read on one stream instance. version absent = 0 (no value seen yet,
    # D8 analogue). First use of a stream_id implicitly creates the stream
    # (D4); a read on a stream with a held read supersedes it (D5). No
    # `max_records`/`max_bytes` (roadmap §1.2 — a single value, backpressure is
    # meaningless). timeout_ms: absent = hold until replace/seal/close/
    # end_stream; 0 = immediate would_block probe; >0 = hold + timer (D14).
    Msg("AtomReadRequest",
        F("atom_id", 1, STR),
        F("stream_id", 2, STR),
        F("version", 3, Ref("AtomVersion"), optional=True),
        F("timeout_ms", 4, INT, optional=True)),
    # End one stream instance: drops its held read (no response), cancels its
    # timer; reader-count ≥1→0 may emit AtomProducerStop (D4/D6). Adapters
    # inject this on transport death. Unknown stream_id = no-op.
    Msg("AtomEndStream",
        F("atom_id", 1, STR),
        F("stream_id", 2, STR)),

    # ---- node inputs: environment -------------------------------------------
    # The shell's clock answering AtomSetTimer. Late/canceled tokens are
    # ignored (no-op).
    Msg("AtomTimerExpired",
        F("token", 1, INT)),

    # ---- node outputs --------------------------------------------------------
    # The answer to one AtomReadRequest (or its held release). `value` is
    # present exactly when state=data (one optional value, not a list — the
    # roadmap's §1.2 load-bearing difference from LogReadResponse.records[]).
    # `next_version` is ALWAYS present (the atom analogue of `next_cursor`),
    # clamped to the current version whenever a request named a `version`
    # beyond it (there is no floor/head distinction to misuse, unlike `log`).
    # Every response path — including the one answering an `AtomTimerExpired`
    # — computes it through the same canonical resolver in probe mode; none
    # of them re-emit a caller-supplied version verbatim (PH0-D19, fixes
    # review 56-F2's timed-expiry normalization defect). When one input
    # releases several held reads, responses are emitted in stream-creation
    # order (D16).
    Msg("AtomReadResponse",
        F("atom_id", 1, STR),
        F("stream_id", 2, STR),
        F("value", 3, Ref("AtomValue"), optional=True),
        F("next_version", 4, Ref("AtomVersion")),
        F("state", 5, Ref("AtomState")),
        F("error", 6, Ref("AtomError"), optional=True)),
    # Timer requests to the shell (D14). Tokens allocated monotonically from 1
    # (D16) so runs are deterministic.
    Msg("AtomSetTimer",
        F("token", 1, INT),
        F("ms", 2, INT)),
    Msg("AtomCancelTimer",
        F("token", 1, INT)),
    # Routed by the shell to the producer so it halts and releases state
    # (D6). Idempotent by design; shells that initiated the close ignore it.
    Msg("AtomProducerStop",
        F("reason", 1, Ref("AtomStopReason"))),
    # Engine diagnostics, delegated to the caller (D18). First use: a
    # `replace` after seal/close is dropped and warns (D19 analogue).
    Msg("AtomDiagnostic",
        F("severity", 1, Ref("AtomSeverity")),
        F("code", 2, Ref("AtomDiagCode"))),
)
