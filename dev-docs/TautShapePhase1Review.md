# Taut Shape Phase 1 post-remediation review

Date: 2026-08-22  
Status: clean review; no open correctness finding in the reviewed scope.

## Scope

This review covers the uncommitted Atom/SWMR v1 schemas, generated IR,
authored corpus scripts, reference generators, contract documentation, the
TypeScript/Python held-reader implementation changes, matrix startup cleanup,
and the Datascad pin/adapter seam. Earlier F5 and 56 reports remain historical
evidence; this report evaluates the remediated state.

## Findings disposition

1. **Resolved — reset could be missed between polls.** `SwmrCursor` is now
   `(epoch, seq)`. Producer reset increments epoch; snapshot compaction does
   not. Vector 33 proves an epoch-0/seq-1 cursor receives reset after epoch 1
   rebuilds overlapping seq 0..1.
2. **Resolved — reset detail was discarded.** `SwmrReadResponse.reset_detail`
   carries producer detail on immediate held-reader reset and later stale-epoch
   repair. Engine-assigned retention/invalid-position resets leave it absent.
3. **Resolved — restart identity was ambiguous.** `swmr_id` identifies a node
   incarnation. Reuse requires restoring an epoch above every prior issued
   epoch; otherwise the shell allocates a new id.
4. **Resolved — Atom's single-writer declaration was unenforced.** Atom v1
   deliberately keeps node-local producer messages without `writer_id`; the
   producer-binding adapter must reject a second binding before state mutation
   and must carry the corresponding conformance test.
5. **Resolved — held-reader batch release was quadratic.** TypeScript and
   Python now resolve in creation order and clear the answerable subset in one
   linear pass. Each package has a 1,024-reader regression.
6. **Resolved — matrix partial startup leaked the node.** If client startup
   fails after node startup, the driver now kills/reaps the node and closes all
   owned pipes. The failure path has a dedicated pytest regression.

No new correctness, protocol-consistency, lifecycle, or integration-pin defect
was found in the final diff review.

## Validation evidence

| Gate | Result |
| --- | --- |
| IR regeneration and all five corpus generators in `--check` mode | Pass |
| Rust workspace tests | 73 pass |
| Rust `no_std` build and clippy with warnings denied | Pass |
| TypeScript tests | 29 pass |
| TypeScript typecheck with repository-pinned TypeScript 5.9.2 | Pass |
| Python tests | 44 pass |
| Targeted strict mypy for changed Python source modules | Pass |
| Normal pytest matrix | 37 pass: 36 language/scenario cells plus startup-cleanup regression |
| Isolated `python3 -S` matrix | 36/36 cells pass |
| Datascad pin, corpus, positive, negative, and epoch-contract selftests | 15/15 pass |
| Generated JSON parsing, Python compilation, and `git diff --check` | Pass |
| GWZ fetch-only refresh and comparison with `origin/main` | All six workspace repos 0 ahead / 0 behind |

Full mypy over `tests/test_engine_unit.py` retains pre-existing helper/union-
narrowing errors; the two changed source modules pass strict mypy.

## Integration and readiness

Datascad is the concrete Atom/SWMR contract integration today: it pins the five
consumed artifacts, re-runs both corpus generators, validates P8/P9 fixture
semantics, and now directly inspects the durable reset vector. It is not yet a
runtime language-engine integration. Its fixtures have no SWMR cursor-epoch
field, so a future generated binding must retain epoch alongside `resume_seq`;
the application `generation` field is not a substitute.

No Atom or SWMR language engine exists yet in Rust, TypeScript, or Python.
Glial currently integrates Value/Log, Glade supplies lower-level fold/runtime
pieces, and Gryth remains mock-backed/planned; none should be described as a
current portable Atom/SWMR engine consumer.

The reviewed Atom/SWMR contract files are ready to land as one coherent
milestone. No commit, merge, or push was performed by this review.
