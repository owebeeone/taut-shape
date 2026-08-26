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
        "taut": workspace / "taut",
        "glial": workspace / "glial",
    }


def test_current_release_manifest_is_in_lockstep() -> None:
    assert check_compatibility(load_manifest(), ROOT, workspace_repos()) == []


def test_corpus_version_drift_is_rejected() -> None:
    manifest = deepcopy(load_manifest())
    manifest["contracts"][0]["corpora"][0]["version"] = "atom.oracle/v999"
    errors = check_compatibility(manifest, ROOT, workspace_repos())
    assert any("corpus version" in error for error in errors)


def test_release_mode_rejects_candidate_status_and_development_pins() -> None:
    manifest = deepcopy(load_manifest())
    manifest["status"] = "candidate"
    manifest["consumers"][0]["pin"].update(
        {"kind": "development-workspace", "specifier": "workspace:*"}
    )
    errors = check_compatibility(
        manifest,
        ROOT,
        workspace_repos(),
        release=True,
        check_cleanliness=False,
    )
    assert any("manifest status" in error for error in errors)
    assert any("development-only pin" in error for error in errors)
    assert not any("development package version" in error for error in errors)


def test_release_train_and_protocol_dependency_drift_are_rejected() -> None:
    manifest = deepcopy(load_manifest())
    manifest["packages"]["rust"]["version"] = "0.10.0"
    manifest["packages"]["python"]["dependencies"]["taut-proto"] = ">=0.9.0,<0.10"
    errors = check_compatibility(manifest, ROOT, workspace_repos())
    assert any("outside the 0.9 release train" in error for error in errors)
    assert any("dependency taut-proto specifier" in error for error in errors)


def test_release_pin_accepts_initial_semver_but_not_zero_or_paths() -> None:
    assert is_release_pin("0.1.0")
    assert is_release_pin("^0.2.3")
    assert not is_release_pin("0.0.0")
    assert not is_release_pin("workspace:*")
    assert not is_release_pin("file:../taut-shape-ts")
