# matrix — the interop matrix

The corpus proves each engine against the spec *alone*; the matrix proves the
engines against *each other*, live, over the real wire framing. See
[`../dev-docs/TautShapeOracle.md`](../dev-docs/TautShapeOracle.md) §7.

- `driver.py` — the Python runner (pytest, `test_kotlin.py`-style: spawn the
  per-language `taut-shape-<lang>` CLI tools, assert on structured output). It
  runs `node(X) ⊗ client(Y)` for every language pair `X, Y ∈ {rs, ts, py}`
  (same-lang pairs are baselines), crossing stdin/stdout pipes and draining them
  concurrently.
- `scenarios/` — deterministic node/client interop scenarios (the `--scenario`
  file scripting the producer: push/seal/close interleaved against read counts).

Channels: **data** = `u32-LE length + CBOR` frames of the taut companion
messages (the wire under test); **control/result** = OOB JSONL on stderr (each
tool emits its observed transcript). Interop scenarios avoid `timeout_ms > 0`
(real clocks are nondeterministic across processes) — timer behavior is
corpus-only, where `TimerExpired` is a scripted input.
