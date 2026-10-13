#!/usr/bin/env python3
"""
Generate config.json for dbus-emporia-vue by querying Home Assistant
for power sensors (unit_of_measurement == 'W') that end with "_1s"
(instantaneous values).

Note: Entity registry and device registry APIs are not available in this
Home Assistant version, so device-based filtering is not possible.
The "_1s" suffix is used to filter for instantaneous power values.

Usage:
    HA_URL=ws://homeassistant:8123/api HA_TOKEN=your_token \
    [DEVICE_NAME=emporia_vue] python ha_config_gen.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def ha_url_to_rest(ws_url: str) -> str:
    """Convert WS URL to REST base URL."""
    parsed = urlsplit(ws_url)
    schemes = {"ws": "http", "wss": "https", "http": "http", "https": "https"}
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "HA_URL must be an HTTP(S) or WS(S) host URL without credentials, query or fragment"
        )
    # Accessing port validates malformed and out-of-range values.
    _ = parsed.port
    path = parsed.path.removesuffix("/websocket").rstrip("/")
    if not path.endswith("/api"):
        path += "/api"
    return urlunsplit((schemes[parsed.scheme], parsed.netloc, path, "", ""))


class NoAuthRedirect(HTTPRedirectHandler):
    """Never forward an operator's bearer token to a redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Authenticated redirects are disabled", headers, fp)


def open_authenticated(request):
    """Open only a validated HTTP(S) request with redirects disabled."""
    if urlsplit(request.full_url).scheme not in {"http", "https"}:
        raise ValueError("Unsupported authenticated request scheme")
    return build_opener(NoAuthRedirect()).open(request, timeout=10)  # nosec B310 - HTTP(S) allowlist above


def write_private_config(config, path=Path("config.json")):
    """Atomically replace configuration with owner-only mode, never follow symlinks."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing a symlink configuration destination")
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(config, output, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fetch_json(ha_url: str, token: str, api_path: str):
    """Fetch JSON from HA REST API."""
    rest_url = ha_url_to_rest(ha_url)
    api_url = f"{rest_url}{api_path}"
    req = Request(api_url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("content-type", "application/json")
    try:
        with open_authenticated(req) as resp:
            data = resp.read()
            return json.loads(data)
    except HTTPError as e:
        print(f"HTTP error: {e.code} {e.reason} for URL: {api_url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"URL error: {e.reason} for URL: {api_url}", file=sys.stderr)
        return None


def main():
    ha_url = os.environ.get("HA_URL")
    ha_token = os.environ.get("HA_TOKEN")
    device_name = os.environ.get("DEVICE_NAME", "emporia_vue")
    if not ha_url or not ha_token:
        print("Please set HA_URL and HA_TOKEN environment variables.", file=sys.stderr)
        print("Example:", file=sys.stderr)
        print('  export HA_URL="ws://192.168.1.50:8123/api/websocket"', file=sys.stderr)
        print('  export HA_TOKEN="your_long_lived_access_token"', file=sys.stderr)
        sys.exit(1)

    try:
        ha_url_to_rest(ha_url)
    except ValueError:
        print("HA_URL is invalid; use an HTTP(S) or WS(S) host URL.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching states from {ha_url} (looking for device: {device_name}) ...")
    states = fetch_json(ha_url, ha_token, "/states")
    if states is None:
        print("Failed to fetch states from Home Assistant", file=sys.stderr)
        sys.exit(1)
    print(f"Got {len(states)} states total.")

    # Filter for power sensors: domain sensor and unit_of_measurement == 'W'
    power_candidates = []
    for s in states:
        entity_id = s.get("entity_id", "")
        if not entity_id.startswith("sensor."):
            continue
        attrs = s.get("attributes", {})
        unit = attrs.get("unit_of_measurement")
        if unit == "W":
            power_candidates.append(s)
    print(f"Found {len(power_candidates)} power sensors (unit_of_measurement == 'W').")

    if not power_candidates:
        print("No power sensors found. Check your HA instance and token.", file=sys.stderr)
        sys.exit(1)

    # Filter for entities ending with "_1s" (instantaneous values)
    instantaneous_candidates = []
    for s in power_candidates:
        entity_id = s.get("entity_id", "")
        if entity_id.endswith("_1s"):
            instantaneous_candidates.append(s)
    print(f"After filtering for '_1s' suffix: {len(instantaneous_candidates)} sensors")

    # Note: Entity registry and device registry APIs are not available in this HA version
    # (they return 404), so device-based filtering is not possible.
    # We rely on the "_1s" suffix filtering as the determining factor for
    # instantaneous power sensor selection, as noted by the user.
    selected = instantaneous_candidates
    print(
        f"Using {len(selected)} sensors with '_1s' suffix "
        "(device filtering not available in this HA version)"
    )

    if not selected:
        print(
            "No power sensors found for the specified device. Check your HA configuration.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Sort by entity_id for deterministic ordering
    selected.sort(key=lambda s: s.get("entity_id", ""))

    # Determine free DeviceInstance range: we will start at 71 and increment.
    base_instance = 71
    channels = []
    for idx, s in enumerate(selected):
        entity_id = s.get("entity_id")
        attrs = s.get("attributes", {})
        friendly = attrs.get("friendly_name", entity_id)
        # Create service name
        ch_num = idx + 1
        service_name = f"com.victronenergy.acload.emporia_ch{ch_num}"
        instance = base_instance + idx
        channels.append(
            {
                "ha_entity_id": entity_id,
                "service_name": service_name,
                "instance": instance,
                "custom_name": friendly,
                "position": 0,  # default to AC Input 1
            }
        )

    config = {
        "ha_url": ha_url,
        "ha_token": ha_token,
        "channels": channels,
        "stale_timeout": 15,
        "update_interval": 1,
    }

    out_path = "config.json"
    write_private_config(config, Path(out_path))
    print(f"Generated {out_path} with {len(channels)} channels.")
    print("Review and edit if needed (e.g., adjust instance numbers to avoid conflicts).")


if __name__ == "__main__":
    main()
