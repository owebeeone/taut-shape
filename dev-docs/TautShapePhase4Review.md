# Taut Shape Phase 4 Post-Implementation Review

Date: 2026-08-22
Scope: atom schema/corpus, Rust/TypeScript/Python engines and tools, live
interop, and the Glial provider-status consumer

## Verdict

Clean. No open correctness finding remains for the Phase 4 acceptance surface.
The three implementations independently reproduce all 28 committed atom
vectors, expose exact shape-local wire adapters, and agree in every live
language pairing. Atom remains distinct from Glial's multi-writer value fold.

## Review results

1. Replace increments one engine-owned version and retains only the latest
   payload. Reads below that version receive data; caught-up reads hold, probe,
   or resolve terminal according to the corpus.
2. Held-read supersession, timer cancellation/expiry, stream teardown, seal,
   clean/failed close, and producer stop reproduce whole oracle transcripts.
3. Held-reader release is linear or `O(H log H)` and is covered with 2,000
   readers in each language.
4. All three CLIs register `atom`, `log`, and `value` exactly. Unknown shapes,
   tags, direction violations, and malformed bodies fail closed.
5. Five live atom scenarios cover replacement wake-up, deterministic timer
   expiry, terminal draining, failed close, and two readers. They pass all 45
   Rust/TypeScript/Python node-client cells.
6. Glial consumes the canonical TypeScript `AtomNode` through an explicit
   `GlialAtomAdapter` for provider status. `ProviderStatusAtomRegistry` rejects
   a conflicting writer before service use, while the consumer test proves
   replacement and reconnect/resume from an observed version.

## Gates run

| Gate | Result |
| --- | --- |
| IR regeneration and all corpus generators in check mode | Pass |
| Rust core | 65 tests pass |
| Rust tool/unit + process tests | 22 tests pass |
| Rust `no_std` build | Pass |
| TypeScript typecheck and suite | Pass; 80 tests |
| Python suite | Pass; 94 tests |
| Targeted strict Python engine/runtime typecheck | Pass |
| Glial typecheck and suite | Pass; 73 tests |
| Normal live matrix plus leak regressions | Pass; 129 tests (126 live + 3 harness) |
| Isolated `python3 -S` matrix | Pass; all 126 live cells |

The Python wire bridge still crosses the sibling Taut package, which lacks a
`py.typed` marker; targeted strict checking therefore gates the changed engine
and runtime modules, while runtime wire behavior is covered by the full Python
suite and every cross-language matrix cell.
