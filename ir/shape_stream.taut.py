"""Taut `stream` delivery vocabulary (`stream.oracle/v1`).

The policy is frozen in `dev-docs/TautShapeStreamDecision.md`: a bounded ring,
node-owned per-reader positions, live-only late join, and explicit slow-reader
drop. Payloads are opaque Taut-encoded bytes. The engine is Sans-I/O; timers
and teardown are messages.

Regenerate (from taut-dev/taut-shape):
  PYTHONPATH=../taut/src python3 -m taut.cli gen ir/shape_stream.taut.py \
      -o <out> -l python,typescript,rust --api-only
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "taut" / "src"))

from taut.ir.dsl import BYTES, INT, STR, Enum, F, List, Msg, Ref, schema


SCHEMA = schema(
    Enum(
        "StreamMsgType",
        push=0,
        seal=1,
        close=2,
        read=3,
        end_stream=4,
        timer_expired=5,
        read_response=6,
        set_timer=7,
        cancel_timer=8,
        producer_stop=9,
        diagnostic=10,
    ),
    Enum(
        "StreamState",
        data=0,
        would_block=1,
        eof=2,
        closed=3,
        failed=4,
        dropped=5,
    ),
    Enum(
        "StreamErrorCode",
        unknown_stream=0,
        producer_error=1,
        internal=2,
        slow_consumer=3,
    ),
    Enum("StreamStopReason", last_reader_gone=0, closed=1, failed=2),
    Enum("StreamSeverity", warn=0, error=1),
    Enum("StreamDiagCode", push_after_terminal=0),

    Msg("StreamPosition", F("seq", 1, INT)),
    Msg(
        "StreamRecord",
        F("seq", 1, INT),
        F("payload", 2, BYTES),
    ),
    Msg(
        "StreamError",
        F("code", 1, Ref("StreamErrorCode")),
        F("message", 2, STR, optional=True),
    ),

    Msg("StreamPush", F("payload", 1, BYTES)),
    Msg("StreamSeal"),
    Msg("StreamClose", F("error", 1, Ref("StreamError"), optional=True)),

    # No cursor: the node owns the reader position. First use of stream_id
    # joins at the then-current head, so reconnect is intentionally lossy.
    Msg(
        "StreamReadRequest",
        F("stream_id", 1, STR),
        F("max_records", 2, INT, optional=True),
        F("max_bytes", 3, INT, optional=True),
        F("timeout_ms", 4, INT, optional=True),
    ),
    Msg("StreamEndStream", F("stream_id", 1, STR)),
    Msg("StreamTimerExpired", F("token", 1, INT)),

    Msg(
        "StreamReadResponse",
        F("stream_id", 1, STR),
        F("records", 2, List(Ref("StreamRecord"))),
        F("next_position", 3, Ref("StreamPosition")),
        F("state", 4, Ref("StreamState")),
        F("error", 5, Ref("StreamError"), optional=True),
    ),
    Msg("StreamSetTimer", F("token", 1, INT), F("ms", 2, INT)),
    Msg("StreamCancelTimer", F("token", 1, INT)),
    Msg("StreamProducerStop", F("reason", 1, Ref("StreamStopReason"))),
    Msg(
        "StreamDiagnostic",
        F("severity", 1, Ref("StreamSeverity")),
        F("code", 2, Ref("StreamDiagCode")),
    ),
)
