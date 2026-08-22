# Taut Shape Release Compatibility

Status: development compatibility table; no package release has occurred

Date: 2026-08-22

Machine-readable source and gate:
`release/compatibility.v1.json` and `release/check_compatibility.py`

## Contract and language packages

Every active engine/profile row is implemented by all three language packages.
Rust and TypeScript declare `0.0.0`; Python derives an untagged development
version from SCM with a `0.0.0` fallback. These are deliberately development
coordinates while this workspace is uncommitted and unreleased. They MUST be
replaced by matching non-development versions before the manifest status becomes
`released`.

| Public shape/profile | Catalogue contract | Oracle corpus | Rust package | TypeScript package | Python package |
| --- | --- | --- | --- | --- | --- |
| `value` | `v0` | `value.oracle/v0` | `taut-shape 0.0.0` | `@owebeeone/taut-shape 0.0.0` | `taut-shape` SCM development (`0.0.0` fallback) |
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
language-package version drift, consumer dependency drift, or missing CI
workflows. Contract CI also regenerates every IR/corpus, tests all three engines,
and runs both the full and dependency-isolated live matrices. Glial and Gryth own
selected consumer workflows in their repositories.

Every version tag additionally runs:

```sh
python3 release/check_compatibility.py --release
```

Release mode MUST fail unless:

1. the compatibility manifest says `released`;
2. all three language package versions are non-development versions;
3. every participating consumer uses a nonzero semver package pin rather than
   `file:`, `link:`, `workspace:`, a Git hash, or an artifact-content hash; and
4. the contract, language, and required consumer Git trees are clean.

This ordering makes schema/corpus and pin drift fail before any consumer release.
Committing, tagging, publishing packages, and converting the development pins
are release operations outside this uncommitted implementation pass.
