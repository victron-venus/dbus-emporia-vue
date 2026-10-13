"""Build a diagnostic vendor bundle for the exact reviewed RC; never deploy it."""

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MANIFEST = json.loads((HERE / "inputs.json").read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def input_records():
    records = {}
    for item in MANIFEST["runtime"] + MANIFEST["build_tools"]:
        for key in ("artifact", "license_source"):
            if key in item:
                record = item[key]
                previous = records.setdefault(record["filename"], record)
                if previous != record:
                    raise ValueError("conflicting download filename")
    return records.values()


def validate_inputs(directory):
    if digest(ROOT / "requirements.lock") != MANIFEST["requirements_lock_sha256"]:
        raise ValueError("the reviewed RC lockfile changed")
    for record in input_records():
        path = directory / record["filename"]
        if path.stat().st_size != record["size"] or digest(path) != record["sha256"]:
            raise ValueError("input hash or size mismatch: " + path.name)


def fetch(directory):
    directory.mkdir(parents=True, exist_ok=False)
    for record in input_records():
        if Path(record["filename"]).name != record["filename"] or not record["url"].startswith(
            "https://files.pythonhosted.org/"
        ):
            raise ValueError("unapproved download location")
        path = directory / record["filename"]
        with urllib.request.urlopen(record["url"], timeout=60) as response:
            with path.open("xb") as stream:
                shutil.copyfileobj(response, stream)
    validate_inputs(directory)


def copy_licenses(inputs, output):
    inventory = {}
    for item in MANIFEST["runtime"]:
        found = []
        with tarfile.open(inputs / item["license_source"]["filename"], "r:*") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if (
                    member.isfile()
                    and name.name.lower().startswith(("license", "licence", "copying", "notice"))
                    and not name.is_absolute()
                    and ".." not in name.parts
                    and member.size <= 1024 * 1024
                ):
                    # Preserve the upstream relative name without extracting links or metadata.
                    relative = Path(item["name"], *name.parts[1:])
                    path = output / "dependency-licenses" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, path.open("xb") as target:
                        shutil.copyfileobj(source, target)
                    found.append(relative.as_posix())
        if not found:
            raise ValueError("no upstream license file found: " + item["name"])
        inventory[item["name"]] = found
    return inventory


def probe(vendor, receipt):
    sys.path.insert(0, str(vendor))
    sys.path.insert(1, str(ROOT))
    sys.path.insert(2, str(ROOT / "aiovelib"))
    installed = {}
    for item in MANIFEST["runtime"]:
        distribution = importlib.metadata.distribution(item["name"])
        if distribution.version != item["version"]:
            raise ValueError("wrong installed version: " + item["name"])
        if not Path(distribution.locate_file("")).resolve().is_relative_to(vendor.resolve()):
            raise ValueError("dependency was resolved outside the isolated vendor directory")
        installed[item["name"]] = distribution.version
    imports = [
        "requests",
        "urllib3",
        "dbus_fast",
        "dbus_fast.aio",
        "websockets",
        "websockets.asyncio.client",
        "pyemvue",
        "pycognito",
        "boto3",
        "botocore",
        "cryptography.hazmat.bindings._rust",
        "cffi",
        "_cffi_backend",
        "jwt",
        "sources",
        "emporia",
        "aiovelib.service",
        "main",
    ]
    for module in imports:
        importlib.import_module(module)
    # Exercise CFFI and the cryptographic native extension without network or credentials.
    from cffi import FFI
    from cryptography.hazmat.primitives import hashes
    from dbus_fast import Variant
    from dbus_fast.message import Message

    if FFI().sizeof("int") != 4 or Variant("s", "probe").value != "probe":
        raise ValueError("CFFI or D-Bus type probe failed")
    Message(path="/diagnostic", interface="test.diagnostic", member="Probe")._marshall()
    hasher = hashes.Hash(hashes.SHA256())
    hasher.update(b"diagnostic")
    if hasher.finalize().hex() != hashlib.sha256(b"diagnostic").hexdigest():
        raise ValueError("cryptographic native extension probe failed")
    data = {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "libc": platform.libc_ver(),
        "installed_versions": installed,
        "imports": imports,
        "offline_native_probe": "passed",
    }
    receipt.write_text(json.dumps(data, indent=2) + "\n")


def build(inputs, output):
    validate_inputs(inputs)
    if platform.python_version() != MANIFEST["python"] or platform.machine() != "armv7l":
        raise ValueError("wrong build architecture or CPython patch version")
    if platform.libc_ver()[0] != "glibc" or tuple(map(int, platform.libc_ver()[1].split("."))) > (
        2,
        39,
    ):
        raise ValueError("builder glibc is newer than the target")
    output.mkdir(parents=True, exist_ok=True)
    work = Path("/tmp/vendor-build")
    work.mkdir(exist_ok=False)
    env = os.environ | {
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SKIP_CYTHON": "1",
        "SOURCE_DATE_EPOCH": "1791763200",
    }
    run([sys.executable, "-m", "venv", str(work / "venv")], env=env)
    python = work / "venv/bin/python"
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            *[str(inputs / x["artifact"]["filename"]) for x in MANIFEST["build_tools"]],
        ],
        env=env,
    )
    wheels = output / "wheels"
    wheels.mkdir(exist_ok=False)
    for item in MANIFEST["runtime"]:
        artifact = inputs / item["artifact"]["filename"]
        if item["build_from_source"]:
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--no-index",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheels),
                    str(artifact),
                ],
                env=env,
            )
        else:
            shutil.copy2(artifact, wheels / artifact.name)
    vendor = output / "vendor"
    wheel_paths = sorted(wheels.glob("*.whl"))
    if len(wheel_paths) != len(MANIFEST["runtime"]):
        raise ValueError("not exactly one wheel per runtime dependency")
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            "--target",
            str(vendor),
            *map(str, wheel_paths),
        ],
        env=env,
    )
    license_inventory = copy_licenses(inputs, output)
    run(
        [str(python), str(__file__), "probe", str(vendor), str(output / "runtime-probe.json")],
        env=env,
    )
    # Check wheel dependency constraints against the complete isolated installation.
    run([str(python), "-m", "pip", "check"], env=env | {"PYTHONPATH": str(vendor)})
    native = []
    for binary in sorted(vendor.rglob("*.so")):
        dynamic = run(["readelf", "-d", str(binary)], capture_output=True).stdout
        versions = run(["readelf", "--version-info", str(binary)], capture_output=True).stdout
        glibc = re.findall(r"GLIBC_([0-9]+\.[0-9]+)", versions)
        if any(tuple(map(int, version.split("."))) > (2, 39) for version in glibc):
            raise ValueError("native extension requires newer glibc")
        if "RPATH" in dynamic or "RUNPATH" in dynamic:
            raise ValueError("native extension contains an unexpected runtime search path")
        needed = re.findall(r"Shared library: \[([^]]+)\]", dynamic)
        allowed = {
            "libffi.so.8",
            "libgcc_s.so.1",
            "libc.so.6",
            "libpthread.so.0",
            "libdl.so.2",
            "librt.so.1",
            "libm.so.6",
            "ld-linux-armhf.so.3",
        }
        if set(needed) - allowed:
            raise ValueError("unreviewed native library dependency: " + binary.name)
        native.append(
            {
                "path": str(binary.relative_to(output)),
                "sha256": digest(binary),
                "needed": needed,
                "glibc_symbol_versions": sorted(set(glibc)),
            }
        )
    if not native:
        raise ValueError("expected native dependencies missing")
    receipt = {
        "inputs_manifest_sha256": digest(HERE / "inputs.json"),
        "source_sha": MANIFEST["source_sha"],
        "diagnostic_checkout_sha": os.environ.get("VENDOR_BUILD_CHECKOUT_SHA"),
        "base_image": MANIFEST["base_image"],
        "requirements_lock_sha256": MANIFEST["requirements_lock_sha256"],
        "build_tools": json.loads(
            run([str(python), "-m", "pip", "list", "--format=json"], capture_output=True).stdout
        ),
        "system_packages": run(
            ["dpkg-query", "-W", "-f=${Package}=${Version}\n"], capture_output=True
        ).stdout.splitlines(),
        "compiler": run(["gcc", "--version"], capture_output=True).stdout.splitlines()[0],
        "native_extensions": native,
        "licenses": license_inventory,
        "wheels": [
            {"filename": p.name, "sha256": digest(p), "size": p.stat().st_size} for p in wheel_paths
        ],
    }
    (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    shutil.copy2(HERE / "inputs.json", output / "inputs.json")
    shutil.copy2(ROOT / "requirements.lock", output / "requirements.lock")
    files = [
        {"path": str(p.relative_to(output)), "sha256": digest(p), "size": p.stat().st_size}
        for p in sorted(output.rglob("*"))
        if p.is_file() and "diagnostics" not in p.relative_to(output).parts
    ]
    (output / "file-inventory.json").write_text(json.dumps(files, indent=2) + "\n")
    with tarfile.open(output / "emporia-vendor-cp312-armv7.tar.gz", "w:gz") as archive:
        for name in [
            "vendor",
            "wheels",
            "dependency-licenses",
            "build-receipt.json",
            "runtime-probe.json",
            "inputs.json",
            "requirements.lock",
            "file-inventory.json",
        ]:
            archive.add(output / name, arcname=name)
    print("Offline ARMv7 vendor build and native probes passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["fetch", "build", "probe"])
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path, nargs="?")
    args = parser.parse_args()
    if args.mode == "fetch":
        fetch(args.first.resolve())
    elif args.mode == "build":
        build(args.first.resolve(), args.second.resolve())
    else:
        probe(args.first.resolve(), args.second.resolve())
