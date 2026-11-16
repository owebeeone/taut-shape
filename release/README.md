# Release compatibility manifest

The prepared train targets `0.12.0` and remains `candidate`. Protocol and shape
artifacts share major/minor coordinates; patch releases can advance independently.
The manifest also records the canonical Rust foundation version and the Rust
shape dependency on it. Python fallback versions express source-export intent;
Git builds continue deriving their actual distribution versions from tags.

Run the version/corpus/consumer consistency checks from this repository:

```sh
python release/check_compatibility.py --contract-version 0.12.0
pytest release/test_compatibility.py -q
```

The separate `--release` check still requires a completed release status and clean
release inputs. Preparing version declarations does not satisfy that gate.

## Publication-dependent lockfiles

The new `taut-foundation` and npm shape versions must exist in their registries
before the corresponding registry-only lockfiles can be regenerated. Until then,
`taut-shape-rs/Cargo.lock` and `glial/pnpm-lock.yaml` retain their previous resolved
state and are not 0.12 release receipts. Do not fabricate checksums or commit a
local-path resolution as a registry lock. The Rust dependency can be tested with
an isolated Cargo patch while the foundation is unpublished.

After the approved workflow publishes the foundation, refresh the Rust shape lock
with `cargo update -p taut-foundation --precise 0.12.0` and rerun the locked checks.
After the npm shape package is published, refresh Glial's lock with
`pnpm install --lockfile-only --ignore-scripts` and rerun its frozen install and
consumer checks. The TypeScript shape package's root version change requires no
lockfile edit because its unchanged development dependencies retain their pins.

Commit candidate sources and refresh the compiler's immutable sibling inputs,
then execute the prescribed strict package and release gates. No tag or registry
publication is implied by these metadata edits.
