"""Validate contract/package/consumer compatibility and release readiness."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "taut-shape.release-compatibility/v1"
DEVELOPMENT_VERSION = re.compile(r"(?:^0\.0\.0$|dev|snapshot)", re.IGNORECASE)
RELEASE_PIN = re.compile(
    r"^(?:\^|~)?(\d+\.\d+\.\d+)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def is_release_pin(specifier: str) -> bool:
    match = RELEASE_PIN.fullmatch(specifier)
    return match is not None and match.group(1) != "0.0.0"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _version_from_source(repo: Path, source: str) -> str:
    if source == "package-json":
        return str(_read_json(repo / "package.json")["version"])
    if source == "cargo-workspace":
        text = (repo / "Cargo.toml").read_text()
        section = re.search(r"(?ms)^\[workspace\.package\]\s*(.*?)(?=^\[|\Z)", text)
        match = re.search(r'^version\s*=\s*"([^"]+)"', section.group(1) if section else "", re.MULTILINE)
        if not match:
            raise ValueError("Cargo.toml has no [workspace.package] version")
        return match.group(1)
    if source == "setuptools-scm-fallback":
        text = (repo / "pyproject.toml").read_text()
        section = re.search(r"(?ms)^\[tool\.setuptools_scm\]\s*(.*?)(?=^\[|\Z)", text)
        match = re.search(r'^fallback_version\s*=\s*"([^"]+)"', section.group(1) if section else "", re.MULTILINE)
        if not match:
            raise ValueError("pyproject.toml has no setuptools-scm fallback_version")
        return match.group(1)
    raise ValueError(f"unknown version source {source!r}")


def _dependency_spec(repo: Path, package: str) -> str | None:
    package_json = _read_json(repo / "package.json")
    for field in ("dependencies", "peerDependencies", "devDependencies", "optionalDependencies"):
        value = package_json.get(field, {}).get(package)
        if value is not None:
            return str(value)
    return None


def _git_is_clean(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def check_compatibility(
    manifest: Mapping[str, Any],
    contract_root: Path,
    repos: Mapping[str, Path],
    *,
    release: bool = False,
    check_cleanliness: bool = True,
) -> list[str]:
    """Return every drift/release violation without stopping at the first."""

    errors: list[str] = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"manifest schema must be {SCHEMA!r}")

    catalog_path = contract_root / str(manifest.get("catalog_ir", ""))
    try:
        catalog = _read_json(catalog_path)["shapes"]
    except (OSError, KeyError, json.JSONDecodeError) as error:
        return errors + [f"cannot load catalogue IR {catalog_path}: {error}"]

    active_shapes = {
        name
        for name, row in catalog.items()
        if row.get("class") in {"engine", "profile"}
    }
    contracts = list(manifest.get("contracts", []))
    contract_names = [str(row.get("shape", "")) for row in contracts]
    if len(set(contract_names)) != len(contract_names):
        errors.append("contract shape rows must be unique")
    if set(contract_names) != active_shapes:
        errors.append(
            "contract rows do not exactly cover active catalogue shapes: "
            f"manifest={sorted(contract_names)!r}, catalogue={sorted(active_shapes)!r}"
        )

    package_rows = dict(manifest.get("packages", {}))
    for package_id, row in package_rows.items():
        repo_id = str(row.get("repo", ""))
        repo = repos.get(repo_id)
        if repo is None or not repo.is_dir():
            errors.append(f"package {package_id}: repository {repo_id!r} is missing")
            continue
        expected = str(row.get("version", ""))
        try:
            actual = _version_from_source(repo, str(row.get("version_source", "")))
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"package {package_id}: cannot read version: {error}")
            continue
        if actual != expected:
            errors.append(f"package {package_id}: version {actual!r} != manifest {expected!r}")
        if release and DEVELOPMENT_VERSION.search(expected):
            errors.append(f"package {package_id}: development package version {expected!r}")

    expected_package_ids = set(package_rows)
    for row in contracts:
        shape = str(row.get("shape", ""))
        catalog_row = catalog.get(shape, {})
        expected_contract = str(row.get("contract_version", ""))
        if catalog_row.get("contract_version") != expected_contract:
            errors.append(
                f"{shape}: contract version {expected_contract!r} != catalogue "
                f"{catalog_row.get('contract_version')!r}"
            )
        if set(row.get("packages", [])) != expected_package_ids:
            errors.append(f"{shape}: package coverage must include {sorted(expected_package_ids)!r}")
        ir_path = contract_root / str(row.get("ir", ""))
        if not ir_path.is_file():
            errors.append(f"{shape}: missing IR {ir_path}")
        for corpus in row.get("corpora", []):
            corpus_path = contract_root / str(corpus.get("file", ""))
            try:
                actual_version = _read_json(corpus_path).get("version")
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"{shape}: cannot load corpus {corpus_path}: {error}")
                continue
            expected_version = corpus.get("version")
            if actual_version != expected_version:
                errors.append(
                    f"{shape}: corpus version {actual_version!r} != manifest "
                    f"{expected_version!r} for {corpus_path.name}"
                )

    workflow = contract_root / str(manifest.get("contract_workflow", ""))
    if not workflow.is_file():
        errors.append(f"missing contract CI workflow {workflow}")

    checked_repos: dict[str, Path] = {"taut-shape": contract_root}
    checked_repos.update({key: value for key, value in repos.items() if value.is_dir()})
    for consumer in manifest.get("consumers", []):
        name = str(consumer.get("name", "consumer"))
        repo_id = str(consumer.get("repo", ""))
        repo = repos.get(repo_id)
        required = bool(consumer.get("required_in_contract_ci"))
        if repo is None or not repo.is_dir():
            if required:
                errors.append(f"{name}: required consumer repository {repo_id!r} is missing")
            continue

        pin = dict(consumer.get("pin", {}))
        package = pin.get("package")
        if package:
            actual_spec = _dependency_spec(repo, str(package))
            expected_spec = str(pin.get("specifier", ""))
            if actual_spec != expected_spec:
                errors.append(
                    f"{name}: dependency {package} specifier {actual_spec!r} != "
                    f"manifest {expected_spec!r}"
                )
        pin_file = pin.get("file")
        if pin_file and not (repo / str(pin_file)).is_file():
            errors.append(f"{name}: missing pin file {repo / str(pin_file)}")
        consumer_workflow = consumer.get("workflow")
        if consumer_workflow and not (repo / str(consumer_workflow)).is_file():
            errors.append(f"{name}: missing consumer CI workflow {repo / str(consumer_workflow)}")

        if release:
            kind = str(pin.get("kind", ""))
            specifier = str(pin.get("specifier", ""))
            if kind != "semver" or not is_release_pin(specifier):
                errors.append(
                    f"{name}: development-only pin {kind!r}/{specifier!r}; "
                    "released consumers require a nonzero semver package pin"
                )

    if release and manifest.get("status") != "released":
        errors.append(f"manifest status is {manifest.get('status')!r}, not 'released'")

    if release and check_cleanliness:
        for name, repo in sorted(checked_repos.items()):
            if not _git_is_clean(repo):
                errors.append(f"{name}: release input Git tree is missing or dirty")

    return errors


def _parse_repo(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("repository mapping must be NAME=PATH")
    name, path = value.split("=", 1)
    return name, Path(path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--repo", action="append", default=[], type=_parse_repo)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)

    contract_root = Path(__file__).resolve().parents[1]
    manifest_path = args.manifest or contract_root / "release" / "compatibility.v1.json"
    manifest = _read_json(manifest_path)
    workspace = contract_root.parent
    repos: dict[str, Path] = {
        str(row["repo"]): workspace / str(row["repo"])
        for row in manifest.get("packages", {}).values()
    }
    for consumer in manifest.get("consumers", []):
        repo_id = str(consumer.get("repo", ""))
        repos.setdefault(repo_id, workspace / repo_id)
    repos.update(dict(args.repo))

    errors = check_compatibility(manifest, contract_root, repos, release=args.release)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    mode = "release" if args.release else "development"
    print(f"compatibility gate OK ({mode}; {len(manifest['contracts'])} contracts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
