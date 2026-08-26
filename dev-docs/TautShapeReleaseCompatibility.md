# Taut Shape Release Compatibility

Status: `0.9.*` release in progress; Rust is published, TypeScript and Python remain in progress

Date: 2026-08-25

Machine-readable source and gate:
`release/compatibility.v1.json` and `release/check_compatibility.py`

## Contract and language packages

Every active engine/profile row is implemented by all three language packages.
The coordinated Taut train fixes major/minor at `0.9` while allowing patch
versions to advance independently. The release coordinates are `taut-proto
0.9.1`, contract tag `v0.9.0`, `taut-shape 0.9.0` in Rust and TypeScript, and
`taut-shape 0.9.1` in Python. Rust 0.9.0 and the protocol are published;
TypeScript 0.9.0 is tagged; Python 0.9.1 is the corrected publication candidate.

| Public shape/profile | Catalogue contract | Oracle corpus | Rust package | TypeScript package | Python package |
| --- | --- | --- | --- | --- | --- |
| `value` | `v0` | `value.oracle/v0` | `taut-shape 0.9.0` | `@owebeeone/taut-shape 0.9.0` | `taut-shape 0.9.1` SCM release coordinate |
| `atom` | `v1` | `atom.oracle/v1` | same | same | same |
| `log` | `v1` | `log.oracle/v0` | same | same | same |
| `stream` | `v1` | `stream.oracle/v1` | same | same | same |
| `swmr` | `v1` | `swmr.oracle/v1` | same | same | same |
| `snapshot_delta` | `v1` | `snapshot_delta.profile/v1` | same SWMR core | same SWMR core | same SWMR core |
| `crdt` | `v1` | `crdt.oracle/v1`; `crdt.convergence/v1` | same | same | same |
| `text_crdt` | `v1` | `text_crdt.profile/v1` | same CRDT core | same CRDT core | same CRDT core |

The differing `log` catalogue/oracle suffixes are intentional historical
identifiers, not a mismatch: the catalogue metadata was normalized to `v1`
after the already-ratified `log.oracle/v0` corpus was published internally.
The compatibility manifest pins both independently.

## Consumer pins and gates

| Consumer | Current status | Shapes crossed | Development pin | Continuous gate | Release disposition |
| --- | --- | --- | --- | --- | --- |
| Glial | private `0.0.0` | `value`, `log`, `atom`, `stream`, `crdt`, `text_crdt` | local `file:../taut-shape-ts` | typecheck + full Glial suite; full log applicability gate | MUST move to a released TypeScript semver before Glial release |
| Gryth | private `0.0.0` | first cutover: workspace-name `value` | `workspace:*` Glial member; GWZ lock records clean Glial commit `b3ee6658…` | full Gryth test/build/lint workflow | MUST move to a released Glial semver before Gryth release |
| Datascad | prototype workspace with no release commit | `atom`, `swmr`, `snapshot_delta` | exact development content pin in `TAUT_PIN.json` | adapter + SQLite SWMR runtime selftests | explicitly not a release input; MUST re-pin to released packages/contracts first |

No released consumer currently relies on a path or content hash: all three rows
are explicitly development/private/prototype. The gate prevents those statuses
from being relabelled as a release accidentally.

## Enforced transition to a release

Normal CI runs:

```sh
python3 release/check_compatibility.py
```

It fails on catalogue/manifest disagreement, missing IR, corpus-version drift,
protocol/shape release-train drift, language-package version drift, consumer
dependency drift, or missing CI workflows. It also verifies the Python shape
package's `taut-proto>=0.9.1,<0.10` dependency. Contract CI regenerates every
IR/corpus, tests all three engines, and runs both the full and
dependency-isolated live matrices. Glial and Gryth own selected consumer
workflows in their repositories.

Every version tag additionally runs:

```sh
python3 release/check_compatibility.py --release
```

Release mode MUST fail unless:

1. the compatibility manifest says `released`;
2. `taut-proto`, the contract coordinate, and all three language packages are
   non-development versions in the `0.9.*` release train;
3. every participating consumer uses a nonzero semver package pin rather than
   `file:`, `link:`, `workspace:`, a Git hash, or an artifact-content hash; and
4. the contract, language, and required consumer Git trees are clean.

This ordering makes schema/corpus and pin drift fail before any consumer release.
The Python `v0.9.0` workflow stopped before publication because its wheel relied
on sibling contract files. That immutable tag is retained for auditability;
0.9.1 bundles the canonical schemas and adds an isolated-wheel gate. Publishing
TypeScript and Python, converting consumer development pins, and finalizing the
contract remain outstanding release operations.
