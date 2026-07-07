"""shape_value wire surface — the taut `value` delivery-shape vocabulary.

The `value` shape is a **last-writer-wins register**: a *set* of attributed
whole-value writes folds to a single materialized winner. This is glade's `value`
fold extracted to its own contract home (`TautShapeGladeConsolidation.md` P1),
lifting the reference in `taut.crdt.glade_fold.fold_value` — winner = `max` by
`(lamport, origin)` (the GladeSubstrateV1 §2 tiebreak, the glade analogue of
taut ReferenceDoc's `(seq, actor)` lww stamp).

Like `shape_log` this is the *delivery substrate* for any `shape="value"`
method, not an app service: `ValueSet.payload` carries the method's whole-value
message already taut-encoded (opaque, NUL-safe — the glade `Op.payload` pattern),
so the engine stays payload-agnostic. It is therefore modeled as messages +
codecs, NOT a `service`: taut generates the message types; the fold engine
(op-set dedup, lww selection, equivocation rejection) and the In/Out unions are
hand-written per `taut-shape-<lang>`.

Read whole. Three layers:
  1. core types — ValueStamp (the lww provenance of a winner)
  2. node inputs — ValueSet (a whole-value write op), ValueReadRequest
     (addressed by value_id + stream_id)
  3. node outputs — ValueReadResponse (addressed), ValueDiagnostic

Semantics (from `fold_value`):
  * The register folds a SET of ops. Dedup by `(origin, seq)`: an exact re-send
    is idempotent (dropped, no output). A second op at an existing `(origin,
    seq)` with a DIFFERENT `payload`/`prev` is **equivocation** — a forked
    per-origin chain — rejected (never folded) and surfaced as a
    `ValueDiagnostic{error, equivocation}`; the register is unchanged.
  * A read is an immediate probe of the current winner (v0 has no held reads,
    no timers, no lifecycle — those are `shape_log` / later shapes). It answers
    `data` with the winning `payload` + `winner` stamp, or `empty` (no ops yet).
  * MV (multi-value / conflict surfacing) is DEFERRED (GQ-1 sidestep,
    GladeSubstrateV1 §11): v0 declares only the conflict-free single-winner
    fold. `ValueReadResponse.winner` is a single stamp; MV becomes an additive
    repeated field later, foreclosing nothing.

The engine consuming these messages is a pure fold (no I/O, no clock): outputs
are a deterministic, immediate function of the input op-set. The oracle corpus
(`TautShapeOracle.md`) is expressed as sequences of exactly these messages in
taut jsoncodec form and generated from the `fold_value` reference (Python —
`corpus/value_gen.py`), the `glade_folds` discipline.

Regenerate (from the taut-dev/gwz workspace root):
  PYTHONPATH=../taut/src python3 -m taut.cli gen ir/shape_value.taut.py \
      -o <out> -l python,typescript,rust --api-only
"""

import sys
from pathlib import Path

# Make the taut builder importable when this file is loaded by path
# (taut is a sibling member of the workspace).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "taut" / "src"))

from taut.ir.dsl import BYTES, INT, STR, Enum, F, Msg, Ref, schema

SCHEMA = schema(
    # ---- enums -------------------------------------------------------------
    # ValueMsgType is the mailbox type-tag registry: framing (the conformance
    # tool's `[tag][CBOR]` data channel) and the hand-written In/Out unions
    # discriminate on it. Not a union message — the discriminator is a
    # transport/dispatch detail, the codecs are per-message (the shape_log /
    # glade FrameType precedent).
    Enum("ValueMsgType",
         set=0, read=1,
         read_response=2, diagnostic=3),
    # A read outcome. `data` = the register has a winner; `empty` = no op has
    # been folded yet. There is no error/expiry state in v0: equivocation is a
    # diagnostic on the offending write, not a read outcome.
    Enum("ValueState",
         data=0, empty=1),
    # Severity of an engine diagnostic (mirrors shape_log's LogSeverity). v0
    # emits `error` for equivocation only.
    Enum("ValueSeverity", warn=0, error=1),
    # Machine-readable diagnostic codes; open for growth. Deliberately no
    # free-text companion (the behavioral oracle compares whole outputs, so any
    # prose would freeze byte-identical strings across every language — shells
    # map codes to text). `equivocation` = a forked per-origin chain: a second
    # write at an existing (origin, seq) with a different payload/prev.
    Enum("ValueDiagCode", equivocation=0),

    # ---- core types ----------------------------------------------------------
    # The provenance of the winning write: its (origin, seq, lamport). This is
    # the lww stamp `fold_value` maximizes over `(lamport, origin)`; `seq`
    # carries the per-origin position. Surfaced so the winner is legible and so
    # MV surfacing can grow additively (a repeated ValueStamp later).
    Msg("ValueStamp",
        F("origin", 1, STR),
        F("seq", 2, INT),
        F("lamport", 3, INT)),

    # ---- node inputs: producer side -----------------------------------------
    # One whole-value write op — the fold-relevant subset of the glade Op
    # envelope (glade owns the share/glade_id/key routing; the shape is
    # single-register + payload-agnostic, so ValueSet carries only what the
    # fold needs). `payload` is the method's whole-value message, already
    # taut-encoded (opaque, NUL-safe — the Op.payload pattern). `prev` is the
    # hash of this origin's predecessor write (per-origin chain integrity); it
    # participates in equivocation detection alongside `payload`.
    Msg("ValueSet",
        F("origin", 1, STR),
        F("seq", 2, INT),
        F("lamport", 3, INT),
        F("prev", 4, BYTES, optional=True),
        F("payload", 5, BYTES)),

    # ---- node inputs: read side (addressed) ---------------------------------
    # Probe the current winner. value_id names the register (service-level
    # routing); stream_id addresses the response back to one reader. v0 reads
    # are immediate — there is no held read and no timeout (whole-value only;
    # change subscription / deltas are a later shape).
    Msg("ValueReadRequest",
        F("value_id", 1, STR),
        F("stream_id", 2, STR)),

    # ---- node outputs --------------------------------------------------------
    # The answer to one ValueReadRequest. On `data`, `value` is the winning
    # payload and `winner` its stamp; on `empty` both are absent (no op folded).
    Msg("ValueReadResponse",
        F("value_id", 1, STR),
        F("stream_id", 2, STR),
        F("value", 3, BYTES, optional=True),
        F("winner", 4, Ref("ValueStamp"), optional=True),
        F("state", 5, Ref("ValueState"))),
    # Engine diagnostics, delegated to the caller (a sans-io fold cannot log).
    # First (only, in v0) use: a rejected equivocating write emits exactly one
    # ValueDiagnostic{error, equivocation}; the register is left unchanged.
    Msg("ValueDiagnostic",
        F("severity", 1, Ref("ValueSeverity")),
        F("code", 2, Ref("ValueDiagCode"))),
)
