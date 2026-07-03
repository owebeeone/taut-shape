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

**Client termination.** The reading cursor loop treats `eof`/`closed`/`failed`
as the ONLY terminal states — it emits the final `state` and exits. `expired` is
NOT terminal: per D9 the response's `next_cursor` is the earliest resumable
position, so the client advances the cursor to `next_cursor` and re-reads (an
evict mid-stream is survivable). All three client tools (rs/ts/py) implement this
identically — see `scenarios/evict_expired_resume`.

Channels: **data** = `u32-LE length + 1 tag byte + CBOR` frames of the taut
companion messages (the wire under test; the `length` counts the tag byte plus
the CBOR body, min 1, and the tag byte is the `LogMsgType` wire value 0..=11 —
see Oracle §7); **control/result** = OOB JSONL on stderr (each
tool emits its observed transcript). Interop scenarios avoid `timeout_ms > 0`
(real clocks are nondeterministic across processes) — timer behavior is
corpus-only, where `TimerExpired` is a scripted input.
