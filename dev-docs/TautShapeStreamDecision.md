# Taut Stream Policy Decision

Status: accepted for `stream.oracle/v1`
Date: 2026-08-22

## Decision

`stream` is disposable ordered delivery backed by a bounded in-memory ring.
Capacity is a positive construction knob (`capacity_records`), not a separate
profile. When a reader falls behind the retained floor, that reader receives
`state=dropped` on its next read and its session is removed. The producer and
other readers continue.

This deliberately differs from `log`: there is no durable cursor, eviction
command, or replay promise. A reader is addressed by `stream_id`; the node owns
its position. A newly seen `stream_id` joins at the current head and receives
only future records. Ending a stream and reconnecting—even with the same id—is
a fresh late join.

## Frozen behavior

1. `push` assigns contiguous engine-owned sequence numbers starting at one.
2. At most `capacity_records` payloads are retained. Push drops the oldest
   payloads immediately when the bound is exceeded.
3. `read` carries no cursor. A first read creates a reader positioned at the
   current head. A subsequent read continues from the node-owned position.
4. Available data wins over terminal state. A sealed or closed reader drains
   retained unread data before `eof`, `closed`, or `failed`.
5. A reader whose next required sequence is below the retained floor receives
   one empty `dropped` response, is removed, and cannot resume that session.
6. Late join is live-only. Records pushed before the first read are not replayed.
7. Reads support `max_records`, `max_bytes`, and `timeout_ms` with the same
   forward-progress and Sans-I/O timer rules as `log`.
8. At most one read is held per reader. A new read supersedes the old one and
   cancels its timer before resolving or holding the replacement.
9. A push wakes caught-up held readers in reader-creation order. Slow idle
   readers never block retention or producer progress.
10. `seal` is graceful and idempotent. `close` is idempotent; an error produces
    `failed`, otherwise `closed`. Close after seal remains a valid transition.
11. `end_stream` cancels a held timer and removes the reader. Under
    `stop_when=last_reader`, the transition from at least one reader to none
    emits `producer_stop(last_reader_gone)`.
12. Push after seal/close is ignored and emits one warning diagnostic.
13. `close` emits `producer_stop(closed|failed)`. `stop_when=explicit_only`
    suppresses only the last-reader stop.

## Resume and reconnect

There is no cross-reconnect resume token in v1. Applications needing retained
history use `log`; applications needing a reconstructible snapshot plus deltas
use `swmr`. Stream reconnect is intentionally lossy and is tested as a late
join at the then-current head.

## Acceptance scenarios

The oracle must cover empty probe, live delivery, late join, batching and byte
bounds, slow-reader drop, two-reader independence, held wake-up, timers and
supersession, terminal drain, clean/failed close, teardown/producer stop,
capacity validation, and push-after-terminal diagnostics. The live matrix must
include observable slow-reader loss and reconnect behavior in addition to held,
timer, multi-reader, and terminal cases.
