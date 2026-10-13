"""Check native package capture without activating a service or exposing config."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("staged_installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def payload(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "run").write_text("#!/bin/sh\nexit 0\n")
    (source / "run").chmod(0o755)
    (source / "module").mkdir()
    (source / "module/app.py").write_text("print('fixture')\n")
    (source / "config.json").write_text("private fixture value")
    monkeypatch.setattr(installer, "PAYLOAD", ("run", "module/app.py"))
    return source, tmp_path / "stage"


def test_install_uninstall_preserves_operator_files_and_modes(payload):
    source, destdir = payload
    installer.stage(source, str(destdir))
    package = installer.package_path(str(destdir))
    assert (package / "run").stat().st_mode & 0o777 == 0o755
    assert (package / "module/app.py").stat().st_mode & 0o777 == 0o644
    assert not (package / "config.json").exists()
    (package / "config.json").write_text("operator-owned")
    (package / "module/notes.txt").write_text("keep")
    installer.stage(source, str(destdir))
    installer.unstage(str(destdir))
    assert (package / "config.json").read_text() == "operator-owned"
    assert (package / "module/notes.txt").read_text() == "keep"
    assert not (package / "run").exists()
    assert not (package / "module/app.py").exists()
    assert not (package / installer.MANIFEST).exists()


def test_uninstall_removes_empty_owned_directories(payload):
    source, destdir = payload
    installer.stage(source, str(destdir))
    installer.unstage(str(destdir))
    assert not installer.package_path(str(destdir)).exists()


@pytest.mark.parametrize("destdir", ["", "/", "/tmp/.."])
def test_live_root_is_rejected(destdir):
    with pytest.raises(ValueError, match="DESTDIR"):
        installer.package_path(destdir)


def test_missing_last_input_causes_no_writes(payload):
    source, destdir = payload
    (source / "module/app.py").unlink()
    with pytest.raises(ValueError, match="Missing"):
        installer.stage(source, str(destdir))
    assert not destdir.exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory"])
def test_unsafe_destination_is_rejected_before_any_write(payload, kind):
    source, destdir = payload
    package = installer.package_path(str(destdir))
    package.mkdir(parents=True)
    (package / "run").write_text("previous release")
    (package / "module").mkdir()
    target = package / "module/app.py"
    if kind == "symlink":
        target.symlink_to(source / "config.json")
    elif kind == "hardlink":
        os.link(source / "config.json", target)
    else:
        target.mkdir()
    with pytest.raises(ValueError):
        installer.stage(source, str(destdir))
    assert (package / "run").read_text() == "previous release"
    assert (source / "config.json").read_text() == "private fixture value"


def test_destination_parent_symlink_is_rejected(payload):
    source, destdir = payload
    destdir.mkdir()
    (destdir / "data").symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        installer.stage(source, str(destdir))
    assert not (source / installer.PACKAGE).exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_unsafe_source_is_rejected(payload, kind):
    source, destdir = payload
    target = source / "module/app.py"
    target.unlink()
    if kind == "symlink":
        target.symlink_to(source / "config.json")
    elif kind == "hardlink":
        os.link(source / "config.json", target)
    else:
        os.mkfifo(target)
    with pytest.raises(ValueError):
        installer.stage(source, str(destdir))
    assert not destdir.exists()


@pytest.mark.parametrize("manifest", [["../keep"], ["config.json"], [123], {"run": True}])
def test_uninstall_rejects_unowned_manifest_entries(payload, manifest):
    source, destdir = payload
    installer.stage(source, str(destdir))
    package = installer.package_path(str(destdir))
    (package / installer.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        installer.unstage(str(destdir))
    assert (package / "run").exists()


def test_uninstall_rejects_link_in_owned_payload(payload):
    source, destdir = payload
    installer.stage(source, str(destdir))
    package = installer.package_path(str(destdir))
    (package / "module/app.py").unlink()
    (package / "module/app.py").symlink_to(source / "config.json")
    with pytest.raises(ValueError, match="symlink"):
        installer.unstage(str(destdir))
    assert (package / "run").exists()
    assert (source / "config.json").read_text() == "private fixture value"


def test_staging_payload_matches_declared_native_package():
    config = json.loads((ROOT / ".release-package.json").read_text())
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    selected = {
        name
        for name in tracked
        if name and any(name == item or name.startswith(item + "/") for item in config["include"])
    }
    assert set(installer.PAYLOAD) == selected
    assert installer.PACKAGE == config["name"]


@pytest.mark.parametrize("entry", ["python", "setup", "update"])
def test_real_entrypoints_stage_without_firmware_or_service_tools(tmp_path, entry):
    source = tmp_path / "source"
    source.mkdir()
    for name in installer.PAYLOAD:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    destdir = tmp_path / "stage"
    env = dict(os.environ, DESTDIR=str(destdir))
    commands = {
        "python": [sys.executable, "install.py", "install"],
        "setup": ["bash", "setup", "INSTALL"],
        "update": ["sh", "update.sh"],
    }
    subprocess.run(commands[entry], cwd=source, env=env, check=True, capture_output=True)
    package = installer.package_path(str(destdir))
    assert (package / "version").read_bytes() == (ROOT / "version").read_bytes()
    assert not (destdir / "service").exists()
    subprocess.run(
        ["bash", "setup", "UNINSTALL"], cwd=source, env=env, check=True, capture_output=True
    )
    assert not package.exists()


def test_parent_file_collision_causes_no_partial_update(payload):
    source, destdir = payload
    package = installer.package_path(str(destdir))
    package.mkdir(parents=True)
    (package / "run").write_text("previous release")
    (package / "module").write_text("operator file")
    with pytest.raises(ValueError, match="Parent"):
        installer.stage(source, str(destdir))
    assert (package / "run").read_text() == "previous release"
    assert (package / "module").read_text() == "operator file"


def test_manifest_symlink_is_rejected_before_install(payload):
    source, destdir = payload
    package = installer.package_path(str(destdir))
    package.mkdir(parents=True)
    (package / installer.MANIFEST).symlink_to(source / "config.json")
    with pytest.raises(ValueError, match="symlink"):
        installer.stage(source, str(destdir))
    assert not (package / "run").exists()
    assert (source / "config.json").read_text() == "private fixture value"
