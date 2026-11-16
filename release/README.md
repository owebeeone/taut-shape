# Release compatibility manifest

The `0.12.0` compiler, foundation and three shape-library artifacts are published
and verified. Glial's separate Glade assistance dependency is now released as
`@owebeeone/glade-decl 0.2.0`, its consumer checks pass, and the compatibility
manifest is `released`. See the [publication and finalization record](0.12.0.md)
for exact evidence and checks.

Protocol and shape artifacts share major/minor coordinates; patch releases can
advance independently. The manifest records the canonical Rust foundation
version and the Rust shape dependency on it. Python fallback versions express
source-export intent; Git builds derive their distribution versions from tags.

Run the version/corpus/consumer consistency checks from this repository:

```sh
python release/check_compatibility.py --contract-version 0.12.0
pytest release/test_compatibility.py -q
```

The separate `--release` check requires completed release status and clean
release inputs. Gearu runs it before tagging the contract release and again
on the exact release candidate.

## Publication-dependent lockfiles

The foundation was published before `taut-shape-rs/Cargo.lock` was refreshed
with `cargo update -p taut-foundation --precise 0.12.0`. The locked Rust checks
then passed against its registry artifact. Glial's lock was refreshed with
`pnpm install --lockfile-only --ignore-scripts` after the npm shape artifact
became available; it now resolves the registry version rather than a local path.
Do not fabricate checksums or replace registry locks with local resolutions.

The TypeScript shape package's root version change requires no lockfile edit
because its unchanged development dependencies retain their pins. The compiler's
immutable sibling inputs identify its original clean release candidates; later
registry lock and publication-record commits do not move that compiler tag.
