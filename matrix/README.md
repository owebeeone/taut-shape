# matrix — the interop matrix

The corpus proves each engine against the spec *alone*; the matrix proves the
engines against *each other*, live, over the real wire framing. See
[`../dev-docs/TautShapeOracle.md`](../dev-docs/TautShapeOracle.md) §7.

- `driver.py` — the shape-neutral registry/runner. It runs `node(X) ⊗ client(Y)`
  for every registered shape scenario and language pair
  `X, Y ∈ {rs, ts, py}` (same-language pairs are baselines).
- `harness.py` — process startup, crossed-pipe transport, concurrent draining,
  timeouts, and unconditional child/pipe cleanup. It has no shape or message
  knowledge.
- `shapes.py` — the minimal `MatrixShape`/`MatrixCase` registration contract.
- `atom_shape.py`, `crdt_shape.py`, `log_shape.py`, `snapshot_delta_shape.py`,
  `stream_shape.py`, `swmr_shape.py`, and `value_shape.py` — shape-specific scenario loading and
  transcript canonicalization.
- `scenarios/` — deterministic node/client interop scenarios (the `--scenario`
  file scripting the producer: push/seal/close interleaved against read counts).
- `fixtures/smoke_tool.py` and `test_harness.py` — a live non-log fixture plus
  partial-start and protocol-failure process-leak regressions.

Every registered command receives `--shape <name>` explicitly. Adding a shape
means adding one `MatrixShape` registration with its scenario loader and
canonicalizer; the process harness and language-pair loop remain unchanged.

CRDT clients are real second replicas: their replica script is applied locally
and sent to the node, the node's missing operations are applied back through the
client engine, and the transcript ends in a canonical clock/op/diagnostic set.
Text scenarios additionally compare the shared text projection. Eight scenarios
therefore contribute 72 live cross-language cells.

Run the live table directly, or run all matrix and harness regressions with
pytest:

```sh
python3 matrix/driver.py
pytest matrix/driver.py matrix/test_harness.py -q
```

**The py child environment is self-sufficient.** `taut-shape-py`'s
`taut_shape.tool` transitively imports the sibling `taut` runtime
(`taut.wire.codec`, `taut.ir.load`, ...), which is not vendored into
`taut-shape-py`. `driver.py` therefore prepends BOTH `taut-shape-py/src` and
the sibling `<taut-dev>/taut/src` to `PYTHONPATH` for every "py" child process
(derived from the same `_TAUT_DEV` root the driver already computes — never
hardcoded to a particular user's absolute path). The default
`python3 matrix/driver.py` / `pytest matrix/driver.py` invocations must pass
without relying on an ambiently-installed `taut` distribution.

**Preflight.** Before running any pairing, the driver import-checks
`taut_shape.tool` once, in the exact child environment described above. If
the sibling `taut` checkout is missing (or otherwise unimportable), this
fails fast with ONE diagnostic naming the missing module and every
`PYTHONPATH` entry that was attempted, instead of producing up to 20
derivative pairing failures across the py-involving node/client
combinations. Under pytest this aborts the whole session (`pytest.exit`)
before any `test_matrix` case runs; the plain runner (`__main__`) prints the
same diagnostic to stderr and exits non-zero before the pass table starts.

**Missing tool binaries fail their cell, not the run.** If a language's CLI
tool cannot be spawned (e.g. an unbuilt `taut-shape-rs` binary — `Popen`
raises `FileNotFoundError`/`OSError`), only that (node, client, scenario)
cell is marked failed (`FAIL (tool missing): ...`); the table and the pytest
parametrization continue through every other pairing. This matters most on a
partially built workspace where only some of the three language tools are
available.

If the node starts but the client does not, or if either peer times out during
startup, protocol exchange, or pipe drain, `harness.py` kills and reaps every
started child and closes all six parent-owned pipe endpoints in a `finally`
path. The live smoke regression records child PIDs and proves no process remains.

**Client termination.** The log reading cursor loop treats `eof`/`closed`/`failed`
as the ONLY terminal states — it emits the final `state` and exits. `expired` is
NOT terminal: per D9 the response's `next_cursor` is the earliest resumable
position, so the client advances the cursor to `next_cursor` and re-reads (an
evict mid-stream is survivable). All three client tools (rs/ts/py) implement this
identically — see `scenarios/evict_expired_resume`. Atom clients additionally
support repeatable reader ids and finish a timed read attempt on `would_block`.
Stream clients expose bounded live-delivery behavior: the matrix deliberately
pauses one of two readers until it receives `dropped/slow_consumer`, then proves
that reconnect joins at the current head and receives only the next live record.
The five stream and five SWMR scenarios contribute 45 live cells each; the
three snapshot-delta profile scenarios add 27. The full matrix has 243 live
cells and three harness regressions.

Channels: **data** = `u32-LE length + 1 tag byte + CBOR` frames of the selected
shape's Taut companion messages (the wire under test; the `length` counts the
tag byte plus the CBOR body, min 1, and the tag byte is the selected message-type
enum value — see Oracle §7); **control/result** = OOB JSONL on stderr (each
tool emits its observed transcript). No scenario depends on a real clock. The
atom and stream timer cases request a positive timeout but inject
`TimerExpired` deterministically from the script.
