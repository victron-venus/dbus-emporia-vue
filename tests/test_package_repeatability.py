"""Exercise archive determinism and refusal of aliased input without installing."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "package_under_test", Path(__file__).parents[1] / "scripts/package_release.py"
)
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


def test_archive_ignores_source_timestamps_and_preserves_executable_bits(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "config").write_text("public fixture\n")
    (root / "run").write_text("#!/bin/sh\nexit 0\n")
    (root / "run").chmod(0o755)
    first, second = tmp_path / "one.tgz", tmp_path / "two.tgz"
    PACKAGE.write_archive(root, "fixture", ["config", "run"], first)
    for path in root.iterdir():
        os.utime(path, (123, 456))
    PACKAGE.write_archive(root, "fixture", ["config", "run"], second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert archive.getnames() == ["fixture/config", "fixture/run"]
        assert archive.getmember("fixture/config").mode == 0o644
        assert archive.getmember("fixture/run").mode == 0o755
        assert all(item.mtime == 0 and item.uid == 0 for item in archive)


def test_archive_rejects_symlink_input(tmp_path):
    target = tmp_path / "outside"
    target.write_text("must not be copied")
    root = tmp_path / "input"
    root.mkdir()
    (root / "alias").symlink_to(target)
    with pytest.raises(ValueError, match="non-regular"):
        PACKAGE.write_archive(root, "fixture", ["alias"], tmp_path / "out.tgz")


@pytest.fixture
def package_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / "main.py").write_text("print('public runtime')\n")
    (root / "settings.private").write_text("untracked operator secret\n")
    (root / ".release-policy.json").write_text(json.dumps({"version": "1.2.3"}))
    (root / ".release-package.json").write_text(
        json.dumps({"name": "fixture", "include": ["main.py"]})
    )
    subprocess.run(["git", "add", "main.py"], cwd=root, check=True)
    return root


def test_native_build_excludes_operator_files_and_verifies_checksum(package_project, tmp_path):
    output = tmp_path / "release"
    assets = PACKAGE.build_package(package_project, "1.2.3", "stable", output)
    assert len(assets) == 1
    with tarfile.open(assets[0]) as archive:
        assert archive.getnames() == ["fixture/main.py"]
        assert archive.extractfile("fixture/main.py").read() == b"print('public runtime')\n"
    assert (output / "SHA256SUMS").read_text() == (
        f"{hashlib.sha256(assets[0].read_bytes()).hexdigest()}  {assets[0].name}\n"
    )


def test_build_rejects_stale_output_before_writing_assets(package_project, tmp_path):
    output = tmp_path / "release"
    output.mkdir()
    stale = output / "old.tar.gz"
    stale.write_bytes(b"previous release")
    with pytest.raises(ValueError, match="must be empty"):
        PACKAGE.build_package(package_project, "1.2.3", "stable", output)
    assert stale.read_bytes() == b"previous release"
    assert list(output.iterdir()) == [stale]


@pytest.mark.parametrize("required", ["settings.private", "absent.py"])
def test_required_runtime_input_must_exist_and_be_tracked(package_project, required):
    with pytest.raises(ValueError, match="Missing required runtime input"):
        PACKAGE.package_inputs(package_project, {"name": "fixture", "include": [required]})


def test_frozen_release_evidence_is_selected_without_operator_files(package_project):
    (package_project / ".release-plan.json").write_text("{}")
    (package_project / ".release-inputs.json").symlink_to("settings.private")
    _, selected = PACKAGE.package_inputs(
        package_project, {"name": "fixture", "include": ["main.py"]}
    )
    assert selected == [".release-plan.json", "main.py"]


def test_source_archive_omits_deleted_tracked_and_untracked_files(package_project):
    (package_project / "removed.py").write_text("old runtime")
    subprocess.run(["git", "add", "removed.py"], cwd=package_project, check=True)
    (package_project / "removed.py").unlink()
    _, selected = PACKAGE.package_inputs(package_project, {"name": "fixture", "source": True})
    assert selected == ["main.py"]


@pytest.mark.parametrize("version", ["../../escape", "1.2.3;echo secret", "1.2", "\u0661.2.3"])
def test_build_rejects_unsafe_versions_before_creating_output(package_project, tmp_path, version):
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="semantic version"):
        PACKAGE.build_package(package_project, version, "stable", output)
    assert not output.exists()


def test_build_rejects_unknown_channel(package_project):
    with pytest.raises(ValueError, match="Unknown release channel"):
        PACKAGE.validate_version(package_project, "1.2.3", "unreviewed")


@pytest.mark.parametrize("version_file", ["version", "pyproject.toml", None])
def test_build_rejects_mismatched_committed_version(package_project, version_file):
    if version_file:
        (package_project / ".release-policy.json").write_text(
            json.dumps({"version_file": version_file})
        )
        content = (
            '[project]\nversion = "1.2.3"\n' if version_file == "pyproject.toml" else "1.2.3\n"
        )
        (package_project / version_file).write_text(content)
    with pytest.raises(ValueError, match="must match committed"):
        PACKAGE.validate_version(package_project, "1.3.0", "stable")


def test_build_rejects_empty_asset_declaration(package_project, tmp_path):
    (package_project / ".release-package.json").write_text(json.dumps({"name": "fixture"}))
    with pytest.raises(ValueError, match="No release assets"):
        PACKAGE.build_package(package_project, "1.2.3", "stable", tmp_path / "release")
