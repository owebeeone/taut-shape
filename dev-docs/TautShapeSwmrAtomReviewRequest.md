# TautShapeSwmrAtomReviewRequest — independent review of the post-remediation atom/swmr work

You are an independent reviewer with a two-letter designator **XX** (supplied at
invocation; else pick the lowest unused pair alphabetically for which no output
file below exists). Several reviewers run this prompt independently: do NOT read
any `TautShapeSwmrAtomReview-*.md` before writing your own. **Write your review
to `dev-docs/TautShapeSwmrAtomReview-XX.md`** in this repo. Rules: offline;
read-only except your own review file; NO git operations; canonical checkout is
THIS repo (`/Users/owebeeone/limbo/taut-dev/taut-shape`) — never open the
glade-wz duplicate; every claim cites file:line or a command you ran; unverified
claims are marked SUSPECTED.

## Context (verify, don't trust)

The atom/swmr shapes were added recently, then reviewed twice
(`dev-docs/TautShapeCode-Review56.md`, `-ReviewF5.md`) and REMEDIATED to oracle
**v1** (`corpus/atom.v1.json` 28 vectors, `corpus/swmr.v1.json` 32) under
ratified downstream decisions PH0-D19/D20/D24 (recorded in
`/Users/owebeeone/limbo/datascad/dev-docs/DatascadPhase0Spec.md` §7): canonical
resolver on every path incl. timed expiry; `next_cursor` present iff a snapshot
exists; absent-cursor holds never receive `reset`; snapshots consume no
delivery-seq slot; compaction/re-basing never resets caught-up readers; one
reset-reason enum with engine normalization of producer-supplied engine
reasons; `CancelTimer` before any non-expiry resolution of a timed hold;
jsoncodec-form capture. Downstream consumers: datascad pins these files by hash
(`datascad/rl/harness/TAUT_PIN.json`) and garns M4 emits streams validated by
`datascad/rl/harness/taut_adapter.py`.

## Your tasks

1. **Baseline**: run `python3 ir/regen.py --check` and all five corpus `--check`
   gates plus `python3 matrix/driver.py`; report results. (Matrix should be
   hermetic post-remediation — verify with `python3 -S matrix/driver.py` too.)
2. **Remediation completeness audit**: for EVERY finding in Review56 (esp. F2,
   F4) and ReviewF5 (esp. F5-02, F5-03, F5-04, F5-06, F5-07, F5-13) verify the
   fix is actually present in code AND pinned by a vector — cite the vector
   file. A fix without a pinning vector is a finding.
3. **Fresh review of the changed code**: `ir/shape_atom.taut.py`,
   `ir/shape_swmr.taut.py`, `corpus/atom_gen.py`, `corpus/swmr_gen.py`, the new
   `scripts_atom/`/`scripts_swmr/` vectors, `dev-docs/AtomSwmrNotes.md`
   (#1–#16). Hunt NEW defects the remediation may have introduced: state
   normalization on every response path, reset/compaction interactions,
   seq/base_seq arithmetic after the D20 renumbering (9 swmr scripts were
   renumbered — check them all), timer lifecycles, corpus/schema/doc agreement.
4. **Seeded leads from downstream** (verify or refute): (a) case-10
   retention-loss reset *timing* is under-documented (recoverable only from
   datascad's generate_p9.py) — assess whether the swmr contract docs state
   when retention loss is discovered/delivered; (b) the datascad
   BINDING_CONTRACT has no `log` delivery kind — assess whether taut-shape's
   `log` shape docs give a consumer enough to define one.
5. **Consistency + complexity** on the changed files only (the earlier reviews
   covered the rest): repo conventions held? any new ≥O(n²) on unbounded n?

## Output format

`dev-docs/TautShapeSwmrAtomReview-XX.md`: header (designator, date, baseline
results); verdict ≤5 sentences; findings table
`ID(XX-nn) | file:line | severity(blocker/major/minor/nit) | class | description | proposed fix`,
most severe first; remediation-completeness checklist (finding → fixed? →
pinning vector); seeded-leads verdicts; do-NOT-change list. Final chat message:
10 lines — verdict, top 3 findings, remediation-audit summary, review path.
