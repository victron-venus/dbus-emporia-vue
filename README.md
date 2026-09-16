# dbus-emporia-vue

Emporia Vue power and energy monitoring for Victron Venus OS. Each configured
channel registers a `com.victronenergy.acload.*` D-Bus service. Select either
Emporia Cloud or Home Assistant as the data source.

<!-- ci-release-process:start -->
## Release process

See the [release strategy](RELEASING.md) for validation, nightly, beta, RC and stable promotion rules, and the [operator runbook](docs/release-workflow.md) for local commands.
<!-- ci-release-process:end -->

## Configuration

Copy `config.json.example` to `config.json` and configure the channel mappings:

```json
{
  "source": "emporia",
  "emporia": {
    "token_file": "emporia-tokens.json",
    "credentials_file": "emporia-credentials.json",
    "poll_interval_seconds": 3,
    "day_interval_seconds": 900,
    "month_interval_seconds": 3600,
    "timeout_seconds": 10,
    "stale_after_seconds": 30,
    "solar_invert": true
  },
  "channels": [
    {
      "emporia_device_gid": 123456,
      "emporia_channel": "1",
      "id": "channel_1",
      "service_name": "com.victronenergy.acload.emporia_ch1",
      "instance": 71,
      "custom_name": "Heat Pump",
      "position": 0
    }
  ],
  "submeter": null,
  "log_level": "INFO"
}
```

Create `emporia-credentials.json` directly on the GX device:

```json
{
  "username": "your-emporia-email@example.com",
  "password": "YOUR_EMPORIA_PASSWORD"
}
```

Restrict credentials and token files to mode `0600`. The driver creates and
refreshes the token file automatically. For token-only authentication, remove
the `credentials_file` key and provide a valid token file. A configured
credentials file must exist even when cached tokens are available.
Alternatively, omit `credentials_file` and set `EMPORIA_USERNAME` and
`EMPORIA_PASSWORD` in the service environment.
Keep these files private; deployments do not upload them. Relative paths are
resolved beside `config.json`.

- `source`: `"emporia"` or `"home_assistant"`. The default is `"home_assistant"`
  for existing configurations. Only the selected source connects.
- `id`: stable channel identifier. Existing `ha_entity_id` identifiers remain
  supported.
- `emporia_device_gid` and `emporia_channel`: device ID and channel string.
  Main channels may use `"1,2,3"`.
- `emporia_import_channel` and `emporia_export_channel`: optional main-meter
  energy channels, typically `"MainsFromGrid"` and `"MainsToGrid"`.
- `power_multiplier`: optional power and energy multiplier, default `1`.
- `solar_invert`: invert channels identified as solar, default `true`.
- `ha_entity_id`: power entity used in Home Assistant mode. This mode also
  requires `ha_url` and `ha_token`.
- `service_name` and `instance`: unique D-Bus name and DeviceInstance. Preserve
  these values when updating an existing installation.
- `position`: `0` for AC output, `1` for AC input.
- `submeter`: optional `{"channel": "channel_1", "stale_after_seconds": 30}`
  selecting one configured `id` or legacy `ha_entity_id`.
  Power remains signed and is mirrored to L1. No additional grid meter is created.

The direct client batches channel reads and keeps only current values.
Power defaults to a 3-second poll; daily and monthly energy use separate
15-minute and 1-hour polls. Internet access is required.
Meter connection status is checked every 15 seconds and expires after
30 seconds; a successful cloud read alone does not establish meter availability.

Unavailable readings publish invalid power and `/Connected=0`. A measured
zero remains zero. Direct mode clears stale readings after 30 seconds by
default. Change `source` and restart the service to switch modes manually.

For Home Assistant mode, set `source` to `"home_assistant"`, configure
`ha_url` (for example, `"ws://192.168.1.50:8123/api/websocket"`) and a long-lived
`ha_token`, then set each channel's `ha_entity_id`. Emporia credentials are
not required in this mode. Direct mode does not require HA credentials.

For Home Assistant configuration discovery, run `ha_config_gen.py` on a
workstation with `HA_URL` and `HA_TOKEN` set. Review the generated `config.json`
before use. The command overwrites the local file.

## D-Bus and MQTT

See [Home Assistant through Cerbo GX MQTT](docs/home-assistant-mqtt.md) for the
broker bridge, source configuration, ready-to-use HA package, availability,
energy dashboard options and troubleshooting.

Channel services expose standard power paths `/Ac/Power`, `/Ac/L1/Power`,
`/Connected`, `/CustomName` and `/DeviceInstance`. Directly mapped channels
also expose:

- `/Source/Type`: `emporia` or `unavailable`.
- `/LastUpdate`: selected power timestamp, in Unix seconds.
- `/Emporia/DeviceId` and `/Emporia/Channel`: channel identity.
- `/Emporia/Energy/Day` and `/Emporia/Energy/Month`: period energy in kWh.
- `/Emporia/Energy/DayUpdated` and `/Emporia/Energy/MonthUpdated`: energy
  timestamps, in Unix seconds.
- `/Emporia/Energy/DaySample` and `/Emporia/Energy/MonthSample`: JSON strings
  containing the energy `value` and its `timestamp` together.
- `/Emporia/Energy/Import/Day`, `/Emporia/Energy/Import/Month`,
  `/Emporia/Energy/Export/Day` and `/Emporia/Energy/Export/Month`: optional
  import and export energy in kWh, each with `Updated` and `Sample` paths.

Daily and monthly values reset at period boundaries. They are not lifetime
counters; `/Ac/Energy/Forward` stays unavailable.

Venus OS MQTT publishes service paths under
`N/<portal-id>/acload/<instance>/<path>`. For example, channel 71 power is
`N/<portal-id>/acload/71/Ac/Power` and daily energy is
`N/<portal-id>/acload/71/Emporia/Energy/Day`. Values use the JSON `value` field.
Use `/Connected` for power availability and the energy timestamps for energy
freshness. Keep the GX MQTT subscription alive as required by Venus OS.
Home Assistant source entities must remain independent of this driver's MQTT output.

## Installation

Requires Python 3.11+, `dbus-fast` and `websockets`. Direct mode also requires
`pyemvue` and its dependencies. `aiovelib` is included in the package.

Place compatible dependencies in `/data/dbus-emporia-vue/vendor`. The service
and installer prepend this directory to `PYTHONPATH`; updates preserve it.
Use the checked-in hash lock and a target-compatible Python interpreter:

```sh
python3 -m pip install --require-hashes --target /data/dbus-emporia-vue/vendor -r requirements.lock
PYTHONPATH=/data/dbus-emporia-vue/vendor python3 -c "import dbus_fast, websockets, pyemvue"
```

Do not install into the read-only firmware filesystem. Firmware updates may
replace system dependencies; verify them after each update. The installer
checks imports before stopping the service and never runs `pip`.

To deploy from a workstation, run `./deploy.sh root@cerbo` using SSH key
authentication. The deployment contains declared, tracked runtime files and
the local `config.json`, if present. Local configuration replaces the device
configuration; credentials and token files stay on the device.

For SetupHelper / PackageManager, place the complete package in
`/data/dbus-emporia-vue`, configure `config.json`, then run:

```sh
cd /data/dbus-emporia-vue
./setup install
```

SetupHelper must be installed at `/data/SetupHelper`. Without SetupHelper,
use `sh update.sh`. Both paths use the same updater. Updates preserve local
configuration, credentials, token files and existing service supervisors.

## Operation

```sh
# Start, stop or restart
svc -u /service/dbus-emporia-vue
svc -d /service/dbus-emporia-vue
svc -t /service/dbus-emporia-vue

# Inspect the service and a channel
svstat /service/dbus-emporia-vue /service/dbus-emporia-vue/log
tail -n 40 /var/log/dbus-emporia-vue/current
dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
```

The persistent service directory is
`/data/dbus-emporia-vue/service/dbus-emporia-vue`. A boot hook recreates its
`/service/dbus-emporia-vue` symlink. Logs rotate four 25 KB files; the heartbeat
is written atomically to `/tmp/dbus-emporia-vue.heartbeat`.

The updater stops only the application and retains the running logger. A stuck
worker receives one supervisor-scoped kill after 20 seconds; installation
aborts if it has not stopped after 25 seconds. Unexpected service paths are
rejected before stopping. Restore a previous release using its `update.sh`
and the existing device-local configuration.

`deploy.sh` waits for a new heartbeat and a running process. Also inspect
`/Connected`, `/Source/Type` and `/LastUpdate` to verify data availability.
`./setup uninstall` removes the service and boot hook.

## License

MIT
