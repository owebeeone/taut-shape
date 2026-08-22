# Taut Shape Phase 5 Post-Implementation Review

Date: 2026-08-22
Scope: stream policy, schema/corpus, Rust/TypeScript/Python engines and tools,
live interop, and Glial live-metrics integration

## Result

Phase 5 is complete locally with no open correctness finding. The implementation
matches the bounded, live-only contract in `TautShapeStreamDecision.md`: a
positive `capacity_records` construction knob bounds memory, a reader that falls
behind the retained floor receives `state=dropped` with `slow_consumer`, and a
subsequent read is a fresh late join at the current head with no replay.

## Contract and reproducibility

- `ir/shape_stream.taut.py` and generated `ir/shape_stream.ir.json` define the
  payload-agnostic companion protocol. `python3 ir/regen.py --check` is clean.
- `corpus/scripts_stream/` contains 28 authored scenarios and
  `corpus/stream.v1.json` is pinned as `stream.oracle/v1`.
- `python3 corpus/stream_gen.py --check` regenerates the corpus byte-for-byte.
- Coverage includes late join, batching and byte-bound forward progress,
  overflow/drop, independent fast/slow readers, reconnect, held reads, timers,
  supersession, seal/close, teardown, and post-terminal diagnostics.
- Generated Python, Rust, and TypeScript bindings carry provenance back to the
  canonical authored schema.

## Independent engines and tool surfaces

- Rust: the `no_std + alloc` `StreamNode` uses a capacity-bounded `BTreeMap`,
  passes all corpus vectors and the 2,000-held-reader order/scaling test, and is
  registered in the shared CLI and shape-local tag registry.
- TypeScript: `StreamNode` uses a capacity-bounded sequence map, passes all 28
  vectors and the 2,000-reader test, exports the public stream API, and is
  registered in the shared CLI.
- Python: `StreamNode` uses a bounded deque plus payload map, passes all 28
  vectors and the 2,000-reader test, and is registered through `StreamAdapter`.
- Each CLI supports the same `stream` node/client shape plus capacity, batch,
  timeout, multiple-reader, intentional-pause, drop, and reconnect controls.
  Unsupported shapes and direction/unknown-tag errors remain fail-closed.

## Live interop

Five deterministic stream scenarios exercise all nine node/client language
pairings: live tail through EOF, scripted timer expiry, failed close, a paused
slow reader being dropped while a fast reader continues, and the dropped reader
reconnecting as a late join to receive only new data.

The complete normal matrix gate passes 174 tests: 171 live cells across atom,
log, stream, and value, plus three harness regressions. The dependency-isolated
`python3 -S matrix/driver.py` run passes all 171 live cells. The common harness's
partial-start, timeout/protocol-failure, pipe-close, kill, and reap regressions
continue to cover stream without shape-specific process control.

## Consumer acceptance

Glial now advertises `stream.oracle/v1` as a delivery capability while keeping
it out of the durable multi-writer value/log fold path. `LiveMetricsStream`
uses the canonical TypeScript `StreamNode` for a real provider-metrics surface.
Its integration test rejects a second producer, observes and counts a
`slow_consumer` loss, reconnects at the current head without replaying the lost
interval, and receives the next live metric with the correct sequence.

## Verification snapshot

- Rust: 67 core tests, 17 tool tests, 2 interop tests, and 5 CLI tests pass;
  `no_std` and strict workspace Clippy pass.
- TypeScript: strict typecheck and all 111 tests pass.
- Python: all 125 tests pass. Strict checking of the changed stream engine is
  clean; the broader tool/wire check reports only the existing missing
  `py.typed` boundary for the sibling `taut` package.
- Glial: strict typecheck and all 75 tests pass.
- IR and stream-corpus regeneration checks pass.
- Normal matrix/harness: 174/174. Isolated live matrix: 171/171.

## Review disposition

No correctness remediation is required before Phase 6. Changes remain
uncommitted, as requested; this review does not authorize commit or push.
