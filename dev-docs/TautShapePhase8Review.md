# Taut Shape Phase 8 Review

Status: implementation complete locally; packages intentionally unreleased

Date: 2026-08-22

## Outcome

The shape family now has exhaustive consumer boundaries, a first Gryth provider
cutover, and executable drift/release gates. No publication, commit, or push was
performed.

## Glial log coverage

`dev-docs/log-corpus-applicability.v0.json` classifies all 25
`log.oracle/v0` vectors exactly once. Six immediate append/cursor/batch vectors
cross Glial's `LogBuffer` assembly seam and reproduce the canonical transcript.
Nineteen held-read, timer, terminal, eviction, teardown, and producer-stop rows
belong to the portable node state machine because Glial's binder does not own or
expose those mailbox operations. The oracle test fails if either the corpus or
the classification changes without the other.

## Gryth graduation

The GWZ-managed Gryth workspace now includes Glial as a clean Git member pinned
by its lock to `b3ee6658b76cc208fdb7363a3c14724581079d87`. The composition root's
`WorkspaceNameTap` is a Glial `value` provider over the existing
`WORKSPACE_NAME` grip. The visible demo value is seeded through the instance
write/fold path, and the provider control grip can update it without any UI or
Grip consumer learning the delivery protocol.

The headless seam regression proves the unchanged Grip read, the Glial control
write, and the round trip. Gryth's full 74-test suite, production build,
no-React-state gate, and ESLint suite pass.

## Release and drift gates

- `release/compatibility.v1.json` covers every active catalogue engine/profile,
  its contract version, every oracle, all three language packages, and consumer
  pins.
- `release/check_compatibility.py` checks development lockstep and has a stricter
  tag/release mode that rejects dirty trees, `0.0.0`, and non-semver consumer
  pins.
- `.github/workflows/contract-and-interop.yml` regenerates IR/corpora, runs all
  language tests and Rust lint/no-std gates, and runs full plus isolated live
  matrices.
- Glial and Gryth each own a selected-consumer workflow.
- `TautShapeReleaseCompatibility.md` is the human-facing version/pin table.

All current packages and consumers remain explicitly development/private or
prototype. Release mode is expected to reject them until coordinated clean
commits, package versions, publication, and semver consumer re-pins exist. This
is the fail-before-release behavior required by the plan, not an implicit claim
that local paths are publishable.

## Review disposition

All implementation work in Phases 0–8 is complete locally. The next actions are
release operations: review the unified diff, commit coordinated repositories,
assign package versions/tags, publish the three language packages, convert
consumer development links to semver, and run the tag gate. Those actions
require explicit commit/publish authority and are not performed here.

## Final validation

| Gate | Result |
| --- | --- |
| IR and corpus drift | all 6 IR exports and all 10 committed corpora regenerate in check mode |
| Taut catalogue | 5 tests passed |
| Python package | sdist + wheel build; 183 tests passed |
| TypeScript package | typecheck; 169 tests passed |
| Rust package | 71 core + 22 tool + 2 interop + 5 CLI tests; clippy and `no_std` passed |
| Live interop | 315/315 cells plus 3 harness tests; 4 compatibility tests pass; isolated 315/315 |
| Glial | typecheck; 78 tests passed |
| Gryth | 74 tests, production build, no-React-state scan, and ESLint passed |
| Datascad | refreshed decision-document pin; all 15 adapter checks and SQLite generation-reset runtime passed |

The Datascad gate caught a stale hash for `AtomSwmrNotes.md` after the completed
snapshot-delta evidence was appended. Its schemas and corpora had not drifted;
the development pin now records the new document hash and why it changed.
