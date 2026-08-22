from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from release.check_compatibility import check_compatibility, is_release_pin

ROOT = Path(__file__).resolve().parents[1]


def load_manifest() -> dict:
    return json.loads((ROOT / "release" / "compatibility.v1.json").read_text())


def workspace_repos() -> dict[str, Path]:
    workspace = ROOT.parent
    return {
        "taut-shape-rs": workspace / "taut-shape-rs",
        "taut-shape-ts": workspace / "taut-shape-ts",
        "taut-shape-py": workspace / "taut-shape-py",
        "glial": workspace / "glial",
    }


def test_current_development_manifest_is_in_lockstep() -> None:
    assert check_compatibility(load_manifest(), ROOT, workspace_repos()) == []


def test_corpus_version_drift_is_rejected() -> None:
    manifest = deepcopy(load_manifest())
    manifest["contracts"][0]["corpora"][0]["version"] = "atom.oracle/v999"
    errors = check_compatibility(manifest, ROOT, workspace_repos())
    assert any("corpus version" in error for error in errors)


def test_release_mode_rejects_development_versions_and_pins() -> None:
    errors = check_compatibility(
        load_manifest(),
        ROOT,
        workspace_repos(),
        release=True,
        check_cleanliness=False,
    )
    assert any("manifest status" in error for error in errors)
    assert any("development package version" in error for error in errors)
    assert any("development-only pin" in error for error in errors)


def test_release_pin_accepts_initial_semver_but_not_zero_or_paths() -> None:
    assert is_release_pin("0.1.0")
    assert is_release_pin("^0.2.3")
    assert not is_release_pin("0.0.0")
    assert not is_release_pin("workspace:*")
    assert not is_release_pin("file:../taut-shape-ts")
