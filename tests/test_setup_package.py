"""Check the installable runtime layout without executing SetupHelper or devices."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_setup_copies_complete_runtime(tmp_path):
    """Execute only package-copy commands into a private temporary directory."""
    setup = (ROOT / "setup").read_text(encoding="utf-8")
    copy_section = setup.split("    # Install Python script and config\n", 1)[1].split(
        "    # Copy example config", 1
    )[0]
    installed = tmp_path / "installed"
    copy_section = copy_section.replace("/data/dbus-emporia-vue", '"$installDir"')
    subprocess.run(
        [
            "bash",
            "-ec",
            "scriptDir=$1\ninstallDir=$2\n" + copy_section,
            "package-copy",
            str(ROOT),
            str(installed),
        ],
        check=True,
    )
    expected_version = (ROOT / "version").read_text(encoding="utf-8").strip()
    assert (installed / "version").read_text(encoding="utf-8").strip() == expected_version
    assert (installed / "aiovelib/aiovelib/service.py").is_file()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(installed)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, main; assert main.VERSION == sys.argv[1]",
            expected_version,
        ],
        cwd=installed,
        env=environment,
        check=True,
    )


def test_setup_defines_persistence_before_installation():
    """The installer must define its helper before reaching the install branch."""
    setup = (ROOT / "setup").read_text(encoding="utf-8")
    assert setup.index("setupFirmwarePersistence() {") < setup.index("#### install")
    subprocess.run(["bash", "-n", str(ROOT / "setup")], check=True)
