"""Check the installable runtime layout without executing SetupHelper or devices."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_setup_copies_complete_runtime(tmp_path):
    """Execute only package-copy commands into a private temporary directory."""
    installer = (ROOT / "update.sh").read_text(encoding="utf-8")
    runtime = re.search(r'^RUNTIME_ITEMS="([^"]+)"', installer, re.MULTILINE).group(1).split()
    installed = tmp_path / "installed"
    installed.mkdir()
    for item in runtime:
        source = ROOT / item
        if source.is_dir():
            shutil.copytree(source, installed / item)
        else:
            shutil.copy2(source, installed / item)
    expected_version = (ROOT / "version").read_text(encoding="utf-8").strip()
    assert (installed / "version").read_text(encoding="utf-8").strip() == expected_version
    assert (installed / "aiovelib/aiovelib/service.py").is_file()
    # This import smoke test executes a second copy of the runtime; collecting
    # it again would count vendored code and unexecuted duplicate modules.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("COV_CORE_")
    }
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


def test_setup_delegates_installation_to_shared_updater():
    """SetupHelper and direct deployments must invoke the same install path."""
    setup = (ROOT / "setup").read_text(encoding="utf-8")
    assert 'sh "$scriptDir/update.sh" "$scriptDir" || exit $?' in setup
    subprocess.run(["bash", "-n", str(ROOT / "setup")], check=True)
