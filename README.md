# dbus-emporia-vue

A Python service for Victron Venus OS (Cerbo GX) that reads power measurements from Home Assistant via WebSocket API and registers individual AC loads on the Venus OS DBus system.

<!-- ci-release-process:start -->
## Release process

See the [release strategy](RELEASING.md) for validation, nightly, beta, RC and stable promotion rules, and the [operator runbook](docs/release-workflow.md) for local commands.
<!-- ci-release-process:end -->

## Features

- Connects to Home Assistant via WebSocket API with long-lived access token authentication
- Subscribes only to the configured power sensors using HA `subscribe_trigger` (state-based triggers), keeping load on the GX device minimal
- Loads the current value of every channel via HA `get_states` on startup
- Registers each channel as a `com.victronenergy.acload.*` service on DBus using the standard `com.victronenergy.BusItem` interface (via a vendored copy of `aiovelib`)
- Assigns unique DeviceInstance numbers (configurable per channel) to avoid conflicts
- Tracks HA and sensor availability: channels are marked `Connected=0` when their sensor is unavailable or the WebSocket link is down
- Optionally marks one configured aggregate channel as a signed grid submeter for a separate controller to use as a fallback
- Provides example configuration and easy installation
- Can be installed via Venus OS PackageManager (using SetupHelper) – same pattern as `dbus-mqtt-battery`, `dbus-tasmota-pv`, `inverter-control`

## Current Integration and Future Plans

**Current:** The service obtains power data from Home Assistant via its WebSocket API. This is the simplest and most reliable method today, as the Emporia Vue integration already publishes individual channel power sensors to Home Assistant.

**Future:** We plan to add a direct connection to the Emporia Vue web portal/local API to eliminate the extra hop through Home Assistant. This will reduce latency and avoid maintaining two separate connections (HA + Vue) for the same data. For now, using Home Assistant is sufficient and keeps the architecture simple.

## Installation

### Deploy from a workstation

1. Copy `config.json.example` to `config.json` and configure the HA URL, token
   and channel mappings. Keep this file private.
2. Check that the GX system Python can import `dbus_fast` and `websockets`.
   Do not run a global `pip install` on the firmware filesystem. If packages are
   missing, provide a compatible dependency bundle on persistent storage and
   verify it with the same interpreter used by the service.
3. Run `./deploy.sh root@cerbo` using SSH key authentication. The workstation
   may also generate the local configuration using `HA_URL` and `HA_TOKEN`.

### SetupHelper / PackageManager

Place the complete package in `/data/dbus-emporia-vue`, configure `config.json`,
and run the SetupHelper entry point:

```sh
cd /data/dbus-emporia-vue
./setup install
```

The same `update.sh` installs both a release archive and an in-place reinstall.
The vendored `aiovelib` and persistent service definitions are installed together.
SetupHelper must already be available at `/data/SetupHelper`. Use
`./setup uninstall` to remove the service and boot hook; configuration is retained.
Without SetupHelper, a prepared release can be installed with `sh update.sh`.

## Configuration

Edit `config.json` with the following structure:

```json
{
  "ha_url": "ws://<YOUR_HOME_ASSISTANT_IP>:8123/api/websocket",
  "ha_token": "YOUR_LONG_LIVED_ACCESS_TOKEN",
  "channels": [
    {
      "ha_entity_id": "sensor.emporia_channel_1_power",
      "service_name": "com.victronenergy.acload.emporia_ch1",
      "instance": 71,
      "custom_name": "Heat Pump",
      "position": 0
    }
  ],
  "submeter": {
    "channel": "sensor.emporia_channel_1_power",
    "stale_after_seconds": 30
  },
  "log_level": "INFO"
}
```

- `ha_url`: WebSocket URL of your Home Assistant instance
- `ha_token`: Long-lived access token from Home Assistant (create in Profile → Long-Lived Access Tokens)
- `channels`: Array of channel configurations:
  - `ha_entity_id`: Entity ID of the power sensor in Home Assistant (should report power in Watts)
  - `service_name`: DBus service name (must be unique, use the pattern `com.victronenergy.acload.emporia_chX`)
  - `instance`: DeviceInstance number (integer). **Choose numbers that do not conflict with existing devices on the VeBus.**
    On a typical Venus OS system, numbers 41‑56 are partially occupied (e.g., 45 and 52 are used). A free block is 71‑86, so you may start at 71 and increment for each channel.
  - `custom_name`: Display name for the load (e.g., "Heat Pump", "Dryer")
  - `position`: AC position of the load:
    - `0` = AC output → shown under **Essential Loads** in the GUI
    - `1` = AC input → shown under **AC Loads** in the GUI
- `log_level`: `INFO` (default), `DEBUG` or `ERROR`
- `submeter`: optional. Set it to `null` to disable the role, or select exactly
  one `ha_entity_id` already listed in `channels`. The selected AC-load service
  publishes the standard Victron AC energy-meter identity (`/Role=acload`,
  `/AllowedRoles`, `/Position`, `/Serial`, `/NrOfPhases`, and `/RefreshTime`),
  plus `/LastUpdate` and `/Source/EntityId` for freshness and provenance.
  `/Ac/Power` remains the signed aggregate value and is mirrored to L1 because
  the source has no independent per-phase measurements.
  The service disconnects and clears power after `stale_after_seconds` without
  a fresh source timestamp.

### How to verify free DeviceInstance numbers

On the Venus OS device, you can list all DeviceInstance values currently in use:

```bash
ssh root@cerbo "dbus -y com.victronenergy.vebus.ttyUSB2 / GetItems | grep -a DeviceInstance"
```

Look for gaps in the output; choose numbers that do not appear.

### Automatic configuration generation

If you prefer not to manually list each channel, you can use the helper script `ha_config_gen.py` to query Home Assistant for all power sensors (unit_of_measurement == 'W') and generate a `config.json` with sequential DeviceInstance numbers starting at 71.

Usage (run on a machine with network access to your HA instance):
```bash
HA_URL=ws://<HA_IP>:8123/api/websocket HA_TOKEN=<your_long_lived_token> python ha_config_gen.py
```
The script will create (or overwrite) `config.json` in the current directory. Review the generated file and adjust `instance` numbers if needed to avoid collisions.

## Service Management on Venus OS

When installed via the setup script, the service is automatically created under `/service/dbus-emporia-vue` and supervised by daemontools. It will start on boot and restart after firmware updates.

To manually control the service:
```bash
# Start
svc -u /service/dbus-emporia-vue
# Stop
svc -d /service/dbus-emporia-vue
# Restart
svc -t /service/dbus-emporia-vue
# View logs
tail -n 40 /var/log/dbus-emporia-vue/current
```

### Verifying installation

After starting the service, you can confirm that the DBus services are registered:

```bash
# List all acload services on the system bus
ssh root@cerbo "dbus -y org.freedesktop.DBus /org/freedesktop/DBus ListNames | grep acload"

# Inspect one channel's exported paths
ssh root@cerbo "dbus -y com.victronenergy.acload.emporia_ch1 / GetItems"
```
You should see the standard Venus paths (`/Ac/Power`, `/Ac/L1/Power`, `/Connected`, `/CustomName`, `/DeviceInstance`, ...) with live values, and the system service should report:
```bash
ssh root@cerbo "dbus -y com.victronenergy.system /Ac/HasAcLoads GetValue"
# 1
```

## Notes

- This service does not register another `com.victronenergy.grid` meter. The
  optional selected channel remains `com.victronenergy.acload.*`, with the
  standard `acload` role and position used by Victron energy meters.
- Make sure the DeviceInstance numbers (instance) do not conflict with existing Victron devices. Use the verification method above to pick a free range.
- Because the subscription uses HA state *triggers*, idle channels (whose reading does not change) keep their last known value and are still reported as connected to HA.

## Dependencies

- Python 3.11+ (verified on Venus OS v3.75 with Python 3.12)
- dbus-fast
- websockets
- requests (used by ha_config_gen.py)
- `aiovelib` (vendored under `aiovelib/`; `deploy.sh` copies it to the GX device, with a fallback to the copies shipped in `/opt/victronenergy/dbus-*/ext/aiovelib`)

## License

MIT

## Venus OS installation and recovery

Use the canonical `/data/dbus-emporia-vue` directory. Both `setup install`
(SetupHelper/PackageManager) and the workstation `deploy.sh` call `update.sh`.
A release is staged under volatile `/tmp` before stopping the service, so
reinstalling from the installed tree does not delete the update source.
The updater preserves `config.json`; `deploy.sh` deliberately replaces it
when the workstation has a local copy (`PUSH_LOCAL_CONFIG=1`).
Existing service and log directory inodes, ownership, supervisor state and the
canonical `/service` symlink are preserved. Only the application is stopped;
run scripts are replaced atomically and a healthy logger keeps running.
Ordinary updates do not restart PackageManager. A stuck application receives
one supervisor-scoped kill after twenty seconds; installation aborts if it is
still running after twenty-five seconds. Unexpected service links, real `/service`
directories or legacy firmware copies require a separate migration before
updating; the updater leaves them untouched.

SIGTERM and SIGINT cancel and join the WebSocket and heartbeat workers before
releasing channel services. WebSocket close and D-Bus release are bounded;
each channel's private bus is disconnected even if name release fails. Normal
shutdown does not raise `SystemExit` in a background task.

Service definitions persist under `/data/dbus-emporia-vue/service/dbus-emporia-vue`.
`/service/dbus-emporia-vue` is a symlink recreated by `/data/rc.local`, including
when that script already ends with `exit 0`. The logger recreates its
`/var/log/dbus-emporia-vue` directory and rotates four 25 KB files. On the audited
Venus image `/var/log` resolves to persistent `/data/log`, so rotation bounds flash
usage. Heartbeats live on volatile storage. Runtime data does not require writes to the
read-only firmware filesystem. Firmware updates can replace system Python
packages; check dependencies after each update before assuming the service is
healthy. The installer does not run `pip` or upgrade system packages.

Before installation, check the target interpreter:

```sh
python3 --version
python3 -c "import dbus_fast, websockets"
```

Verify a running process and its D-Bus data after installation:

```sh
svstat /service/dbus-emporia-vue /service/dbus-emporia-vue/log
readlink /service/dbus-emporia-vue
tail -n 40 /var/log/dbus-emporia-vue/current
```

`update.sh` confirms termination before copying but does not wait for a fresh
process or heartbeat after requesting startup. The deployment caller must
verify startup and D-Bus availability.

`deploy.sh` fails if a fresh heartbeat does not appear within 60 seconds or the
service never reaches `up`. A heartbeat proves the loop is running, not that
Home Assistant is reachable: also inspect `/Connected` and the log. Restore a
previous release with its `update.sh`, keeping the device-local configuration.
Installer regressions cover repeated updates with live directory handles,
supervisor-state and ownership preservation, atomic run-script replacement,
configuration, safe rejection before stopping, and boot hooks before `exit 0`.


### Home Assistant outage behavior

Connection refusals, socket failures and timeouts retry with exponential backoff
(up to 60 seconds, plus jitter) while D-Bus names stay registered. Authentication,
subscription and initial-state loading share a 30-second deadline. Unknown,
unavailable, malformed and non-finite power readings publish invalid values;
a valid reading of zero remains zero. A connected WebSocket alone does not make
missing channels connected. Energy is unavailable because this bridge receives
power measurements, not cumulative energy.

Initial loading preserves state-trigger updates received while `get_states`
is in flight. A snapshot replaces an interleaved event only when both HA state
objects provide `last_updated` and identify the snapshot as newer; otherwise
the already received event wins. This comparison is scoped to initial loading,
so it cannot reject later events after an HA clock adjustment. The existing
50-message initialization cap and 30-second connection deadline remain intact.
Regressions cover older/newer snapshots, unavailable power, measured zero,
missing timestamps and a failed initial query. The state timestamps follow the
[Home Assistant WebSocket API](https://developers.home-assistant.io/docs/api/websocket/).

A stable channel is not disconnected merely because its value does not change.
WebSocket availability and HA state timestamps do not independently verify the
physical Emporia sensor or its upstream integration.


Dependency bundles should use the checked-in hash lock:
`python3 -m pip install --require-hashes -r requirements.lock` in the selected
persistent environment, not the firmware filesystem. `requirements.lock` is
included in the deployed runtime for reproducibility.

The heartbeat is replaced atomically, so readers never see a partial timestamp
and an existing symlink cannot redirect writes. It remains at
`/tmp/dbus-emporia-vue.heartbeat`, readable by the service account.
