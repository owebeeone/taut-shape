# Taut Shape Phase 3 Post-Implementation Review

Status: clean — no open correctness finding  
Date: 2026-08-22  
Scope: the `value.oracle/v0` contract, three language engines and tools, live
interop matrix, and Glial consumer adapter

## Result

Phase 3 is complete locally and remains uncommitted. Rust, TypeScript, and
Python independently implement the attributed whole-value register, expose it
through the shared shape adapter shell, and reproduce all 13 committed corpus
vectors. Glial's named `ValueRegister` adapter reproduces the same complete
corpus.

The live matrix passes five value scenarios across every Rust/TypeScript/Python
node-client pairing in both the normal and an inherited-`PYTHONPATH`-free
environment. The existing four log scenarios remain green.

## Findings closed during review

1. The generated TypeScript value API uses `bigint`, but the package initially
   retained an older safe-number-only vendored CBOR runtime. The runtime and
   codec were refreshed from canonical Taut, the JSON bridge now preserves
   integers as `bigint`, and a full signed-i64 wire round trip is pinned.
2. `(lamport, origin)` alone did not totally order two accepted writes when one
   origin reused a Lamport value. Different container iteration rules could
   therefore choose different winners. The canonical reference, contract,
   engines, Glial adapter, fold oracle, and value oracle now use
   `(lamport, origin, seq)`, with two message-level vectors, one raw-fold vector,
   and one live matrix scenario proving arrival-order-independent convergence.

No correctness finding remains open.

## Replayed gates

- Taut generator/compiler suite: 227 passed.
- IR regeneration plus log, value, fold, atom, and SWMR corpus checks: clean.
- Rust: workspace tests green; core 64, tool 13, interop 2, CLI 5;
  `taut-shape --no-default-features` builds.
- TypeScript: typecheck clean; 50 tests passed.
- Python: 64 tests passed; targeted mypy gate clean.
- Glial: typecheck clean; 71 tests passed.
- Matrix: 81 live cells plus 3 harness/leak regressions passed; isolated run
  also passed all 81 live cells.

No commit, merge, or push was performed.
