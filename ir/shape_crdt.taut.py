"""Payload-agnostic replicated-operation delivery vocabulary for `crdt`.

The normative behavior is `dev-docs/TautShapeCrdtDecision.md`. This schema owns
only operation identity, causal/vector delivery, bootstrap and terminal state;
payload merge (including `text_crdt`) is deliberately outside the wire core.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "taut" / "src"))

from taut.ir.dsl import BYTES, INT, STR, Enum, F, List, Msg, Ref, schema


SCHEMA = schema(
    Enum(
        "CrdtMsgType",
        apply=0,
        install_bootstrap=1,
        seal=2,
        close=3,
        read=4,
        read_response=5,
        diagnostic=6,
    ),
    Enum(
        "CrdtState",
        data=0,
        empty=1,
        eof=2,
        closed=3,
        failed=4,
        bootstrap_required=5,
        invalid_cursor=6,
    ),
    Enum("CrdtErrorCode", unknown_crdt=0, producer_error=1, internal=2),
    Enum("CrdtSeverity", warn=0, error=1),
    Enum(
        "CrdtDiagCode",
        apply_after_terminal=0,
        invalid_operation=1,
        equivocation=2,
        bootstrap_conflict=3,
        pending_bound_exceeded=4,
    ),
    Msg("CrdtClockEntry", F("origin", 1, STR), F("seq", 2, INT)),
    Msg("CrdtClock", F("entries", 1, List(Ref("CrdtClockEntry")))),
    Msg(
        "CrdtOp",
        F("origin", 1, STR),
        F("seq", 2, INT),
        F("deps", 3, Ref("CrdtClock")),
        F("payload", 4, BYTES),
    ),
    Msg(
        "CrdtBootstrap",
        F("clock", 1, Ref("CrdtClock")),
        F("state", 2, BYTES),
    ),
    Msg("CrdtError", F("code", 1, Ref("CrdtErrorCode")), F("message", 2, STR, optional=True)),
    Msg("CrdtApply", F("op", 1, Ref("CrdtOp"))),
    Msg("CrdtInstallBootstrap", F("bootstrap", 1, Ref("CrdtBootstrap"))),
    Msg("CrdtSeal"),
    Msg("CrdtClose", F("error", 1, Ref("CrdtError"), optional=True)),
    Msg(
        "CrdtReadRequest",
        F("crdt_id", 1, STR),
        F("stream_id", 2, STR),
        F("cursor", 3, Ref("CrdtClock"), optional=True),
    ),
    Msg(
        "CrdtReadResponse",
        F("crdt_id", 1, STR),
        F("stream_id", 2, STR),
        F("bootstrap", 3, Ref("CrdtBootstrap"), optional=True),
        F("ops", 4, List(Ref("CrdtOp"))),
        F("next_cursor", 5, Ref("CrdtClock")),
        F("state", 6, Ref("CrdtState")),
        F("error", 7, Ref("CrdtError"), optional=True),
    ),
    Msg(
        "CrdtDiagnostic",
        F("severity", 1, Ref("CrdtSeverity")),
        F("code", 2, Ref("CrdtDiagCode")),
        F("origin", 3, STR, optional=True),
        F("seq", 4, INT, optional=True),
    ),
)
