#!/usr/bin/env python3
"""Export the configured Emporia tariff reference without exposing credentials."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Imports follow the standalone script path setup.
# pylint: disable=wrong-import-position
from emporia import EmporiaClient  # noqa: E402
from sources import emporia_config  # noqa: E402
from tariff_export import read_tariff_reference  # noqa: E402


def export_path(filename: str) -> Path:
    """Confine generated exports to a JSON basename in the working directory."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.json", filename):
        raise ValueError("Choose a JSON filename without directory components")
    return Path.cwd() / filename


def main():
    """Write a sanitized reference from the configured Emporia device."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--device-gid", type=int, required=True)
    parser.add_argument(
        "--currency", required=True, help="Currency used by the Emporia app, e.g. USD"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="New JSON filename in the current directory; paths and existing files are refused",
    )
    args = parser.parse_args()
    try:
        destination = export_path(args.output)
        configuration = args.config.resolve()
        data = json.loads(configuration.read_text())
        config = emporia_config(data)
        if config is None:
            raise ValueError(
                "This exporter requires source=emporia in the driver configuration"
            )
        for key in ("token_file", "credentials_file"):
            if key in config:
                config[key] = str(configuration.parent / config[key])
        client = EmporiaClient(config, data["channels"], lambda *_: None, lambda: None)
        result = read_tariff_reference(client, args.device_gid, args.currency)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
        print(
            "Tariff reference exported. Import this file in the dashboard tariff editor."
        )
        if result["utilityRateGid"]:
            print(
                "The utility plan ID is available; "
                "copy its time-of-use prices from the Emporia app."
            )
    # Never print API response bodies or credentials, including unexpected errors.
    except Exception as error:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        print(
            f"Tariff export failed ({type(error).__name__}). Check configuration and API access.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
