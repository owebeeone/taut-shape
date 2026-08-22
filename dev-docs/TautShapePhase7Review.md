# Taut Shape Phase 7 Review

Status: complete locally
Date: 2026-08-22

## Outcome

Phase 7 now has one payload-agnostic CRDT delivery contract and one text
specialization over that exact core. Rust, TypeScript, and Python agree on the
mailbox corpus, all authored replica permutations, and the live two-replica
matrix. Glial provides the first collaborative consumer and converges after
offline concurrent edits and reconnect without a private merge rule.

The normative identity/bootstrap/error decision is
`TautShapeCrdtDecision.md`. Operation identity is `(origin, seq)`; `stream_id`
only addresses a sync read. Normalized vector clocks carry causal dependencies
and resume state. Exact repeats are idempotent; equivocation keeps the
lexicographically canonical envelope variant and emits one stable diagnostic.
Unready operations occupy a construction-bounded pending map.

## Contract evidence

- `ir/shape_crdt.taut.py` and generated `shape_crdt.ir.json`.
- `crdt.oracle/v1`: 15 exact mailbox vectors.
- `crdt.convergence/v1`: five N-replica permutation scenarios.
- `text_crdt.profile/v1`: five text projection scenarios over the common core.
- All generators and IR regeneration pass in check mode.

## Runtime evidence

| Gate | Result |
| --- | --- |
| Python | 183 tests; 18 CRDT-specific tests including 2,000 reversed operations |
| TypeScript | typecheck plus 169 tests; 18 CRDT-specific tests |
| Rust | 71 core + 22 tool + existing integration/CLI tests; clippy and `no_std` green |
| Live matrix | 72/72 CRDT + text cells across all Rust/TS/Python node/client pairs |
| Isolated Python matrix | 72/72 CRDT + text cells |
| Glial | typecheck and 77 tests, including collaborative offline/reconnect/delete |

The live client is itself a replica. It sends local bootstrap/operations, reads
from its durable vector, applies returned operations through its own engine, and
emits a canonical final op set and diagnostic set. Text scenarios additionally
emit the shared text projection. Thus the matrix proves replica convergence,
not merely that one language can decode another's frames.

## Consumer boundary

`GlialCollaborativeText` replays retained common-core operations in both
directions, then verifies/resumes through vector reads. This two-phase exchange
is required because a divergent peer's full vector is correctly invalid until
the source has observed the peer-only components. Both exact replay and causal
read resolution remain common-engine behaviors. The consumer owns only editor
intent and connection scheduling.

Existing Glial value/log folds, provider-status atom, and live metrics stream
remain unchanged.

## Review disposition

No open Phase 7 correctness finding remains. Post-bootstrap compaction and
tombstone garbage collection are explicitly deferred because safe reclamation
requires replica-acknowledgement semantics and a new contract version.
