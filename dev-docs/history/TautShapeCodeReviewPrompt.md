# TautShapeCodeReviewPrompt — "anew" code review of taut-shape (pre-existing + new)

You are an independent code reviewer. Your designator is **XX** (supplied at
invocation; if none was supplied, pick the lowest two-digit number ≥ 01 for which
`dev-docs/TautShapeCode-ReviewXX.md` does not yet exist). Several reviewers run
this same prompt independently: do NOT read any other
`dev-docs/TautShapeCode-Review*.md` before writing your own — your value is an
independent pass. Write ONLY your own review file.

## Ground rules

- Repo under review: `/Users/owebeeone/limbo/taut-dev/taut-shape` — the canonical
  checkout. Do NOT open or compare the duplicate checkout under
  `glade-wz/taut-shape`; it is not an authority.
- The working tree contains BOTH committed code (base commit `389c867`) and new,
  uncommitted additions (the `atom`/`swmr` shape schemas, their corpus
  generators/vectors, and `dev-docs/AtomSwmrNotes.md`, authored recently by a
  different agent). This is an **"anew" review**: review the ENTIRE codebase as
  one body of code, not a diff review — pre-existing code is as much in scope as
  the new code, and consistency is judged across old+new together.
- Read-only: make NO code changes, NO fixes, NO git operations. Your only output
  is the review document. You MAY run the repo's existing validation entry points
  (e.g. `ir/regen.py --check`, `corpus/*_gen.py --check`, `matrix/driver.py` if
  runnable) to establish the current green baseline before reviewing — report
  their results.
- Do everything yourself in one session (no sub-agents). Work offline.
- Design semantics are NOT in scope: `dev-docs/AtomSwmrNotes.md` and
  `dev-docs/TautShapeRoadmap.md` record open design decisions under separate
  review — do not re-litigate what atom/swmr *should mean*. Code quality,
  structure, efficiency, and coverage are in scope. DO flag where new code
  diverges from repo conventions, whether the divergence is in old or new code's
  favor.

## What to read (all of it — the repo is small enough)

`README.md`; `dev-docs/` (for orientation, esp. `TautShapeOracle.md`,
`TautShapeRoadmap.md`, `AtomSwmrNotes.md`); everything under `ir/` (all
`*.taut.py` shape schemas, `*.ir.json`, `regen.py`); everything under `corpus/`
(all generators, `scripts_*/` vector sources, `*.v0.json` corpora,
`corpus/README.md`); `matrix/` (cross-language driver and anything it drives);
and ALL per-language engine/emission code wherever it lives (search the repo for
the Python, Rust, and TypeScript implementations/emitters — do not assume a
layout).

## Review dimensions (each gets its own section in your report)

1. **Code-practice consistency.** Naming, module layout, error handling,
   docstring/comment conventions (e.g. the D-numbered decision-comment style),
   CLI conventions (`--check` lockstep gates), schema-definition idioms across
   all four shapes (`log`, `value`, `atom`, `swmr`), and generator structure
   across all corpus generators. Call out every place old and new code disagree
   on a convention, and say which side should yield.

2. **Efficiency — no O(n²) or worse.** Audit loops, lookups, and serialization
   paths in the generators, engines, regen tooling, and matrix driver.
   Typical suspects: linear scans inside per-item loops (list membership instead
   of set/dict), re-serializing or re-hashing whole corpora per vector, per-
   reader × per-delta work that could be indexed, repeated file re-reads,
   accidental quadratic string building. For every finding: file:line, the input
   dimension n that makes it grow, why it is ≥ O(n²), and the concrete fix.
   Also confirm the ones that are FINE (small bounded n) so the report doesn't
   cry wolf — state the bound.

3. **Reuse / architecture — no cut-and-paste.** Identify duplicated or
   near-duplicated chunks where a shared function/module with parameters would
   do. Known suspects to examine explicitly (verify, don't assume): the
   per-generator embedded reference engines (`atom_gen.py`/`swmr_gen.py` mailbox
   engines vs whatever `gen.py`/`value_gen.py`/`fold_gen.py` share), the
   `--check` lockstep logic replicated across generators, `scripts_*/` vector
   boilerplate, schema-file preambles/core-type blocks repeated across
   `shape_*.taut.py`, and any per-language emission templates that repeat per
   shape. For each: the duplicated locations (file:line ranges), the proposed
   shared abstraction (sketch the function/module signature), and the risk of
   the refactor. Propose; do not perform.

4. **Language coverage — py / rs (Rust) / ts.** Determine from the repo itself
   what "supported shape languages" currently means (docs vs reality), then
   build the coverage matrix: for each shape (`log`, `value`, `atom`, `swmr`) ×
   each language (Python, Rust, TypeScript): schema emitted? engine/runtime
   implemented? corpus validated against that engine (e.g. via `matrix/`)?
   Requirement to review against: shapes should be emitted for all three
   currently supported languages. Flag every gap precisely (e.g. "atom/swmr
   have reference semantics only in the Python generator; no rs/ts emission or
   engine; matrix driver covers log only") and state the minimal work items to
   close each gap. If the repo's own docs claim coverage the code doesn't have
   (or vice versa), that is a finding.

## Report format

Write your review to `dev-docs/TautShapeCode-ReviewXX.md` (XX = your
designator) containing:

1. **Header**: designator, date, base commit + note on uncommitted files
   reviewed (list them), baseline validation-run results.
2. **Verdict paragraph**: overall code health in ≤6 sentences.
3. **Findings table**: `ID | file:line | severity (blocker/major/minor/nit) |
   class (consistency/efficiency/reuse/coverage/correctness) | description |
   proposed fix`. IDs `XX-01, XX-02, …` so findings are citable across reviews.
   Rank most severe first. If you find an outright correctness bug while
   reading, report it (class: correctness) even though hunting bugs is not the
   primary brief.
4. **Complexity audit** (dimension 2 in full, including the cleared-as-fine list
   with bounds).
5. **Reuse/refactor proposals** (dimension 3, with sketched signatures and a
   suggested refactor order).
6. **Language-coverage matrix** (dimension 4) + gap work items.
7. **Consistency notes** (dimension 1 residue not already in the table).
8. **Do-NOT-change list**: things that look like violations but are justified
   (with the justification), so a later fixer doesn't "clean up" something
   load-bearing.

Every claim cites file:line. Findings you could not verify by reading or
running are marked SUSPECTED, not stated as fact. Your final chat message is a
10-line summary: verdict, top 3 findings, coverage-matrix highlights, and the
path of your written review.
