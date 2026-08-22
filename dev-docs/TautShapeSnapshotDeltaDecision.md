# Snapshot-Delta Profile Decision

Date: 2026-08-22  
Contract: `snapshot_delta.profile/v1`  
Core: `swmr.oracle/v1`

## Decision

`snapshot_delta` is a fixed public `expire` recovery profile over the one SWMR
store/session/resolver core. It is not a second engine and has no independent
wire schema. The internal companion protocol remains `shape_swmr`; the profile
boundary projects any SWMR `state=reset` response to an out-of-band
`refresh_required` result and never exposes that reset, its replacement state,
or producer reset detail as an application event.

The closed construction selector is:

| Public shape | Core recovery selector | Default delta bound |
| --- | --- | --- |
| `swmr` | `repair` | unbounded unless configured |
| `snapshot_delta` | `expire` | 64, positive and configurable |

Both profiles use the same writer binding, reset epoch, sequence allocation,
snapshot re-base, delta retention, cursor resolver, held-read/timer table, and
terminal lifecycle. Profile implementations may wrap/project core output; they
must not copy any of those mechanisms.

## Public surface

Producer/core inputs are `snapshot_push`, `delta_push`, `reset`, `seal`, and
`close`. Reader/runtime inputs are `read`, `end_stream`, and `timer_expired`.
`reset` is a core-side source-change signal; it is not a consumer application
event in this profile. Consumer-visible outcomes are ordinary snapshot/delta
`read_response` values, terminal states, diagnostics, and the out-of-band:

```text
refresh_required {
  swmr_id,
  stream_id,
  reason: retention_expired | invalid_cursor | source_changed
}
```

The reason projection is fixed:

| Internal SWMR reset reason | Profile outcome |
| --- | --- |
| `retention_exceeded` | `retention_expired` |
| `invalid_resume_seq` | `invalid_cursor` |
| `producer_requested` | `source_changed` |

The profile stops that read attempt at `refresh_required`; an application uses
its external refresh source and begins a fresh subscription with an absent
cursor. It must not continue from the in-band repair snapshot/cursor that SWMR
would have supplied.

## Conformance and shared-core evidence

Four authored vectors in `corpus/scripts_snapshot_delta/` generate
`corpus/snapshot_delta.profile.v1.json`. They cover all three changed reason
projections plus unchanged normal snapshot/delta/terminal delivery. Each Rust,
TypeScript, and Python profile test constructs the fixed `expire` wrapper and
drives the vector inputs through its contained `SwmrNode`; there is no second
resolver or store type. Structural coverage therefore reaches the same core
`handle`/resolver paths used by the 33 SWMR vectors, then only the output
projection branch differs.

The live matrix registers the public name `snapshot_delta` and runs normal
delivery, retention expiry, and reset-between-polls across all nine language
node/client pairs. The internal node sends the shared SWMR companion frames; the
selected profile client proves that no raw reset or reset detail crosses the
application transcript.
