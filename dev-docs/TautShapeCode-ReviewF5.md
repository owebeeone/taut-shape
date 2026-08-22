# TautShapeCode-ReviewF5 — "anew" review of taut-shape (pre-existing + new)

## 1. Header

- **Designator:** F5. **Date:** 2026-07-19.
- **Base commit:** `389c867` (taut-shape fold oracle P2.S1). Working tree additionally
  contains the uncommitted atom/swmr work, all reviewed as one body of code:
  - Modified: `README.md`, `corpus/README.md`, `dev-docs/TautShapeOracle.md`, `ir/regen.py`.
  - New: `ir/shape_atom.taut.py`, `ir/shape_atom.ir.json`, `ir/shape_swmr.taut.py`,
    `ir/shape_swmr.ir.json`, `corpus/atom_gen.py`, `corpus/atom.v0.json`,
    `corpus/scripts_atom/` (21 scripts), `corpus/swmr_gen.py`, `corpus/swmr.v0.json`,
    `corpus/scripts_swmr/` (22 scripts), `dev-docs/AtomSwmrNotes.md`.
    (`dev-docs/TautShapeCodeReviewPrompt.md` is the review brief itself, not reviewed.)
- **Baseline validation runs** (macOS, python3, node v22.19.0, prebuilt
  `taut-shape-rs/target/debug/taut-shape-tool` of 2026-07-07): **all green.**

  | Gate | Result |
  |---|---|
  | `python3 ir/regen.py --check` | PASS — 4/4 IR files in lockstep (log, value, atom, swmr) |
  | `python3 corpus/gen.py --check` | PASS (27 s wall; drives the Rust tool's `node` mode) |
  | `python3 corpus/value_gen.py --check` | PASS |
  | `python3 corpus/fold_gen.py --check` | PASS, **and** "agrees with glade's frozen oracle" |
  | `python3 corpus/atom_gen.py --check` | PASS |
  | `python3 corpus/swmr_gen.py --check` | PASS |
  | `python3 matrix/driver.py` | PASS — 36/36 (4 scenarios × 9 `node(X)⊗client(Y)` pairings, rs/ts/py) |

  Corpus inventory verified: log 25 vectors, value 11, fold 12, atom 21, swmr 22;
  every corpus's vector order equals its sorted script order; every `version` pin
  matches its README claim.

## 2. Verdict

The codebase is in very good health: every lockstep gate and the full 36-pairing
interop matrix pass, the new atom/swmr work mirrors the established schema and
generator idioms with unusual fidelity, and the D-numbered decision-comment
discipline is carried through consistently. There are **no efficiency problems**
— nothing at or above O(n²) on an unbounded dimension exists anywhere in the
repo (audit in §4). The two real debts are (a) **duplication**: `atom_gen.py`
and `swmr_gen.py` are 77% line-identical after shape-name normalization, and the
`--check` driver skeleton now exists in five near-identical copies; and (b)
**coverage**: value/atom/swmr exist only as schemas + corpora with Python
references — no rs/ts/py emission, engine, or matrix participation, so the
"shapes emitted for all three supported languages" requirement is met by `log`
alone. A handful of contract-text contradictions in the new swmr work (absent
cursor vs `SwmrReset`, `next_cursor` presence after reset) should be reconciled
by the pending design review before the corpus is treated as load-bearing.

## 3. Findings table

Severity: blocker > major > minor > nit. Class: consistency / efficiency /
reuse / coverage / correctness. IDs are citable as F5-NN.

| ID | file:line | sev | class | description | proposed fix |
|---|---|---|---|---|---|
| F5-01 | repo-wide (see §6) | major | coverage | value/atom/swmr have **no per-language emission, engine, or matrix coverage** in any of rs/ts/py; each schema's own docstring pins `-l python,typescript,rust` regeneration (`ir/shape_atom.taut.py:54-55`) and the plan obliges per-language conformance (`TautClientImplPlan.md:232-251`), but the sibling repos are strictly log-only (verified: `taut-shape-rs/crates/taut-shape/src/` has only `log/` + `generated.rs`; `taut-shape-ts/src/` only `log/` + `taut/gen/shape_log.ts`; `taut-shape-py/src/taut_shape/` only `log/`). | Work items itemized in §6; first mover per `TautShapeGladeConsolidation.md:169-177` is de-log-hardwiring the rs/ts CLIs. |
| F5-02 | `ir/shape_swmr.taut.py:54-56` vs `:172-173`; `corpus/swmr_gen.py:223-230` | major | consistency/correctness | Contract text self-contradicts: the schema docstring (and `swmr_gen.py:91-94`) says an ABSENT cursor "NEVER produces `reset`", but the `SwmrReset` field comment says it "Answers **every** currently held read with `state=reset`", and `SwmrNode._reset` implements the latter — a held absent-cursor read (held ⇒ no snapshot exists) answered during a producer `SwmrReset` would get `reset`. Latent: no vector pins an absent-cursor hold across a reset. | Design review (AtomSwmrNotes queue) picks a side; then either scope the docstring's "never" to positional resets (`retention_exceeded`/`invalid_resume_seq`) or make `_reset` re-resolve absent-cursor holds; add the missing vector either way. |
| F5-03 | `corpus/swmr_gen.py:228` vs `:316-317`; pinned in `corpus/swmr.v0.json` `generation_change_reset` | major | consistency/correctness | `next_cursor` presence is inconsistent in the identical engine state: the reset response hardcodes `next_cursor={seq:0}` while the immediately following probe (same state: no snapshot) emits `next_cursor=null` — and `AtomSwmrNotes.md:134-140` (#8) says absent "exactly when no snapshot has ever been established", which matches neither. Worse, `{seq:0}` is precisely the "claimed stale position" (`ir/shape_swmr.taut.py:126-133` analogue of notes #7) that resolves to `reset(retention_exceeded)` once the next snapshot lands — the engine hands the reader a cursor guaranteeing a second reset. Already pinned in the committed corpus, so fixing later costs an oracle bump. | Decide the invariant ("present iff a snapshot currently exists" is the only self-consistent reading), make `_reset` emit `next_cursor=None`, regenerate + bump `swmr.oracle/v0` before it is consumed anywhere. |
| F5-04 | `dev-docs/AtomSwmrNotes.md:3-6` vs `dev-docs/TautShapeRoadmap.md:222-231, 525-531, 550-553` | major | consistency | The notes claim to record "every place §1/§3 left a decision open, and every deliberate divergence" — but the roadmap's swmr sketch includes `window.update` reader-steering and ranks the resulting disposability question **D25 [HIGH]**, plus the D28 recommendation (`snapshot_delta` = `reset_policy` profile of one engine); the delivered schema silently omits both (no window concept, no reset_policy knob) with no numbered note. | Add two notes recording the decisions (e.g. "window steering dropped for v0 → swmr streams stay disposable, D25 resolved as (a)-trivially"; "snapshot_delta profile deferred"), keeping the notes' completeness claim true. |
| F5-05 | `corpus/atom_gen.py:222-235`; `corpus/swmr_gen.py:331-334`; `corpus/scripts/20b_never_read_no_stop.json` | major | reuse | `atom_gen.py` and `swmr_gen.py` are near-clones: 265 of atom_gen's 345 lines (77%) are line-identical with swmr_gen after shape-name normalization (`main`/`_corpus_text`/`_load_schema` are exact modulo names); the whole `_Held`/codec-roundtrip/session-table/`--check` apparatus is duplicated, and value_gen shares 109/189 lines of the same skeleton. Fifth shape (`stream`, roadmap §2) would copy again. | Extract `corpus/_gen_common.py` (§5 R1): codec helpers + held-read session mixin + shared `run_gen()` driver. Byte-identical corpora provable via the existing `--check` gates. |
| F5-06 | `corpus/atom_gen.py` (no script), `ir/shape_atom.taut.py:78-80`; `corpus/swmr_gen.py:331-334`, `ir/shape_swmr.taut.py:109-112`; `corpus/scripts_atom/`, `corpus/scripts_swmr/` | minor | coverage | Three documented behaviors are implemented but **unpinned by any vector**: (a) atom's `version > current` clamp (AtomSwmrNotes #3); (b) swmr's `invalid_resume_seq` reset reason — corpus scan confirms only `producer_requested` and `retention_exceeded` ever appear; (c) the D6 "never-read log emits no ProducerStop" variant exists for log (`20b`) but has no atom/swmr counterpart despite the claimed "full log/atom-parity lifecycle set" (`corpus/README.md:80-84`). A future rs/ts engine can diverge on all three undetected. | Add ~4 scripts: atom read `version>current`; swmr read past head; atom+swmr `end_stream` on a never-read node. Also worth pinning: post-close `end_stream` double-`ProducerStop` (verified consistent, §8.9). |
| F5-07 | `corpus/atom_gen.py:176→243`; `corpus/swmr_gen.py:243→344-345` | minor | correctness | Native/jsoncodec form mixing: `close_error` is captured in **native** form (`n.get("error")`) and later embedded into a **jsoncodec-form** output dict fed back through `from_json_value`. It works only because `AtomError`/`SwmrError` happen to contain only STR + enum fields (identical in both forms — verified against `taut/src/taut/wire/jsoncodec.py`); a future BYTES field (e.g. an opaque `detail`) would be silently corrupted (`b64decode` of raw bytes) rather than fail loudly. Same latent pattern for `_reset`'s `reason` (enum — safe by construction). | Capture the jsoncodec form instead: `self.close_error = msg.get("error")` (the raw input already is jsoncodec-form), or convert at the boundary with `to_json_value`. |
| F5-08 | `corpus/gen.py:75-91` vs `ir/shape_log.taut.py:53-58` | minor | reuse/consistency | `_TYPE` hand-duplicates every `LogMsgType` wire tag from the schema; a renumbering lands in two places or drifts (caught only at runtime decode of a mismatched frame). The member→message-name half is genuinely non-mechanical (`read`→`LogReadRequest`) and must stay a table; the tag half is derivable from the loaded IR. | Build tags from the IR enum at load time: `tags = schema.enums["LogMsgType"]`-equivalent lookup; keep only the name map by hand. |
| F5-09 | `README.md:6` | minor | consistency | "it holds **no** engine code of its own" is now literally false: `AtomNode` (`corpus/atom_gen.py:96`), `SwmrNode` (`corpus/swmr_gen.py:107`) and the value `Register` are engines living in this repo. Every other doc qualifies correctly ("no *shipped* engine", `corpus/atom_gen.py:20-22`, Oracle §5, notes #13); the front-page claim was not updated by the new work. | Amend to "no shipped engine code of its own (reference engines embedded in corpus generators are gen-tooling only)". |
| F5-10 | `dev-docs/TautShapeOracle.md:337-339`, `corpus/README.md:16-18` vs `taut-shape-rs .../main.rs:76-80`; `TautShapeOracle.md:373-374`, `TautClientImplPlan.md:239-248` | minor | consistency/coverage | Docs-vs-reality on tooling: the Oracle/corpus README say the log corpus is generated by "`taut-shape-rs`'s **`gen` mode**", but the rs tool's `gen` and `check` modes are stubs — generation is actually `corpus/gen.py` replaying scripts against the tool's `node` mode; and the "one CLI tool with modes `gen | check | node | client`" obligation is met by no language (ts/py implement `node`/`client` only; their oracle gating lives in test suites instead). Semantics are equivalent (the Rust engine *is* the reference) but the described mechanism doesn't exist. | Reword Oracle §5/§7 + corpus README to name `corpus/gen.py` + `node` mode as the generation path, and either drop the `gen`/`check` mode obligation or mark it aspirational. |
| F5-11 | `ir/shape_value.taut.py:44-45`, `corpus/value_gen.py:16` | nit | consistency | Committed `value` files say "from the taut-dev/**gwz** workspace (root)" where log/atom/swmr all say "taut-dev/taut-shape" / "taut-dev workspace". The new files followed log's (correct) convention; value is the odd one out. | s/taut-dev\/gwz workspace/taut-dev workspace/ in both value files. |
| F5-12 | `dev-docs/TautShapeOracle.md:3` | nit | consistency | Status line still says "aligned with `TautClientImplPlan.md` v2 / **D1–D16**"; the plan now pins D1–D23 and the Oracle itself cites D17/D18/D20. | Update to D1–D23. |
| F5-13 | `ir/shape_swmr.taut.py:177-180` with `:104-112` | nit | consistency | `SwmrReset.reason` reuses the full `SwmrResetReason` enum, so a producer can wire-legally claim the engine-originated reasons (`retention_exceeded`, `invalid_resume_seq`) and the engine echoes them verbatim to readers; the enum's own comment describes those two as engine conditions. Possibly deliberate (one enum, additive growth) — the design review owns the call. | Either document the sharing as intended, or split producer-declarable vs engine-assigned reasons (v0-compatible: keep one enum, have the engine normalize non-`producer_requested` inputs). |
| F5-14 | `corpus/atom_gen.py:322-323`, `corpus/swmr_gen.py:419-420` | nit | consistency | `argparse` continuation style diverges from the house style: new files use single-line `add_argument(..., action=...,` with a 25-space aligned `help=` continuation; gen/value/fold/regen all use the expanded multi-line 8-space-indent form. Old code's side should win. | Reformat the two `add_argument` calls to the expanded form. |
| F5-15 | `ir/shape_atom.taut.py:25,143`, `ir/shape_swmr.taut.py:30,210` vs `ir/shape_log.taut.py:23,127` | nit | consistency | The new schemas ASCII-fy comment notation (`<=1 outstanding`, `>=1->0`) where `shape_log` — the idiom the notes claim to mirror "precisely" — writes `≤1`, `≥1→0`. Cosmetic but systematic. | Match log's unicode in atom/swmr comments (or declare ASCII the standard repo-wide; log is the incumbent). |
| F5-16 | `matrix/driver.py:293-304` | nit | correctness | The plain runner catches only `subprocess.TimeoutExpired`; a missing tool binary (`FileNotFoundError` from `Popen`) aborts the entire table on the first cell instead of FAILing that cell (the pytest path errors similarly). Only matters on a partially built workspace. | Catch `OSError` alongside and render the cell `FAIL (tool missing)`. |

No blocker-severity findings. No correctness bug was found in any committed or
generated artifact; F5-02/F5-03 are contract-text/engine contradictions caught
before any second implementation consumes them.

## 4. Complexity audit (dimension 2, in full)

**Result: no finding at or above O(n²) on an unbounded input dimension.** The
repo's runtime code is generator/driver tooling over small, human-authored
inputs; everything scales linearly in corpus size except the bounded cases
below, each cleared with its bound.

Cleared as FINE (with the n that bounds them):

1. `corpus/value_gen.py:108-115` — `_set` linearly scans accepted ops for the
   `(origin, seq)` dedup/equivocation check: O(k) per set ⇒ O(k²) per vector.
   k = ops per authored vector ≤ 5 in the committed corpus; even a 10³-op
   vector would gen in milliseconds. Fix-if-ever-needed: dict keyed by
   `(origin, seq)`.
2. `corpus/value_gen.py:118-134` — `_read` recomputes `max(...)` and calls
   `fold_value(self.ops)` per read: O(k) per read; reads per vector ≤ 3. The
   recomputation is deliberate (the assert keeps `fold_value` the authority).
3. `corpus/atom_gen.py:257-267`, `corpus/swmr_gen.py:352-362` —
   `_answer_all_held` walks the whole `_order` per producer input: O(S) per
   input, S = live streams (≤ 2 in every vector). Each held read is answered
   exactly once per releasing input — no quadratic accumulation.
4. `corpus/atom_gen.py:274-275`, `corpus/swmr_gen.py:369-370` —
   `_end_stream`'s `self._order.remove(stream_id)`: O(S) list removal. S ≤ 2.
5. `corpus/atom_gen.py:286-293`, `corpus/swmr_gen.py:381-386` —
   `_timer_expired` scans all streams for the token: O(S). A token→stream
   index is the at-scale fix; pointless at S ≤ 2.
6. `corpus/swmr_gen.py:336` — the incremental-catch-up tail
   `[d for d in self.deltas if d[0] > c]` is a linear filter: O(D) per
   resolve, so O(S·D) per push wave, D = retained deltas ≤ 3 in every vector.
   **Template note:** deltas are contiguous by invariant, so this is index
   arithmetic — `self.deltas[max(0, c - snap_seq):]`. Worth doing if this file
   becomes the model rs/ts engines port from (it is the de-facto semantics
   template), not for corpus scale.
7. `corpus/swmr_gen.py:251-274` — `_mk_response` rebuilds the delta list per
   response: O(output size), inherent.
8. `corpus/gen.py:70,170-183` — the QUIET_S=0.3 s quiet-gap drain puts a 0.3 s
   floor under every step: measured 27 s for the 25-vector corpus. Linear with
   a large constant, not a complexity problem; an explicit end-of-step
   sentinel in the tool protocol (or a CLI-tunable gap) would cut gen/check
   ~50× if CI time ever matters.
9. `matrix/driver.py:224-235,244-246` — `load_expected` re-reads and re-parses
   the expected JSON once per pairing: 9× per scenario, 36 tiny (<2 KB) reads
   total. Bounded; hoisting per scenario is trivial if the matrix grows.
10. `matrix/driver.py:91-111,194-221` — relay threads copy in 4 KB chunks;
    `canonicalise` is one pass over transcript lines. O(bytes).
11. `corpus/fold_gen.py:96-129` — conflict guard indexes both oracles by name
    into dicts then compares: O(n), n = 12 vectors.
12. `ir/regen.py:74-91` — one schema import + one export per shape, 4 shapes.
13. String building everywhere is single-shot `json.dumps(...) + "\n"` per
    corpus — no incremental concatenation, no accidental quadratic growth; no
    file is read more than once per gate run in any generator.

## 5. Reuse / refactor proposals (dimension 3)

Measured duplication (difflib LCS, line-identical):
- `atom_gen.py` (345 L) vs `swmr_gen.py` (442 L): 221 raw / **265 after
  shape-name normalization (77% of atom_gen)**. `main`, `_corpus_text`,
  `_load_schema` are exact modulo the shape token; `_replay_script` differs
  only by the `max_deltas` knob.
- `value_gen.py` vs `atom_gen.py` normalized: 109/189 lines (the codec
  round-trip + driver skeleton).
- `gen.py` vs `atom_gen.py` raw: 75/288 (paths/prologue/driver shell).
- The `--check` lockstep `main()` exists in 5 near-identical copies (gen,
  value_gen, fold_gen, atom_gen, swmr_gen) + a 6th variant in `regen.py`.

**R1 — `corpus/_gen_common.py` (do this before shape #5).** One module, three
layers, all provable byte-identical via the existing `--check` gates:

```python
# corpus/_gen_common.py (proposed sketch)

def load_schema(ir_json: Path) -> Schema: ...          # the 3× _load_schema

def native_in(schema, type_to_msg: dict, msg: dict) -> dict: ...   # the 3× _native
def roundtrip_out(schema, msg_to_type: dict, name: str, jv: dict) -> dict: ...  # the 3× _out

class HeldReadSessionMixin:
    """The mailbox session table shared by AtomNode/SwmrNode (and any future
    stateful reference engine): _streams/_order/_next_token bookkeeping,
    _ensure_stream, the _read skeleton (supersede + CancelTimer + hold/SetTimer
    around a shape-supplied _resolve), _answer_all_held, _end_stream
    (incl. stop_when), _timer_expired (via a shape-supplied would_block
    response factory). Shape classes keep: _resolve, producer handlers,
    response construction, the store core."""

def run_gen(*, shape: str, version: str, scripts_dir: Path, out_json: Path,
            make_node: Callable[[dict], Any],          # node_cfg -> engine (or subprocess Node)
            vector_node_field: Callable[[dict], dict | None],  # None => omit (value)
            argv: list[str] | None = None) -> int:
    """The shared driver: argparse --check, sorted-script replay, sort_keys/
    indent=2/trailing-newline serialization, the exact stale/lockstep messages,
    exit codes. gen.py participates by passing its subprocess-backed Node as
    make_node; fold_gen passes its raw-op runner and keeps _conflict_guard as a
    post-check hook (run_gen(..., extra_check=fold_conflict_guard))."""
```

Effect: `atom_gen.py` ≈ 345→180 LOC, `swmr_gen.py` ≈ 442→290, `value_gen.py`
≈ 189→120, plus ~30 each from `gen.py`/`fold_gen.py`; net ≈ −300 LOC and shape
#5 (`stream`) starts from the mixin instead of a fourth copy. **Risk: low.**
The corpora are exact-byte gated, so any behavioral slip in the refactor fails
`--check` immediately; the real risk is future inter-shape coupling (an edit
for shape N perturbing shape M's generator), mitigated by keeping `_resolve`,
producer handlers and the store core strictly per-shape (only bookkeeping is
shared). Do NOT try to absorb the three *generation strategies* themselves
(§8.1) — the shared piece is the skeleton, not the reference sourcing.

**R2 — derive `gen.py`'s wire tags from the IR** (F5-08): drop the hand-copied
tag numbers, keep the name map. ~10 LOC.

**R3 — give `AtomNode` a `_mk_response` factory** like `SwmrNode`'s
(`swmr_gen.py:251`): atom builds its response `jv` dicts inline four times
(`atom_gen.py:229-254, 289-292`). Folds naturally into R1's mixin work.

**R4 — swmr `_reset` should reuse the answer-all-held walk** (`swmr_gen.py:
223-230` duplicates the `_answer_all_held` iteration with a different response
factory) — parameterize the walk, or have `_reset` mark state and delegate.
Folds into R1.

**Refactor order:** R2 (independent, trivial) → R1 driver (`run_gen`, pure
I/O) → R1 codec helpers → R1 mixin + R3 + R4 (the only step with engine-logic
motion; gates prove byte-identity) — each step leaves every `--check` green.

**Explicitly NOT proposed:** unifying the `scripts_*/` JSON boilerplate. The
authored inputs are the human-reviewed contract surface (the `glade_folds`
discipline); the near-duplication across `scripts/07_held_read_timer.json`,
`scripts_atom/07…`, `scripts_swmr/10…` is shape-adapted (different ids, extra
swmr setup steps), and a script-generating DSL would trade reviewability for
nothing. Leave them.

## 6. Language-coverage matrix (dimension 4)

"Supported languages" per the repo itself: **rs, ts, py** — `matrix/driver.py:68`
(`LANGS`), plan §5's tool obligation, and every schema's regeneration footer
(`-l python,typescript,rust`). Requirement under review: shapes emitted for all
three. Reality (all cells verified by listing/grepping the sibling repos and
running the gates):

| shape | schema + IR (this repo) | emitted rs | emitted ts | emitted py | engine rs | engine ts | engine py | corpus (gated) | matrix |
|---|---|---|---|---|---|---|---|---|---|
| log | ✓ `shape_log.taut.py` / `.ir.json` | ✓ `generated.rs` | ✓ `taut/gen/shape_log.ts` | ✓ `log/_generated.py` | ✓ `log/node.rs` | ✓ `log/node.ts` | ✓ `log/engine.py` | ✓ 25 v (Rust ref via `gen.py`) | ✓ 4 scen × 9 pairings green |
| value | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | (ref = `taut.crdt.glade_fold.fold_value` + `Register` glue in `value_gen.py` — not shipped) | ✓ 11 v (py ref) | ✗ (driver log-hardwired) |
| atom | ✓ (new) | ✗ | ✗ | ✗ | ✗ | ✗ | (ref = `AtomNode` embedded in `atom_gen.py` — not shipped) | ✓ 21 v (py ref) | ✗ |
| swmr | ✓ (new) | ✗ | ✗ | ✗ | ✗ | ✗ | (ref = `SwmrNode` embedded in `swmr_gen.py` — not shipped) | ✓ 22 v (py ref) | ✗ |
| (fold layer) | n/a — raw ops, deliberately schema-less | — | — | — | — | — | ref = taut runtime | ✓ 12 v + glade conflict guard | n/a |

So: **atom/swmr (and value) have reference semantics only in the Python
generators; no rs/ts emission or engine anywhere; the matrix covers log only.**
The docs do not overclaim this state (corpus/README and Oracle §5 say it
plainly; `TautShapeRoadmap.md:13` "only `log` exists … all green" is accurate);
the only doc-vs-reality slips found are the mechanism-level ones in F5-09/F5-10.
D23 (per-shape module namespacing before shape #2) is already satisfied in all
three sibling repos (`log/` modules everywhere).

**Gap work items** (minimal, per gap; LOC scales from
`TautShapeGladeConsolidation.md:133-177`'s value assessment):

1. **Shared prerequisite (all shapes):** de-log-hardwire the three CLIs
   (`main.rs`/`cli.ts`/`taut_shape.tool.main`) — mode dispatch + framing over a
   shape parameter (per-shape `MsgType` tag map). The consolidation doc already
   nominates this as the first move.
2. **Per shape × language emission:** run `tautc gen` on
   `shape_{value,atom,swmr}.ir.json`, vendor as `generated_<shape>.rs` /
   `taut/gen/shape_<shape>.ts` / `<shape>/_generated.py`, wire tag maps.
3. **Engines:** port the reference semantics — value ~110–120 LOC/lang
   (consolidation estimate); atom: port `AtomNode` (~150 LOC py ref) ≈ 150–200
   /lang; swmr: port `SwmrNode` (~250 LOC py ref) ≈ 230–300/lang. Each repo
   adds a corpus-replay lockstep test pinning `<shape>.oracle/v0` (the
   `test_lockstep` pattern already present for log).
4. **Matrix:** atom/swmr can reuse the existing held-read/release-after-k
   driver model with a shape parameter + per-shape scenarios; value cannot
   (immediate probes — needs the "client sets N, probes" driver variant the
   consolidation doc sketches, ~150 LOC + scenarios).
5. **Sequencing:** value first (smallest engine, driver variant already
   scoped), then atom (proves the mixin-shaped port), then swmr. This is also
   the roadmap's own risk ordering.

## 7. Consistency notes (dimension 1 residue)

What the new code got **right** (worth saying so a fixer doesn't churn it):
the atom/swmr schemas reproduce shape_log's layer ordering, enum-registry
idiom, opaque-BYTES payload pattern, D-citation density and docstring
structure almost exactly; all five corpora share one serialization convention
(`sort_keys=True, indent=2`, trailing newline, `<shape>.oracle/v0` pins);
`--check` UX text is uniform across all six gates; vector order equals script
order everywhere; supersede output ordering (`cancel_timer` then `set_timer`),
close-after-seal `ProducerStop{closed}`, and idempotent-teardown emissions are
byte-consistent across the three mailbox corpora (verified above).

Residue not in the table:

- **Section-divider styles:** `gen.py`/`driver.py` use `# ── … ` box-drawing
  rules; `value_gen`/`atom_gen`/`swmr_gen` use `# -- … ---` ASCII. The new
  files followed value_gen's side. Two committed styles pre-exist, so neither
  side "yields"; pick one when R1 lands (the shared module will set it).
- `SwmrNode._mk_response` exists but `AtomNode` inlines its response dicts —
  new-code-internal inconsistency; see R3.
- `_Held.__slots__` appears in the new engines only (value's `Register` has no
  counterpart need) — fine, not a divergence.
- `swmr_gen._replay_script` conditionally includes `max_deltas` in the vector
  `node` field (`swmr_gen.py:399-401`) — correct and matches the corpus; note
  the asymmetry with log/atom (always exactly `{stop_when}`) is knob-driven,
  not accidental.
- The committed value files' "gwz workspace" wording (F5-11) is the only place
  old code should yield to new; everywhere else the new files correctly copied
  the incumbent convention.

## 8. Do-NOT-change list (looks wrong, is right)

1. **Three different generation strategies** (log: external Rust tool over
   frames; value: imported pure fold; atom/swmr: embedded mailbox engines) —
   deliberate and documented three ways (`TautShapeOracle.md` §5,
   `AtomSwmrNotes.md` #13, `corpus/README.md`). Unify the *driver skeleton*
   (R1), never the reference sourcing.
2. **Corpus `in` messages echo the authored form unnormalized** (e.g.
   `log.v0.json` inputs carry authored key order/omissions while outputs are
   codec-normalized). Oracle §3 pins decoded-value comparison, so this is
   sound; "normalizing" inputs would churn every committed corpus for zero
   semantic gain.
3. **`fold.v0.json` hex payloads + raw-int fields** (vs base64/string-i64
   everywhere else) — glade byte-parity requirement; the conflict guard's
   simple `(ops, expect)` compare depends on it (`fold_gen.py` docstring,
   consolidation P2.S1 notes).
4. **`SwmrDelta.base_seq` redundancy** (`== seq-1` always in v0) —
   `AtomSwmrNotes.md` #12: griplab parity + future batching headroom.
5. **value vectors carry no `node` field** — documented format delta
   (`corpus/README.md:28`, Oracle §4b); don't "harmonize" it in.
6. **The `_order` list beside the insertion-ordered `_streams` dict**
   (`atom_gen.py:113-114`, `swmr_gen.py:124-125`) — technically redundant in
   py≥3.7, but it keeps the D16 creation-order rule explicit and mirrors the
   order vector rs/ts engines must maintain anyway. Legibility over 4 lines.
7. **Interop scenarios avoid `timeout_ms > 0`** — deliberate cross-process
   clock-nondeterminism dodge (`matrix/README.md`); timers are corpus-only.
8. **`gen.py`'s QUIET_S quiet-gap drain** — looks like a race-prone hack; it
   is documented, deterministic in effect (the tool flushes synchronously),
   and exact-byte gated. Revisit only if the 27 s gate time hurts (see §4.8).
9. **Double `ProducerStop` (post-close `end_stream` of the last stream emits
   `last_reader_gone` after `closed`)** — I probed the Rust log engine live:
   it does exactly what the new Python engines do, and `ProducerStop` is
   idempotent-by-design (D6). Cross-engine-consistent, currently unpinned; the
   fix is a pinning vector (F5-06), not an engine change.
10. **`.pytest_cache/` absent from the root `.gitignore`** — pytest's own
    dropped `.gitignore` self-ignores the directory; git status is clean. No
    action needed.

---

*Every claim above was verified by reading the cited lines or by running the
listed commands in this session; the only externally-sourced facts are the
sibling-repo listings/greps cited in F5-01/F5-10 and §6 (taut-shape-rs/-ts/-py
file trees, rs tool mode stubs), each individually inspected. Findings resting
on unexercised code paths (F5-02's absent-cursor-hold × reset interaction) are
latent-by-construction and labeled as such; none are speculative.*
