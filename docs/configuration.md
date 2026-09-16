# Configuration reference

Start with [one of the three setups](../README.md#choose-your-setup). This page
covers optional settings, credentials and published readings.

The service reads `/data/dbus-emporia-vue/config.json`. Use valid JSON without
comments. Restart with `svc -t /service/dbus-emporia-vue` after changes.

## Source and credentials

`source` accepts exactly `home_assistant` or `emporia`. If omitted, it defaults
to `home_assistant` for compatibility with existing installations. New examples
set it explicitly. Only the selected source connects; changing modes is manual.

### Home Assistant

Set the top-level `ha_url` and `ha_token`. The URL ends in `/api/websocket`;
use `ws://` for HTTP or `wss://` for HTTPS. Each channel needs `ha_entity_id`.
Ordinary HA channels use the numeric state as watts, so choose entities reporting
`W`. The optional submeter also accepts `kW` and converts it to watts.

Protect `config.json` with mode `0600`, since it contains the access token.
Keep the HA Emporia integration enabled and its source entities independent of
this driver's MQTT output.

`ha_config_gen.py` can generate mappings on a workstation with `HA_URL` and
`HA_TOKEN` set in its environment. It overwrites the local `config.json`;
review the generated mappings and units before use.

### Emporia API

The `emporia` object contains `credentials_file` and `token_file`. Relative paths
resolve beside the installed `config.json`; absolute paths are also supported.
Use the [credentials template](examples/2-from-emporia-api/emporia-credentials.json.example)
to store `username` and `password` on GX. These are your Emporia account email
and password. The driver creates and refreshes the token file automatically.

The files contain unencrypted JSON. Keep them on GX with owner-only permissions
(`0600`). The default file names and `config.json` are excluded from Git, and
deployment does not upload Emporia credentials or tokens.

For token-only authentication, omit `credentials_file` and supply a valid token
file. A configured credentials file must exist even when cached tokens are
available. Alternatively, omit the key and set `EMPORIA_USERNAME` and
`EMPORIA_PASSWORD` in the service environment. `token_file` defaults to
`emporia-tokens.json`. Direct mode requires no HA URL or access token.

## Find your Emporia device and channel IDs

After preparing the [dependencies](installation.md#prepare-the-package), run
this once in an interactive SSH terminal on GX. It prompts for your Emporia
account, reads the account's device list and prints channel mappings. It does
not change devices or save credentials or tokens.

```sh
PYTHONPATH=/data/dbus-emporia-vue/vendor python3 -c '
from getpass import getpass
import json
import sys
from pyemvue import PyEmVue

vue = PyEmVue()
try:
    if not vue.login(username=input("Emporia email: ").strip(), password=getpass("Emporia password: ")):
        raise RuntimeError("login failed")
    devices = vue.get_devices()
except Exception:
    sys.exit("Could not read Emporia devices. Check your credentials and connection.")
for device in devices:
    for channel in device.channels:
        print(json.dumps({"emporia_device_gid": device.device_gid, "emporia_channel": str(channel.channel_num), "name": channel.name}))
'
```

Example output:

```json
{"emporia_device_gid": 123456, "emporia_channel": "1", "name": "Heat Pump"}
```

Copy the device ID and channel string into your chosen example. The device ID
is an integer; the channel is a string. A main channel commonly uses `"1,2,3"`.
Use the values returned for your device rather than guessing from the circuit's
display name. Optional aggregate/import/export channels depend on the device
and may not appear in this physical-channel listing; configure them only when
your account provides them.

## Channel settings

Each object in `channels` defines one AC-load service:

- `id`: a stable channel identifier. Existing `ha_entity_id` identifiers remain
  supported when `id` is omitted.
- `service_name`: a unique name beginning with `com.victronenergy.acload.`.
- `instance`: a unique nonnegative GX device instance. It becomes part of the
  MQTT topic. Preserve it and `service_name` when updating an existing channel.
- `custom_name`: the name shown by consumers.
- `ha_entity_id`: the power entity for HA input.
- `emporia_device_gid` and `emporia_channel`: the device/channel pair for direct
  API input. Each pair must be unique.
- `position`: `0` for AC output or `1` for AC input; defaults to `0`.
- `power_multiplier`: direct-mode power and energy multiplier; defaults to `1`.
- `emporia_import_channel` and `emporia_export_channel`: optional direct-mode
  energy channels, commonly `"MainsFromGrid"` and `"MainsToGrid"`. They add
  directional energy to the same service without creating extra power meters.

Add circuits by copying a channel object and changing its mapping, ID, service
name and instance. In setup 3, also add matching HA sensors and MQTT topic
instances. The minimal examples omit defaults and optional fields.

## Polling and freshness

Direct API settings live inside `emporia`. Defaults are:

- `poll_interval_seconds`: `3` for power.
- `day_interval_seconds`: `1800` (30 minutes) for daily energy.
- `month_interval_seconds`: `21600` (6 hours) for monthly energy.
- `timeout_seconds`: `10` for cloud requests.
- `stale_after_seconds`: `30` for power freshness; must exceed the power interval.
- `status_interval_seconds`: `15` for meter connection status.
- `status_stale_after_seconds`: `30`; must exceed the status interval.
- `solar_invert`: `true` to invert channels identified as solar.

The client batches channel reads and keeps current values. Energy refreshes
independently of power; its freshness limit is twice its polling interval plus
30 seconds. Missing or stale direct readings become unavailable. Meter status
must also be current and connected; a successful cloud response alone does not
establish availability. A measured zero remains zero.

Changing polling intervals in setup 3 also requires updating any corresponding
freshness thresholds in your HA templates. MQTT keepalive republishes cached GX
values and does not cause additional Emporia API polls.

## Optional submeter and logging

To select one existing channel as a signed submeter, add a top-level object:

```json
{"submeter": {"channel": "channel_1", "stale_after_seconds": 30}}
```

`channel` refers to its `id` or legacy `ha_entity_id`. Power stays signed and is
mirrored to L1. This selects an existing AC-load service; it creates no additional
grid meter. Omit `submeter` or set it to `null` when not needed.

`log_level` is an optional top-level setting and defaults to `INFO`.

## Published readings

All channel services expose `/Ac/Power`, `/Ac/L1/Power`, `/Connected`,
`/CustomName` and `/DeviceInstance`. Direct mode also exposes:

- `/Source/Type`: `emporia` or `unavailable`.
- `/LastUpdate`: power timestamp in Unix seconds.
- `/Emporia/DeviceId` and `/Emporia/Channel`: the mapped identity.
- `/Emporia/Energy/Day` and `/Emporia/Energy/Month`: energy in kWh.
- `/Emporia/Energy/DayUpdated` and `/Emporia/Energy/MonthUpdated`: energy timestamps.
- `/Emporia/Energy/DaySample` and `/Emporia/Energy/MonthSample`: JSON strings
  containing `value` and `timestamp` together.
- `/Emporia/Energy/Import/Day`, `/Emporia/Energy/Import/Month`,
  `/Emporia/Energy/Export/Day` and `/Emporia/Energy/Export/Month`: optional
  directional energy, each with corresponding `Updated` and `Sample` paths.

Daily and monthly energy reset at period boundaries. They are not lifetime
counters; `/Ac/Energy/Forward` stays unavailable. In HA-input mode, energy and
Emporia metadata are absent; `/LastUpdate` exists only for a selected submeter.

Venus OS MQTT publishes these paths under
`N/<portal-id>/acload/<instance>/<path>`. For example, channel 71 power is
`N/<portal-id>/acload/71/Ac/Power`. Payloads contain a JSON `value` field.
See the [MQTT guide](home-assistant-mqtt.md) for bridge prefixes, keepalive,
availability and energy statistics.
