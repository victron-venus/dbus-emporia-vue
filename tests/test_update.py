"""Exercise the real installer in a temporary Venus filesystem layout."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(name="venus")
def venus_layout_fixture(tmp_path):
    """Create isolated device roots and record supervisor commands."""
    repo = Path(__file__).resolve().parents[1]
    name = "dbus-emporia-vue"  # independent of checkout/worktree directory name
    root = tmp_path / "venus"
    install = root / "data" / name
    install.mkdir(parents=True)
    (root / "service").mkdir()
    (root / "data" / "rc.local").write_text("#!/bin/sh\nexit 0\n")
    script = (repo / "update.sh").read_text()
    runtime = re.search(r'^RUNTIME_ITEMS="([^"]+)"', script, re.MULTILINE).group(1).split()
    script = script.replace("/data/", str(root / "data") + "/")
    script = re.sub(r"""(?<=[\s"'])/service(?=/|\b)""", str(root / "service"), script)
    script = script.replace("/opt/victronenergy/", str(root / "opt") + "/")
    commands = tmp_path / "bin"
    commands.mkdir()
    stubs = {
        "svc": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SVC_LOG"\n',
        "sleep": "#!/bin/sh\nexit 0\n",
        "python3": "#!/bin/sh\nexit 0\n",
        "svstat": (
            '#!/bin/sh\nif [ "${STAY_UP:-0}" = 1 ]; then\n'
            'printf "%s: up (pid 123) 10 seconds\\n" "$1"\n'
            'else printf "%s: down 0 seconds\\n" "$1"; fi\n'
        ),
    }
    for command, body in stubs.items():
        stub = commands / command
        stub.write_text(body)
        stub.chmod(0o755)
    if shutil.which("gsed"):
        (commands / "sed").symlink_to(shutil.which("gsed"))
    calls = tmp_path / "svc-calls"
    environment = dict(
        os.environ,
        PATH=str(commands) + os.pathsep + os.environ["PATH"],
        SVC_LOG=str(calls),
    )
    layout = SimpleNamespace(
        repo=repo,
        name=name,
        root=root,
        install=install,
        runtime=runtime,
        script=script,
        env=environment,
        calls=calls,
        service=install / "service" / name,
        link=root / "service" / name,
    )
    copy_payload(layout, install)
    layout.config = install / ("config.json" if name == "dbus-emporia-vue" else "local_config.py")
    layout.config.write_text("device-local configuration must survive\n")
    return layout


def copy_payload(layout, destination):
    """Copy tracked runtime inputs and redirect only literal device roots."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in [*layout.runtime, "services"]:
        source = layout.repo / item
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, destination / item)
        else:
            shutil.copy2(source, destination / item)
    (destination / "update.sh").write_text(layout.script)


def install_existing_service(layout):
    """Model existing service directories and live supervisor state."""
    shutil.copytree(layout.install / "services" / layout.name, layout.service)
    layout.link.symlink_to(layout.service)
    for directory in (layout.service, layout.service / "log"):
        (directory / "supervise").mkdir()
        (directory / "supervise" / "status").write_bytes(b"live supervisor state")
        directory.chmod(0o751)


def run_update(layout, source=None):
    """Run the real installer without invoking actual device commands."""
    source = source or layout.install
    return subprocess.run(
        ["sh", str(source / "update.sh"), str(layout.install)],
        cwd=layout.install,
        env=layout.env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


def assert_directory_metadata(before):
    """Check directory and symlink inode, ownership and permissions."""
    for path, original in before.items():
        current = path.lstat()
        assert (current.st_ino, current.st_uid, current.st_gid, current.st_mode) == (
            original.st_ino,
            original.st_uid,
            original.st_gid,
            original.st_mode,
        )


def test_repeated_in_place_updates_preserve_live_supervisors_and_boot(venus):
    """Retain directory handles, metadata and unrelated files across updates."""
    install_existing_service(venus)
    stale = venus.install / "inverter_control"
    has_stale_package = 'STALE_TOP_LEVEL="main.py inverter_control"' in venus.script
    if has_stale_package:
        stale.mkdir()
        (stale / "obsolete.py").write_text("old package")
    untouched = venus.install / "operator-backup"
    untouched.mkdir()
    (untouched / "keep").write_text("operator data")
    paths = [venus.service, venus.service / "log", venus.link]
    before = {path: path.lstat() for path in paths}
    descriptors = [os.open(path, os.O_RDONLY) for path in paths[:2]]
    try:
        for _ in range(2):
            result = run_update(venus)
            assert result.returncode == 0, result.stdout + result.stderr
            assert venus.config.read_text() == "device-local configuration must survive\n"
            assert (untouched / "keep").read_text() == "operator data"
            if has_stale_package:
                assert not stale.exists()
            assert_directory_metadata(before)
            for descriptor, directory in zip(descriptors, paths[:2], strict=True):
                assert os.fstat(descriptor).st_ino == directory.stat().st_ino
                assert (directory / "supervise" / "status").read_bytes() == b"live supervisor state"
            boot = (venus.root / "data" / "rc.local").read_text()
            marker = f"# === {venus.name} service persistence ==="
            assert boot.count(marker) == 1
            assert boot.index(marker) < boot.index("exit 0")
            assert venus.link.resolve() == venus.service
            for item in venus.runtime:
                if (venus.repo / item).exists():
                    assert (venus.install / item).exists(), item
            # The installed package uses service/, even without services/.
            shutil.rmtree(venus.install / "services", ignore_errors=True)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    calls = venus.calls.read_text().splitlines()
    assert calls == [
        f"-d {venus.link}",
        f"-u {venus.link}/log",
        f"-u {venus.link}",
        f"-d {venus.link}",
        f"-u {venus.link}/log",
        f"-u {venus.link}",
    ]


def test_release_update_replaces_run_files_atomically(venus, tmp_path):
    """Open old run files remain intact while their paths receive new content."""
    install_existing_service(venus)
    release = tmp_path / "release"
    copy_payload(venus, release)
    for relative in ("run", "log/run"):
        (venus.service / relative).write_text("old running script\n")
    with (venus.service / "run").open() as worker, (venus.service / "log/run").open() as logger:
        result = run_update(venus, release)
        assert result.returncode == 0, result.stdout + result.stderr
        for opened, relative in ((worker, "run"), (logger, "log/run")):
            current = venus.service / relative
            assert opened.read() == "old running script\n"
            assert os.fstat(opened.fileno()).st_ino != current.stat().st_ino
            assert (
                current.read_bytes() == (release / "services" / venus.name / relative).read_bytes()
            )
            assert current.stat().st_mode & 0o111


def test_first_install_creates_service_without_touching_other_services(venus):
    """A first install starts only the two owned service paths."""
    result = run_update(venus)
    assert result.returncode == 0, result.stdout + result.stderr
    assert venus.link.is_symlink()
    assert venus.link.resolve() == venus.service
    assert venus.calls.read_text().splitlines() == [f"-u {venus.link}/log", f"-u {venus.link}"]


@pytest.mark.parametrize("existing", ["valid", "missing", "directory"])
def test_boot_hook_only_creates_a_missing_canonical_link(venus, existing):
    """Boot replay preserves existing links and refuses foreign directories."""
    result = run_update(venus)
    assert result.returncode == 0, result.stdout + result.stderr
    inode = venus.link.lstat().st_ino
    if existing != "valid":
        venus.link.unlink()
    if existing == "directory":
        venus.link.mkdir()
        (venus.link / "keep").write_text("foreign service")
    venus.calls.write_text("")
    boot = venus.root / "data" / "rc.local"
    result = subprocess.run(
        ["sh", str(boot)],
        env=venus.env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    if existing == "directory":
        assert not venus.link.is_symlink()
        assert (venus.link / "keep").read_text() == "foreign service"
        assert not venus.calls.read_text()
    else:
        assert venus.link.is_symlink()
        assert venus.link.resolve() == venus.service
        if existing == "valid":
            assert venus.link.lstat().st_ino == inode
        assert venus.calls.read_text().splitlines() == [f"-u {venus.link}/log", f"-u {venus.link}"]


@pytest.mark.parametrize("layout", ["directory", "foreign_link", "service_link", "legacy"])
def test_unexpected_layout_is_rejected_before_stopping_or_replacing(venus, tmp_path, layout):
    """Reject conflicting layouts without stopping or modifying any service."""
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "keep"
    sentinel.write_text("do not touch")
    if layout == "directory":
        venus.link.mkdir()
    elif layout == "foreign_link":
        venus.link.symlink_to(foreign)
    elif layout == "service_link":
        (venus.install / "service").symlink_to(foreign)
    else:
        legacy = venus.root / "opt" / venus.name
        legacy.parent.mkdir()
        legacy.symlink_to(foreign)
    before = (venus.install / "version").read_bytes()
    result = run_update(venus)
    assert result.returncode != 0
    assert not venus.calls.exists()
    assert sentinel.read_text() == "do not touch"
    assert (venus.install / "version").read_bytes() == before


def test_missing_service_definition_is_rejected_before_stop(venus):
    """A partial release must not take down the installed application."""
    (venus.install / "services" / venus.name / "log" / "run").unlink()
    result = run_update(venus)
    assert result.returncode != 0
    assert "Missing service definition" in result.stderr
    assert not venus.calls.exists()


def test_stuck_worker_aborts_without_replacing_runtime_or_logger(venus):
    """Never replace live runtime files after a worker fails to terminate."""
    install_existing_service(venus)
    venus.env["STAY_UP"] = "1"
    before = (venus.install / "update.sh").stat().st_ino
    result = run_update(venus)
    assert result.returncode != 0
    assert "runtime files were not changed" in result.stderr
    assert (venus.install / "update.sh").stat().st_ino == before
    assert venus.calls.read_text().splitlines() == [f"-d {venus.link}", f"-k {venus.link}"]


def test_missing_dependencies_fail_before_install_changes(tmp_path):
    """Missing interpreter dependencies stop the update before mutations."""
    repo = Path(__file__).resolve().parents[1]
    commands = tmp_path / "bin"
    commands.mkdir()
    interpreter = commands / "python3"
    interpreter.write_text("#!/bin/sh\nexit 42\n")
    interpreter.chmod(0o755)
    script = (repo / "update.sh").read_text()
    script = script.split("# Stage the release before stopping anything.")[0]
    script += '\nprintf "unexpected continuation"\n'
    result = subprocess.run(
        ["sh", "-c", script],
        cwd=tmp_path,
        env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"]),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 42
    assert "unexpected continuation" not in result.stdout


@pytest.mark.parametrize(
    ("config", "needs_direct"),
    [
        ({}, False),
        ({"emporia": None}, False),
        ({"source": "home_assistant"}, False),
        ({"source": "emporia"}, True),
    ],
)
def test_direct_dependency_check_respects_installed_configuration(
    venus, tmp_path, config, needs_direct
):
    """A missing direct client blocks only the selected Emporia source."""
    install_existing_service(venus)
    venus.config.write_text(json.dumps(config))
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "dbus_fast.py").write_text("")
    (imports / "websockets.py").write_text("")
    (imports / "requests.py").write_text("raise ImportError('unused HA dependency')\n")
    (imports / "pyemvue.py").write_text("raise ImportError('direct client unavailable')\n")
    interpreter = Path(venus.env["PATH"].split(os.pathsep)[0]) / "python3"
    interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    venus.env["PYTHONPATH"] = str(imports)

    result = run_update(venus)

    if needs_direct:
        assert result.returncode != 0
        assert "direct client unavailable" in result.stderr
        assert not venus.calls.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert venus.calls.exists()


def test_direct_dependency_check_uses_pushed_configuration(venus, tmp_path):
    """Check the incoming configuration before replacing a healthy HA service."""
    venus.config.write_text('{"source": "home_assistant"}')
    release = tmp_path / "release"
    copy_payload(venus, release)
    (release / "config.json").write_text('{"source": "emporia"}')
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "dbus_fast.py").write_text("")
    (imports / "websockets.py").write_text("")
    (imports / "requests.py").write_text("raise ImportError('unused HA dependency')\n")
    (imports / "pyemvue.py").write_text("raise ImportError('direct client unavailable')\n")
    interpreter = Path(venus.env["PATH"].split(os.pathsep)[0]) / "python3"
    interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    venus.env.update(PYTHONPATH=str(imports), PUSH_LOCAL_CONFIG="1")

    result = run_update(venus, release)

    assert result.returncode != 0
    assert "direct client unavailable" in result.stderr
    assert not venus.calls.exists()
    assert json.loads(venus.config.read_text())["source"] == "home_assistant"


@pytest.mark.parametrize("in_place", [False, True])
def test_updates_leave_credentials_and_tokens_untouched(venus, tmp_path, in_place):
    """Only runtime paths are replaced, including with custom secret filenames."""
    secrets = {}
    for name in ("emporia-tokens.json", "emporia-credentials.json", "custom-auth.json"):
        path = venus.install / name
        path.write_text("device-local authentication")
        path.chmod(0o600)
        secrets[path] = path.stat()
    source = venus.install
    if not in_place:
        source = tmp_path / "release"
        copy_payload(venus, source)
        for path in secrets:
            (source / path.name).write_text("must not replace device credentials")

    result = run_update(venus, source)

    assert result.returncode == 0, result.stdout + result.stderr
    for path, before in secrets.items():
        assert path.read_text() == "device-local authentication"
        assert path.stat().st_ino == before.st_ino
        assert path.stat().st_mode == before.st_mode


def test_updater_loads_and_preserves_device_vendor_dependencies(venus, tmp_path):
    """Check dependencies from persistent storage without copying over them."""
    venus.config.write_text('{"source": "emporia"}')
    vendor = venus.install / "vendor"
    vendor.mkdir()
    imports = tmp_path / "imports"
    imports.mkdir()
    for name in ("dbus_fast", "websockets", "pyemvue", "botocore"):
        (vendor / f"{name}.py").write_text("# device dependency\n")
        (imports / f"{name}.py").write_text("raise ImportError('wrong dependency path')\n")
    before = {path: path.stat() for path in vendor.iterdir()}
    interpreter = Path(venus.env["PATH"].split(os.pathsep)[0]) / "python3"
    interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    venus.env["PYTHONPATH"] = str(imports)
    release = tmp_path / "release"
    copy_payload(venus, release)
    (release / "vendor").mkdir()
    (release / "vendor" / "pyemvue.py").write_text("raise ImportError('release dependency')\n")

    result = run_update(venus, release)

    assert result.returncode == 0, result.stdout + result.stderr
    assert_directory_metadata(before)
    assert set(vendor.iterdir()) == set(before)
    assert (vendor / "pyemvue.py").read_text() == "# device dependency\n"


@pytest.mark.parametrize("existing_pythonpath", [False, True])
def test_service_loads_vendor_and_preserves_existing_pythonpath(
    venus, tmp_path, existing_pythonpath
):
    """The service resolves the same persistent dependencies as the updater."""
    vendor = venus.install / "vendor"
    vendor.mkdir()
    (vendor / "device_dependency.py").write_text("VALUE = 'device vendor'\n")
    source = "import device_dependency\nprint(device_dependency.VALUE)\n"
    venus.env.pop("PYTHONPATH", None)
    if existing_pythonpath:
        imports = tmp_path / "imports"
        imports.mkdir()
        (imports / "device_dependency.py").write_text(
            "raise ImportError('wrong dependency path')\n"
        )
        (imports / "ambient_dependency.py").write_text("VALUE = 'existing path'\n")
        source += "import ambient_dependency\nprint(ambient_dependency.VALUE)\n"
        venus.env["PYTHONPATH"] = str(imports)
    (venus.install / "main.py").write_text(source)
    interpreter = Path(venus.env["PATH"].split(os.pathsep)[0]) / "python3"
    interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    script = (venus.repo / "services/dbus-emporia-vue/run").read_text()
    script = script.replace("/data/dbus-emporia-vue", str(venus.install))

    result = subprocess.run(
        ["sh", "-c", script], env=venus.env, capture_output=True, text=True, check=False, timeout=10
    )

    assert result.returncode == 0, result.stdout + result.stderr
    expected = ["device vendor", "existing path"] if existing_pythonpath else ["device vendor"]
    assert result.stdout.splitlines() == expected
