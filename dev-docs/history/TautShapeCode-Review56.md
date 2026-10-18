# Taut Shape code review 56

- Date: 2026-07-19 (Australia/Brisbane)
- Reviewer designator: **56**
- Base under review: `389c867`
- Canonical repository: `/Users/owebeeone/limbo/taut-dev/taut-shape`
- Language repositories: `/Users/owebeeone/limbo/taut-dev/taut-shape-rs`, `/Users/owebeeone/limbo/taut-dev/taut-shape-ts`, `/Users/owebeeone/limbo/taut-dev/taut-shape-py`
- Scope: every non-review document, schema, exported IR, generator, authored script, corpus, matrix file, and relevant Rust/TypeScript/Python implementation, generated binding, CLI, and test. Existing `dev-docs/TautShapeCode-Review*.md` files were excluded and not read.
- Review mode: offline, read-only except for this report; no git operation, install, network access, or code change was performed.

The supplied uncommitted atom/SWMR set reviewed on top of `389c867` was:

- Integration files: `README.md`, `corpus/README.md`, `dev-docs/TautShapeOracle.md`, `ir/regen.py`.
- Design note: `dev-docs/AtomSwmrNotes.md`.
- Atom schema and generated artifacts: `ir/shape_atom.taut.py`, `ir/shape_atom.ir.json`, `corpus/atom_gen.py`, `corpus/atom.v0.json`.
- Atom authored inputs: `corpus/scripts_atom/01_read_empty_probe.json`, `02_replace_then_read_data.json`, `03_replacement_overwrites.json`, `04_generation_change_replace.json`, `05_subscriber_join_mid_stream.json`, `06_held_read_released_by_replace.json`, `07_held_read_timer.json`, `08_late_timer_ignored.json`, `09_supersede.json`, `10_seal_then_drain_eof.json`, `11_close_clean.json`, `12_close_failed.json`, `13_terminal_still_readable.json`, `14_idempotent_seal_close.json`, `15_two_streams_two_positions.json`, `16_one_replace_wakes_two.json`, `17_end_stream_mid_hold.json`, `18_last_stream_producer_stop.json`, `19_stop_when_explicit_only.json`, `20_replace_after_seal_warns.json`, and `21_replace_after_close_warns.json`.
- SWMR schema and generated artifacts: `ir/shape_swmr.taut.py`, `ir/shape_swmr.ir.json`, `corpus/swmr_gen.py`, `corpus/swmr.v0.json`.
- SWMR authored inputs: `corpus/scripts_swmr/01_initial_snapshot.json`, `02_delta_batches.json`, `03_resume_retained_seq_success.json`, `04_resume_expired_seq_reset.json`, `05_generation_change_reset.json`, `06_two_readers_different_cursors.json`, `07_backpressure_retention_bound.json`, `08_writer_uniqueness_violation.json`, `09_held_read_released_by_delta.json`, `10_held_read_timer.json`, `11_late_timer_ignored.json`, `12_supersede.json`, `13_seal_then_drain_eof.json`, `14_close_clean.json`, `15_close_failed.json`, `16_idempotent_seal_close.json`, `17_end_stream_mid_hold.json`, `18_last_stream_producer_stop.json`, `19_stop_when_explicit_only.json`, `20_push_after_seal_warns.json`, `21_terminal_still_readable.json`, and `22_delta_before_snapshot.json`.

## Findings

### F1 — High — CONFIRMED: the default live matrix cannot load the Python tool

`python3 matrix/driver.py` passes only the Rust/TypeScript combinations and fails every execution involving Python: 16 of 36 scenario executions pass and 20 fail. The immediate exception is `ModuleNotFoundError: No module named 'taut'`.

The driver adds only `taut-shape-py/src` to `PYTHONPATH` (`matrix/driver.py:49-65`). The Python framing and oracle bridge import the sibling runtime directly (`taut-shape-py/src/taut_shape/tool/framing.py:29`, `oraclefmt.py:28-29`), and the package metadata acknowledges that dependency (`taut-shape-py/pyproject.toml:21-25`). In this offline workspace it is not installed as a distribution.

This is not a protocol incompatibility: rerunning with `PYTHONPATH=/Users/owebeeone/limbo/taut-dev/taut/src` makes all 36 executions pass. The standard documented entry point is nevertheless red, so the current matrix cannot act as a clean checkout/CI gate.

Concrete fix: define `_TAUT_SRC = _TAUT_DEV / "taut" / "src"` and prepend both `_PY_SRC` and `_TAUT_SRC` in `_env_for("py")`. Add a fast preflight that imports `taut_shape.tool` in the exact child environment and reports the missing path once, instead of producing 20 derivative pairing failures. Then gate the unmodified `python3 matrix/driver.py` command.

### F2 — High — CONFIRMED: timed atom/SWMR reads return unnormalised, invalid positions

The atom contract says a request version beyond current is treated as caught up and clamped to current (`dev-docs/AtomSwmrNotes.md:46-56`). Immediate resolution does this (`corpus/atom_gen.py:222-253`), but a timed held request stores the original version and timeout expiry returns it verbatim (`corpus/atom_gen.py:283-292`). Reproduction from a fresh node at version 0:

```text
read(version=9, timeout_ms=50) -> SetTimer{1,50}
TimerExpired{1}                -> would_block, next_version=9
```

The correct `next_version` is 0.

SWMR has the same state-normalisation defect. Before the first snapshot, no valid position exists and `next_cursor` must be absent (`dev-docs/AtomSwmrNotes.md:134-140`; `ir/shape_swmr.taut.py:223-240`). Immediate resolution enforces that (`corpus/swmr_gen.py:316-317`), but timeout expiry echoes the originally supplied cursor (`corpus/swmr_gen.py:378-385`). A fresh node given `cursor=9, timeout_ms=50` returns `next_cursor=9`, manufacturing a position the schema explicitly says cannot exist.

Concrete fix: do not treat the parked request as a ready-made timeout response. On `TimerExpired`, clear the token and run the same canonical resolver in probe mode (`timeout_ms=0`), or store the resolver's normalized current position when parking. Add atom vectors for beyond-current probe and beyond-current timed expiry; add SWMR vectors for a pre-snapshot timed request with a supplied cursor and for `invalid_resume_seq` after a snapshot. The latter enum/branch exists (`ir/shape_swmr.taut.py:104-112`, `corpus/swmr_gen.py:331-334`) but no current SWMR vector reaches it.

### F3 — High — CONFIRMED: three of four contracts have no language implementation or live conformance

The canonical repo now has four schemas and four behavioral corpora, but Rust, TypeScript, and Python still emit, run, and oracle-test only `log`. The atom/SWMR generator headers acknowledge that no per-language engines exist (`corpus/atom_gen.py:10-22`, `corpus/swmr_gen.py:10-14`); the value gap was already recorded (`dev-docs/TautShapeGladeConsolidation.md:133-176`). Searches of every sibling source/generated/test tree found only `Log*` generated types, `LogNode`, and `log.v0.json` loaders.

Quantitatively, only 3 of 12 shape-language cells have generated bindings, only 3 of 12 have runtimes, and only 3 of 12 replay a canonical corpus. No value, atom, or SWMR live pairing exists. This makes the new corpora design specifications, not cross-language contracts that currently constrain shipped code.

Concrete fix: close one vertical slice at a time. For each shape, generate distinct per-shape bindings in all three repos, implement a namespaced engine, add a loader that replays the whole corresponding corpus, add shape selection to framing/CLI without reusing log tags, then add 3x3 live matrix rows. Start with `value` because it has no lifecycle/timer shell and its independent `fold_value` authority already exists; fix F2/F4 before using atom/SWMR goldens as implementation targets.

### F4 — Medium — CONFIRMED: atom/SWMR early wake paths omit `CancelTimer`

All three log engines cancel a held read's timer before emitting an early data/terminal response (`taut-shape-rs/crates/taut-shape/src/log/node.rs:361-405`, `taut-shape-ts/src/log/node.ts:334-372`, `taut-shape-py/src/taut_shape/log/engine.py:291-305`). The shared plan also requires timer cancellation on close and stream teardown (`dev-docs/TautClientImplPlan.md:131-148`).

Atom and SWMR instead clear a resolved held request without emitting cancellation (`corpus/atom_gen.py:257-267`, `corpus/swmr_gen.py:352-362`). Atom has frozen the divergence into its golden: a timed read released by replace emits only the response, while the later expiry is ignored (`corpus/atom.v0.json:301-349`), despite the authored script calling the token “canceled/already-answered” (`corpus/scripts_atom/08_late_timer_ignored.json:2-8`). SWMR has the same behavior on delta/snapshot/reset/seal/close even though its current late-timer vector tests only actual expiry.

The response semantics survive because the engine ignores the late token, but a real shell continues to own an unnecessary timer, and future language engines must choose between established log behavior and the new goldens.

Concrete fix: whenever `_answer_all_held` (or SWMR reset) resolves a timer-backed read for any reason other than `TimerExpired`, emit `CancelTimer` immediately before its response. Regenerate both corpora and add timed early-wake plus timed seal/close/reset vectors so output order is pinned.

### F5 — Medium — CONFIRMED: sequential log reads are quadratic in every language

Each log window scans retained records from the front and skips records at or below the cursor:

- Rust: `taut-shape-rs/crates/taut-shape/src/log/window.rs:101-126`.
- TypeScript: `taut-shape-ts/src/log/window.ts:80-96`.
- Python: `taut-shape-py/src/taut_shape/log/_window.py:120-143`.

With `N` retained records and a client repeatedly asking for `max_records=1`, scan work is `1 + 2 + ... + N = O(N^2)` even though only `N` records are returned. `N` is a user-controlled retained-log size, not a small schema bound.

Concrete fix: exploit the dense sequence invariant. Compute the first candidate index from the front record's sequence (or Python's floor), then iterate only the output suffix. A read becomes `O(K)` for `K` returned records, and a complete one-record-at-a-time replay becomes `O(N)` amortized. Keep cursor classification before the index calculation.

TypeScript's repeated `Array.shift()` eviction (`src/log/window.ts:102-110`) and Python's repeated front-slice deletion (`_window.py:77-98`) also make `N` incremental evictions `O(N^2)`. Use a deque/ring buffer or a logical start index with occasional compaction. Rust's `VecDeque::pop_front` path is already amortized `O(N)` across all removals and should remain unchanged.

### F6 — Medium — CONFIRMED: session release and timer lookup repeatedly scan all streams

For `S` live streams and `H` held reads, each log push/terminal release costs:

- Rust: `O(S + H log H)` because it filters a `BTreeMap` and sorts by creation rank (`log/session.rs:93-105`); timer expiry repeats that work (`log/node.rs:306-319`).
- Python: `O(S + H log H)` because it sorts an insertion-ordered dictionary (`log/_sessions.py:56-67`); timer lookup is `O(S)`.
- TypeScript: `O(S)` because `Map` already preserves creation order (`log/session.ts:72-80`); timer expiry still scans all held sessions (`log/node.ts:286-300`).

Atom and SWMR repeat the same full-order and token scans, plus `list.remove` on every stream end (`corpus/atom_gen.py:257-293`, `corpus/swmr_gen.py:352-386`). `M` pushes with `S` mostly dormant streams cost `O(MS)`; ending `S` atom/SWMR streams can cost `O(S^2)`. These are not output-size bounds because dormant streams contribute no output.

Concrete fix: maintain (1) a creation-ordered collection containing only held stream IDs and (2) a `timer_token -> stream_id` map. Park/supersede/end/expiry update both in amortized `O(1)` (or `O(log S)` in a no-std ordered map); a wake traverses only `H` held reads in required order. In the Python reference engines, `_streams` already preserves creation order, so `_order` is redundant even before the held-only index is added.

### F7 — Medium — CONFIRMED: the value and SWMR reference engines have avoidable history rescans

`Register._set` linearly searches all accepted operations for every write, and `_read` scans them twice through `max` and `fold_value` (`corpus/value_gen.py:104-126`). `W` unique writes therefore cost `O(W^2)` to ingest; `R` reads cost `O(RW)`. Replace the list lookup with a dictionary keyed by `(origin, seq)` and maintain the LWW winner incrementally. Preserve an optional full `fold_value` assertion in the lockstep/check path, where paying `O(W)` is useful independent validation rather than per-read production work.

SWMR incremental catch-up scans the entire retained delta list to select a suffix (`corpus/swmr_gen.py:335-337`). With one push followed by a read at the previous head, `N` returned deltas still cause `O(N^2)` inspection. Because deltas are contiguous, slice from `cursor - snapshot_seq`; the path then costs `O(K)` for the `K` deltas serialized, which is the unavoidable output-size bound.

### F8 — Low — CONFIRMED latency / SUSPECTED attribution race: log corpus replay uses silence as a delimiter

`corpus/gen.py` waits `QUIET_S=0.30` after every input to infer that an immediate synchronous engine produced no more output (`corpus/gen.py:27-33`, `130-183`). The current log corpus has 88 steps, so the design imposes a 26.4-second wait floor. The observed lockstep check took 27.05 seconds while using only 0.39 seconds of CPU.

The latency is confirmed. Misattribution is suspected: a valid output delayed more than 300 ms by process scheduling would be assigned to the next step. Evidence required to promote that part to confirmed is a test proxy that delays one flushed frame beyond `QUIET_S` and demonstrates a shifted golden.

Concrete fix: add a replay/control protocol with an explicit per-input completion marker, including for zero-output inputs. A `taut-shape-tool replay` mode that accepts a vector and emits one JSON result array per step would remove both the sleep and cross-stream timing inference. Do not reduce `QUIET_S`; that trades latency for a more probable race.

### F9 — Low — CONFIRMED: status documentation contradicts the current source

- `dev-docs/TautShapeRoadmap.md:13-16` says only log exists, although value/atom/SWMR schemas and corpora now exist.
- `TautClientImplPlan.md:230` says Rust/TypeScript still owe log namespacing; both now use `log/` modules.
- `taut-shape-py/README.md:18-21`, `src/taut_shape/__init__.py:3-5`, `tests/oracle/SOURCE.md:39-42`, and `pyproject.toml:31-32` say the CLI/matrix phase is not built; the tool exists and participates in the matrix.
- `taut-shape-rs/README.md:14-17,50-53` says `gen`/`check` own and implement oracle emission/verification, while `taut-shape-tool/src/main.rs:12,73-80,234-237` implements them as exit-2 stubs. `taut-shape-rs/crates/taut-shape/src/lib.rs:1-7` still calls the crate Phase 0 scaffolding.
- `taut-shape-ts/README.md:30-35` presents the tool as landed but calls the full matrix a future increment even though the canonical matrix runs it.

Concrete fix: replace phase prose with a small capability table linked to the canonical coverage table, update it in the same change that adds/removes a gate, and test the named commands in CI. Do not claim a mode is implemented merely because its CLI token exists.

## Baseline validation

All commands were run offline from the canonical repo with bytecode writes disabled.

| Command | Result |
|---|---|
| `python3 ir/regen.py --check` | PASS; all four exported IR files match their schemas |
| `python3 corpus/gen.py --check` | PASS; `log.v0.json` is in lockstep (27.05 s observed) |
| `python3 corpus/value_gen.py --check` | PASS |
| `python3 corpus/fold_gen.py --check` | PASS; also agrees with glade's frozen fold oracle |
| `python3 corpus/atom_gen.py --check` | PASS |
| `python3 corpus/swmr_gen.py --check` | PASS |
| `python3 matrix/driver.py` | FAIL; 16/36 pass, all 20 Python-involving executions fail to import `taut` |
| Same matrix with sibling `taut/src` supplied in `PYTHONPATH` | PASS; 36/36 |

The lockstep checks prove reproducibility of the current generators. They do not disprove F2/F4 because the atom/SWMR expected outputs are produced by the same reference code containing those defects.

## Complexity audit

Let `N` be retained records/deltas, `S` live streams, `H` held reads, `W` value writes, `R` value reads, `V` corpus vectors, `P` language pairs, and `C` scenarios.

| Path | Current time | Space | Assessment and replacement |
|---|---:|---:|---|
| Log append | amortized `O(1)` in all languages | `O(N)` | Acceptable. Rust `VecDeque`, TS array append, and Python list append are appropriate. |
| Log sequential reads | `O(N^2)` for one-record replay | `O(K)` response | Unbounded hot path; use dense-sequence offset for `O(N)` total / `O(K)` per read (F5). |
| Log eviction | Rust amortized `O(N)` total; TS/Python `O(N^2)` under incremental eviction | `O(N)` | Keep Rust; use deque/ring/logical offset in TS/Python (F5). |
| Held-read wake | Rust/Python `O(S + H log H)`, TS `O(S)` per wake input | `O(S)` | Unbounded non-output work; held-only ordered index gives `O(H)` (F6). |
| Timer expiry | `O(S)` or `O(S + H log H)` | `O(S)` | Token index gives amortized `O(1)` lookup (F6). |
| Atom/SWMR stream end | `O(S)` because `_order.remove` | `O(S)` | Ending all streams is `O(S^2)`; remove redundant list/use indexed ordered set. |
| Value writes/reads | `O(W^2)` ingestion; `O(RW)` reads | `O(W)` | Dictionary plus cached winner: amortized `O(1)` set/read, full fold retained only as audit (F7). |
| SWMR incremental catch-up | `O(N)` inspection per read even for one returned delta | `O(K)` response | Dense suffix index gives output-bound `O(K)` (F7). |
| Atom read/replace core excluding session scan | `O(1)` | `O(S)` | Acceptable; one current value is intentionally bounded. |
| SWMR fresh/reset response | `O(N)` | `O(N)` response | Acceptable output-size bound: the contract sends snapshot plus retained tail. |
| IR export/check | `O(total schema/IR size)` | same order | Acceptable and small; no repeated import inside the shape loop. |
| Corpus script discovery/build | `O(V log V + total JSON size)` | corpus size | Acceptable; sort is deterministic and `V` is authored/gate-bounded. |
| Fold conflict guard | `O(V + upstream V)` average | `O(V)` | Acceptable; dictionary/set comparison is already direct. |
| Matrix | `O(P*C)` process pairs plus transcript bytes | bounded child/transcript state | Intentional exhaustive product. Today `P=9`, `C=4`; no false quadratic alarm because the language set is explicitly small and exhaustive interoperability is the purpose. |
| CBOR/jsoncodec | `O(message bytes)`; generated field-map sorts are over small schema-bounded field counts | `O(message bytes)` | Acceptable. Keep fail-closed decoding and deterministic map order. |
| Log corpus step separation | `O(steps * 0.30s)` wall time independent of work | `O(queued frames)` | Replace silence delimiter with acknowledgement (F8). |

Amortized claims above rely on standard dictionary/map and deque behavior. A no-std Rust replacement can use an ordered held-ID vector plus token map with tombstones/periodic compaction if adding a dependency is undesirable; it must still avoid scanning dormant sessions on every push.

## Reuse and consolidation audit

### R1 — Extract the corpus codec/replay/check harness (low risk)

`value_gen.py:79-189`, `atom_gen.py:119-345`, and `swmr_gen.py:130-442` repeat schema conversion, script replay, deterministic build, `--check`, diff messaging, and write logic. `gen.py:212-288` repeats the latter half around an external engine, while `fold_gen.py:132-166` has a close variant with an additional conflict guard.

Create `corpus/_oracle_common.py` with narrow functions such as:

```python
CodecBridge(schema, type_to_message).native(message_name, tagged_json)
CodecBridge(...).output(message_name, native_json)
replay_scripts(directory, make_engine, node_config)
corpus_text(shape, version, vectors)
check_or_write(path, fresh_text, regenerate_command, post_check=None)
```

Keep semantic engines and per-shape input mapping outside the helper. This removes roughly four copies of error-prone gate plumbing while preserving explicit goldens. Maintainability cost today: every formatting or check-policy change is repeated, and small differences are hard to distinguish from accidental drift. Refactor risk: low if byte-for-byte corpus output is asserted before and after.

### R2 — Share only mailbox session bookkeeping between atom and SWMR references (medium risk)

`atom_gen.py:77-115,184-293` and `swmr_gen.py:89-126,278-386` repeat held-request storage, supersede, token allocation, creation ordering, stream removal, expiry lookup, and multi-wake traversal. The repetition directly contributed to the same F2/F4/F6 defects appearing twice.

Extract a private generator-only `MailboxSessions[Held]` that owns `ensure`, `supersede`, `park`, `expire`, `end`, and ordered held iteration. Shape callbacks must still build responses and decide whether a request is answerable. This gives one place for cancellation ordering and token indexing without pretending atom and SWMR share store semantics.

Maintainability benefit: lifecycle fixes and complexity fixes land once. Refactor risk: medium because response ordering is wire-visible and SWMR reset has special semantics; require unchanged-corpus tests first, then intentionally update the cancellation vectors.

### R3 — Make the matrix shape-pluggable only when the second runtime lands (medium risk)

The current driver is intentionally log-specific (`matrix/driver.py:68-86,180-235`). Before adding value rows, introduce a small shape descriptor containing tool arguments, scenarios, transcript canonicalizer, and expected-loader. Do not build a universal protocol layer ahead of an implemented second shape; use the value vertical slice to prove the seam.

Maintainability benefit: prevents copying an entire driver per shape. Risk: medium because atom/SWMR responses are not log cursor/record responses and should not be coerced into one canonical shape.

### R4 — Remove redundant ordering structures locally (low risk)

Python dictionaries and TypeScript maps preserve insertion order. Python log sessions sort an order it already has (`_sessions.py:56-61`), and atom/SWMR keep both `_streams` and `_order`. Prefer one authoritative ordered collection plus a held-only index. Risk is low, but recreate-after-end ordering needs a regression vector.

## Coverage matrix

Each language cell is **generated schema bindings / runtime engine / canonical corpus replay**. “Reference only” means the canonical Python corpus generator runs, not that `taut-shape-py` ships the engine.

| Shape | Canonical schema + IR | Rust | TypeScript | Python | Live matrix |
|---|---|---|---|---|---|
| `log` | yes | yes / yes / yes | yes / yes / yes | yes / yes / yes | Default: 16/36 scenario executions; with corrected Python path: 36/36 |
| `value` | yes | no / no / no | no / no / no | no / no / no (reference only) | none |
| `atom` | yes | no / no / no | no / no / no | no / no / no (reference only) | none |
| `swmr` | yes | no / no / no | no / no / no | no / no / no (reference only) | none |

Coverage totals:

- Canonical authored/exported schemas: 4/4. IR lockstep: 4/4.
- Behavioral vectors: log 25, value 11, atom 21, SWMR 22 = 79 shape vectors, plus 12 raw-fold vectors.
- Generated language binding cells: 3/12 (25%).
- Runtime engine cells: 3/12 (25%).
- Canonical corpus replay cells: 3/12 (25%).
- Shapes with any live matrix: 1/4; the sole matrix is red by default until F1 is fixed.

Minimum work to close the gaps:

1. Fix the Python matrix environment and make 36/36 the no-overrides baseline.
2. Add independent invariant tests and correct atom/SWMR goldens for F2/F4 before downstream implementation.
3. Land value bindings, engines, full-corpus tests, CLI shape selection, and a 3x3 value matrix as the first complete non-log slice.
4. Repeat the vertical slice for atom, including real timer-control frames and all new invalid-version/cancellation vectors.
5. Repeat for SWMR, including writer conflict, retention bound, all reset reasons, pre-snapshot optional cursor behavior, and timed reset/close paths.
6. Add per-language codegen lockstep gates so “canonical IR is current” and “checked-in generated types are current” cannot diverge.

## Schema, corpus, engine, and documentation consistency

### What is consistent

- All four exported IR files exactly match their authored schemas.
- All five committed corpora (including fold) exactly match their current scripts/generators.
- Log's 25-vector corpus is replayed whole in all three language repos, and Rust/TypeScript/Python agree live once the Python dependency path is supplied.
- Core log invariants—first sequence 1, cursor-in/cursor-out, terminal drain, diagnostics, monotonic tokens, and creation-order wake—are represented consistently in the three engines.
- The atom and SWMR schema names, per-shape message registries, corpus names, and oracle version names follow D21/D22.

### Drift and missing gates

- Atom/SWMR generators and goldens agree with each other while disagreeing with their own documented cursor normalization and with log timer cancellation (F2/F4). Their `--check` gates are self-referential because no independent engine exists.
- `SwmrResetReason.invalid_resume_seq` has schema and code but no vector. Atom's beyond-current clamp is documented and coded only on the immediate branch, with no vector. These are exactly the cases that exposed F2.
- No test checks that a timed read released by data, seal, close, or SWMR reset emits `CancelTimer` before the response. Atom's current golden instead pins omission.
- Canonical IR lockstep does not check any language repository's generated artifacts. Only log artifacts exist, and their freshness is not covered by the canonical `regen.py --check`.
- The matrix imports tool implementations from sibling source trees but does not preflight their runtime dependencies. Its README does not state the hidden `taut/src` requirement.
- Status prose has drifted independently in the plan and all three language READMEs (F9).

Recommended gates:

1. Add hand-authored invariant tests around each reference engine that assert normative properties independently of generated corpus text: normalized positions, optional cursor rules, cancellation ordering, and every enum branch.
2. Add a corpus coverage manifest mapping every state/reason/diagnostic enum member and each timer transition to at least one vector; fail if an entry has no vector.
3. Add per-language generated-file checks from the canonical IR for every supported shape.
4. Run the default matrix command in a clean child environment; do not depend on the reviewer's shell `PYTHONPATH`.
5. Keep a single capability table as the source for status documentation and validate every command it marks green.

## Do not change

- **Do not create a shared/base wire schema across shapes.** Repeated lifecycle and timer message definitions in `shape_log`, `shape_atom`, and `shape_swmr` are intentional self-contained registries required by D21 (`TautClientImplPlan.md:228`). A source-authoring helper is acceptable only if it emits byte-identical independent IR and does not create a wire inheritance contract.
- **Do not merge the semantic store cores.** The roadmap correctly concludes that the engine frame generalizes but the append window, latest-value slot, and snapshot+delta/reset stores do not (`TautShapeRoadmap.md:236-279,399-412`). Share bookkeeping, not resolution semantics.
- **Do not replace native language engines with one foreign runtime.** Independent Rust, TypeScript, and Python implementations are the point of the oracle and live matrix; their no-std, JS, and Python data structures have different legitimate constraints.
- **Do not deduplicate authored JSON scripts into an opaque scenario DSL.** Their repetition is reviewable contract evidence. Consolidate generator plumbing, while keeping each input sequence explicit and diffable.
- **Do not remove the value/fold overlap merely to reduce vector count.** `corpus/README.md:121-140` documents the intentional two granularities: message protocol versus raw fold. The extra checks are cheap and validate different seams.
- **Do not move reference engines into the canonical repo's public runtime surface.** `taut-shape` is a contract repository; atom/SWMR `*Node` classes are corpus tooling until each language ships an independent engine.
- **Do not weaken whole-transcript equality or deterministic output order.** Those constraints expose control messages such as `CancelTimer`; field-level assertions would hide F4.

## Verdict

**No-go as an implementation-ready multi-shape contract.** Schema/IR export and corpus reproducibility are healthy, but the default live gate is broken, two documented position invariants fail on timed paths, and timer cancellation is inconsistent before any language implementation can independently challenge the new goldens. Fix F1, F2, and F4, add the missing invariant vectors, then use the value vertical slice to turn the current 25% language coverage into an actual multi-shape proof.
