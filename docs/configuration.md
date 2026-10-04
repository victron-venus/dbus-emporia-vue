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

HA channels now reject measurements older than 30 seconds by default. Freshness
uses HA's `last_reported` timestamp (or `last_updated` when absent), not the time
this driver fetched the value. Missing, invalid, future-dated or stale timestamps
make a channel unavailable. The GX and HA clocks should be synchronized.

Two optional top-level settings control this behavior:

- `ha_stale_after_seconds`: maximum source age, default `30`, minimum `10`.
  Choose a value comfortably larger than your HA integration's reporting interval.
  Set it to `null` to retain the previous ordinary-channel behavior without age
  checking. The selected submeter always keeps its own `stale_after_seconds` limit.
- `ha_request_timeout_seconds`: HTTP connect and read timeout, default `10`, from
  `1` through `30` seconds.

Migration: existing configurations use the new 30-second limit automatically.
If your integration reports less often, increase `ha_stale_after_seconds`. Prefer
that over disabling freshness. HA versions without `last_reported` cannot prove
that an unchanged value is still being reported; upgrade HA or explicitly choose
the legacy ordinary-channel policy if necessary. Selecting a submeter still
requires timestamped, fresh source data.

The driver keeps its WebSocket subscription and checks every five seconds whether
quiet channels need revalidation. When a channel has half its freshness interval
remaining, it reads only that entity through HA's REST API. Unchanged zero or
constant power remains valid when HA advances `last_reported`; re-reading an old
timestamp never extends its lifetime. Changing source values require no extra
HTTP requests. The initial WebSocket connection fetches one full state snapshot;
periodic refreshes do not fetch all HA entities.

REST uses the same host, token and URL prefix as `ha_url`, translating `ws`/`wss`
to `http`/`https`. A reverse proxy must allow `GET /api/states/<entity_id>` as well
as WebSockets. Requests are serialized through one reusable HTTP session. An
outstanding slow request is awaited rather than replaced every five seconds;
disconnect and shutdown cannot start an overlapping request or publish a late
response. HTTP failures make the affected channel unavailable; WebSocket events
or a subsequent successful revalidation can restore it.

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
- `timeout_seconds`: `10` for power/status requests and authentication.
- `energy_timeout_seconds`: `3` for each energy request's connect and read
  timeout. This does not impose a total deadline on token refresh or a response.
- `stale_after_seconds`: `30` for power freshness; must exceed the power interval.
- `status_interval_seconds`: `15` for meter connection status.
- `status_stale_after_seconds`: `30`; must exceed the status interval.
- `solar_invert`: `true` to invert channels identified as solar.

The client batches channel reads and reuses an HTTPS connection pool. It reads
at most one due energy period between power polls, choosing the oldest due
period so daily requests cannot starve monthly requests. Failed energy reads
retry with a bounded backoff (normally 5, 10, 20 seconds, up to 5 minutes),
instead of waiting the full daily/monthly interval. Energy's freshness limit is twice its polling interval plus
30 seconds. Missing or stale direct readings become unavailable. Meter status
must also be current and connected; a successful cloud response alone does not
establish availability. A measured zero remains zero.

Configured meter online/offline transitions are logged once per change. A
successful HTTP response while the meter is offline still leaves power
unavailable; cached energy has its own freshness limit.

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
`/CustomName` and `/DeviceInstance`. HA mode also exposes `/LastUpdate` as the
accepted source timestamp. Direct mode also exposes:

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
Emporia metadata are absent.

Venus OS MQTT publishes these paths under
`N/<portal-id>/acload/<instance>/<path>`. For example, channel 71 power is
`N/<portal-id>/acload/71/Ac/Power`. Payloads contain a JSON `value` field.
See the [MQTT guide](home-assistant-mqtt.md) for bridge prefixes, keepalive,
availability and energy statistics.
