"""Ensure CI and the installer use the dependencies declared by this revision."""

from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def locked_requirements(filename):
    """Read this project's hashed, unconditional uv requirements lock format."""
    packages = {}
    hashes = None
    for raw in (ROOT / filename).read_text().splitlines():
        line = raw.strip().removesuffix("\\").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash=sha256:"):
            assert hashes is not None, f"{filename}: hash without a package"
            digest = line.removeprefix("--hash=sha256:")
            assert len(digest) == 64
            assert all(c in "0123456789abcdef" for c in digest)
            hashes.add(digest)
            continue
        requirement = Requirement(line)
        assert requirement.marker is None
        assert requirement.url is None
        assert not requirement.extras
        pins = list(requirement.specifier)
        assert len(pins) == 1
        assert pins[0].operator == "=="
        assert "*" not in pins[0].version
        name = canonicalize_name(requirement.name)
        assert name not in packages, f"{filename}: duplicate package {name}"
        hashes = set()
        packages[name] = (pins[0].version, hashes)
    assert packages
    assert all(hashes for _, hashes in packages.values())
    return packages


@pytest.mark.parametrize(
    "lock, manifests",
    [
        ("requirements.lock", ("requirements.txt",)),
        ("requirements-dev.lock", ("requirements.txt", "requirements-dev.txt")),
    ],
)
def test_locks_satisfy_declared_dependencies(lock, manifests):
    packages = locked_requirements(lock)
    for manifest in manifests:
        for raw in (ROOT / manifest).read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            assert requirement.marker is None
            assert requirement.url is None
            assert not requirement.extras
            name = canonicalize_name(requirement.name)
            assert name in packages, f"{manifest}: {name} missing from {lock}"
            version, _ = packages[name]
            assert requirement.specifier.contains(version, prereleases=True), (
                f"{lock} pins {name}=={version}, outside {manifest}'s {requirement.specifier}; "
                "regenerate both locks"
            )


def test_ci_and_installer_use_identical_runtime_versions_and_hashes():
    runtime = locked_requirements("requirements.lock")
    development = locked_requirements("requirements-dev.lock")
    for name, identity in runtime.items():
        assert development.get(name) == identity, (
            f"CI and the installer disagree on {name}; compile the dev lock with "
            "-c requirements.lock"
        )
