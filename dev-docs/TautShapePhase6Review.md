# Taut Shape Phase 6 Post-Implementation Review

Date: 2026-08-22  
Scope: SWMR engines, snapshot-delta expiry profile, live interop, and Datascad
runtime integration

## Result

Phase 6 is complete locally with no open correctness finding. Rust,
TypeScript, and Python independently implement the stabilized
`swmr.oracle/v1` contract, while `snapshot_delta` is a thin fixed-policy
projection over those same cores. Datascad now runs a real SQLite query-result
subscription through the Python engine instead of stopping at fixture
validation.

## SWMR contract and engines

- The authored schema and 33-vector corpus retain durable `(epoch, seq)`
  cursors, single-writer binding, pre-head snapshot re-base, contiguous deltas,
  held reads/timers, terminal lifecycle, and opaque reset detail.
- All three engines pass all vectors and 2,000-held-reader ordering/scaling
  coverage. Rust remains `no_std + alloc`; TypeScript typechecks strictly;
  Python's changed core/tool files pass strict mypy.
- Each public CLI registers `swmr`, uses the generated shape-local tag registry,
  supports absent or explicit epoch cursors, and fails unknown shapes/tags
  closed.
- Five live scenarios contribute 45 passing SWMR cells: initial snapshot/delta
  drain, retained resume, reset between polls, timer expiry, and writer
  conflict with authoritative-writer recovery.

## Snapshot-delta profile

- `TautShapeSnapshotDeltaDecision.md` fixes public name, allowed operations,
  default bound, and reset projection.
- Four authored profile vectors regenerate byte-for-byte and pass in all three
  language packages through their contained SWMR cores.
- `state=reset` is projected to `refresh_required` with one of
  `retention_expired`, `invalid_cursor`, or `source_changed`; raw reset repair
  state and detail do not reach the profile application transcript.
- Three live profile scenarios contribute 27 passing language-pair cells,
  including a positioned reader crossing producer reset between polls.

## Datascad consumer acceptance

`datascad/rl/harness/taut_runtime_adapter.py` selects `taut-shape-py` and owns
the Datascad JSON encoding of query snapshots, deltas, generation, source
revision, and query-contract revision. The SWMR engine sees only opaque bytes
and owns writer binding, delivery sequence, reset epoch, cursors, and lifecycle.

The runtime selftest executes a real SQLite query, delivers an initial snapshot
and update delta, holds the next read, changes the schema/query generation,
receives the exact reset-detail bytes, refreshes with a real replacement query
result, and observes engine epoch 1. The pre-existing Datascad contract suite
reports all 15 checks green (the plan's older baseline said 14; an epoch-reset
pin check had already raised the actual count to 15 before this integration).

## Verification snapshot

- SWMR live matrix: 45/45.
- Snapshot-delta live matrix: 27/27.
- Full normal matrix/harness: 246/246 (243 live + 3 harness).
- Dependency-isolated `python3 -S matrix/driver.py`: 243/243 live cells.
- TypeScript: strict typecheck and 151/151 tests.
- Python: 165/165 tests; strict changed-file mypy and ruff clean.
- Rust: 68 core tests, 20 tool tests, 2 interop tests, and 5 CLI tests; strict
  clippy and `no_std` build clean.
- Datascad: 15/15 existing adapter checks plus the new runtime generation-reset
  selftest.
- SWMR and snapshot-delta corpus regeneration checks are clean.

## Review disposition

No correctness remediation remains before Phase 7. Changes are uncommitted as
requested; this review authorizes neither commit nor push.
